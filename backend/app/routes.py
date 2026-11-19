from typing import Optional
from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel
from postgrest.exceptions import APIError  # used later, in the race-condition fix

from app.supabase_client import supabase

router = APIRouter(prefix="/api", tags=["CampusConnect API"])


class RegistrationRequest(BaseModel):
    event_id: str


# FR-02: Browse events (optional search by title)
@router.get("/events", summary="Browse all campus events")
def list_events(search: Optional[str] = None):
    query = supabase.table("events").select("id, title, capacity, status, organizer_id")
    if search:
        query = query.ilike("title", f"%{search}%")
    return query.execute().data


# FR-03: One event, plus how many seats are left
@router.get("/events/{event_id}", summary="Get single event details")
def get_event_details(event_id: str):
    event_res = supabase.table("events").select("*").eq("id", event_id).execute()
    if not event_res.data:
        raise HTTPException(status_code=404, detail="Event not found")
    event = event_res.data[0]

    count_res = (
        supabase.table("registrations")
        .select("id", count="exact")
        .eq("event_id", event_id)
        .execute()
    )
    booked = count_res.count or 0
    return {**event, "booked_seats": booked, "seats_left": max(0, event["capacity"] - booked)}


# FR-04 (UNSAFE version, replaced later by the database lock): register the current student
@router.post("/registrations", status_code=status.HTTP_201_CREATED, summary="Register for an event")
def register_for_event(payload: RegistrationRequest, x_user_id: Optional[str] = Header(default=None)):
    # Guard 1: who is asking?
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Guard 2: the event must exist and be open
    event_res = supabase.table("events").select("*").eq("id", payload.event_id).execute()
    if not event_res.data:
        raise HTTPException(status_code=404, detail="Event not found")
    event = event_res.data[0]
    if event["status"] != "open":
        raise HTTPException(status_code=400, detail="Event is closed for registration")

    # Guard 3: no duplicate registration
    existing = (
        supabase.table("registrations")
        .select("id")
        .eq("user_id", x_user_id)
        .eq("event_id", payload.event_id)
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=409, detail="DUPLICATE_REGISTRATION")

    # Guard 4: seats must be left (race condition: check, then act)
    count_res = (
        supabase.table("registrations")
        .select("id", count="exact")
        .eq("event_id", payload.event_id)
        .execute()
    )
    if (count_res.count or 0) >= event["capacity"]:
        raise HTTPException(status_code=409, detail="EVENT_FULL")

    # Guard 5: save the registration
    insert_res = (
        supabase.table("registrations")
        .insert({"user_id": x_user_id, "event_id": payload.event_id})
        .execute()
    )
    new_reg = insert_res.data[0]
    return {"id": new_reg["id"], "event_id": payload.event_id, "status": "REGISTERED"}


# FR-06: The current student's registrations
@router.get("/me/registrations", summary="My registrations")
def get_my_registrations(x_user_id: Optional[str] = Header(default=None)):
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    res = (
        supabase.table("registrations")
        .select("id, created_at, events(id, title, capacity, status)")
        .eq("user_id", x_user_id)
        .execute()
    )
    return res.data


# FR-07: Attendee list, only for the organizer who owns the event
@router.get("/events/{event_id}/registrations", summary="Attendees for an event you own")
def get_event_attendees(event_id: str, x_user_id: Optional[str] = Header(default=None)):
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    event_res = supabase.table("events").select("organizer_id").eq("id", event_id).execute()
    if not event_res.data:
        raise HTTPException(status_code=404, detail="Event not found")
    if event_res.data[0]["organizer_id"] != x_user_id:
        raise HTTPException(status_code=403, detail="Forbidden: you can only view attendees for events you own")

    res = (
        supabase.table("registrations")
        .select("id, created_at, users(id, email, role)")
        .eq("event_id", event_id)
        .execute()
    )
    return res.data