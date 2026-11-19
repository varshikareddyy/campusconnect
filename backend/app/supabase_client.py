import os
from dotenv import load_dotenv
from supabase import Client, create_client

# Read backend/.env
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY in backend/.env")

# One shared connection used by the whole backend
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)