# db_helper.py
"""
Lovable Cloud DB integration layer for AI Outreach Agent.
Uses Supabase REST API via supabase-py client.
Safe for use with Anon Key (RLS-protected).
"""

import os, json, datetime
from supabase import create_client, Client

# -------------------------------------------------------------------
# Connection setup
# -------------------------------------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Supabase credentials not found in environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# -------------------------------------------------------------------
# Utilities
# -------------------------------------------------------------------
def now_iso():
    return datetime.datetime.utcnow().isoformat()

# -------------------------------------------------------------------
# Job operations
# -------------------------------------------------------------------
def create_job(user_id: str, filename: str, payload: dict = None):
    """Insert a new job into the database."""
    data = {
        "user_id": user_id,
        "filename": filename,
        "status": "queued",
        "progress": 0,
        "payload": payload or {},
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    result = supabase.table("jobs").insert(data).execute()
    if result.data:
        return result.data[0]
    raise RuntimeError(f"Failed to create job: {result}")

def update_job(job_id: int, **fields):
    """Update an existing job."""
    fields["updated_at"] = now_iso()
    supabase.table("jobs").update(fields).eq("id", job_id).execute()

def get_job(job_id: int):
    """Retrieve one job by ID."""
    result = supabase.table("jobs").select("*").eq("id", job_id).execute()
    return result.data[0] if result.data else None

def list_jobs(user_id: str = None):
    """List jobs (filtered by user if provided)."""
    query = supabase.table("jobs").select("*")
    if user_id:
        query = query.eq("user_id", user_id)
    result = query.order("id", desc=True).execute()
    return result.data or []

# -------------------------------------------------------------------
# Logging
# -------------------------------------------------------------------
def log_event(level: str, message: str, **extra):
    """Record a log entry."""
    data = {
        "time": now_iso(),
        "level": level,
        "message": message,
        "extra": extra or {},
    }
    supabase.table("logs").insert(data).execute()

# -------------------------------------------------------------------
# Convenience wrapper for pipeline
# -------------------------------------------------------------------
def save_result(job_id: int, data: dict, output_url: str = None):
    """Store pipeline output JSON for a job."""
    update_job(job_id, status="succeeded", progress=100, output_url=output_url, payload=data)