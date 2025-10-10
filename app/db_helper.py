"""
Lovable Cloud DB integration layer for AI Outreach Agent.
Compatible with both Supabase (production) and local JSON fallback (development).
Provides db_insert_job / db_update_job / db_get_jobs interface expected by server.py.
"""

import os
import json
import datetime
from typing import List, Dict, Any, Optional
from supabase import create_client, Client

# -------------------------------------------------------------------
# Setup & Environment
# -------------------------------------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_ANON_KEY")

# Local fallback file for development
LOCAL_JOBS_FILE = os.path.join(os.getcwd(), "jobs.json")

def _ensure_local_json():
    if not os.path.exists(LOCAL_JOBS_FILE):
        with open(LOCAL_JOBS_FILE, "w") as f:
            json.dump([], f)
_ensure_local_json()

supabase: Optional[Client] = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"[WARN] Could not connect to Supabase: {e}")
else:
    print("[WARN] Supabase credentials missing — using local fallback.")

# -------------------------------------------------------------------
# Utilities
# -------------------------------------------------------------------
def now_iso() -> str:
    return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat()

def _read_local_jobs() -> List[Dict[str, Any]]:
    try:
        with open(LOCAL_JOBS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def _write_local_jobs(jobs: List[Dict[str, Any]]):
    with open(LOCAL_JOBS_FILE, "w") as f:
        json.dump(jobs, f, indent=2)

# -------------------------------------------------------------------
# Core DB Operations
# -------------------------------------------------------------------
def db_insert_job(data: Dict[str, Any]) -> Dict[str, Any]:
    """Insert a new job record and return it."""
    if supabase:
        result = supabase.table("jobs").insert(data).execute()
        if result.data:
            return result.data[0]
        raise RuntimeError(f"Failed to insert job: {result}")
    else:
        jobs = _read_local_jobs()
        data["id"] = len(jobs) + 1
        jobs.append(data)
        _write_local_jobs(jobs)
        return data

def db_update_job(job_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Update job by ID and return updated record."""
    patch["updated_at"] = now_iso()
    if supabase:
        result = supabase.table("jobs").update(patch).eq("id", job_id).execute()
        if result.data:
            return result.data[0]
        raise RuntimeError(f"Update failed for job {job_id}")
    else:
        jobs = _read_local_jobs()
        for j in jobs:
            if str(j.get("id")) == str(job_id):
                j.update(patch)
                _write_local_jobs(jobs)
                return j
        raise RuntimeError(f"Job not found locally: {job_id}")

def db_get_jobs(limit: int = 100) -> List[Dict[str, Any]]:
    """Fetch recent jobs."""
    if supabase:
        result = (
            supabase.table("jobs")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    else:
        jobs = _read_local_jobs()
        jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
        return jobs[-limit:]

def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve one job by ID."""
    if supabase:
        result = supabase.table("jobs").select("*").eq("id", job_id).execute()
        return result.data[0] if result.data else None
    else:
        jobs = _read_local_jobs()
        for j in jobs:
            if str(j.get("id")) == str(job_id):
                return j
        return None

# -------------------------------------------------------------------
# Compatibility Wrappers
# -------------------------------------------------------------------
def create_job(user_id: str, filename: str, payload: Optional[dict] = None):
    data = {
        "user_id": user_id,
        "filename": filename,
        "status": "queued",
        "progress": 0,
        "payload": payload or {},
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    return db_insert_job(data)

def update_job(job_id: str, **fields):
    return db_update_job(job_id, fields)

def list_jobs(user_id: Optional[str] = None):
    jobs = db_get_jobs()
    if user_id:
        jobs = [j for j in jobs if j.get("user_id") == user_id]
    return jobs