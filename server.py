# server.py
# FastAPI server for AI Outreach Agent
# Integrated with Supabase Storage and background worker

import os
import json
import uuid
import threading
import queue
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import requests
import traceback
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Request, Header, Path
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from starlette.middleware.base import BaseHTTPMiddleware
from supabase import create_client

# 🧩 FIXED IMPORT PATHS
from backend.parser import read_input_file, validate_columns
from auth import router as auth_router, get_current_user, User
from backend.db_helper import create_job, update_job, get_job, list_jobs
from backend.pipeline import run_pipeline  # ✅ key fix

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------
APP_VERSION = "1.4.5 — Indentation fix + pipeline import"

ROOT = os.getcwd()
UPLOADS_DIR = os.path.join(ROOT, "uploads")
OUTPUTS_DIR = os.path.join(ROOT, "outputs")
DOWNLOADS_DIR = os.path.join(ROOT, "downloads")
LOG_FILE = os.path.join(ROOT, "logging.json")
JOBS_FILE = os.path.join(ROOT, "jobs.json")

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

def _ensure_json(path: str, default):
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f)

_ensure_json(JOBS_FILE, [])
_ensure_json(LOG_FILE, [])

load_dotenv()
PUBLIC_READ = os.getenv("PUBLIC_READ", "1") == "1"
RETRY_API_KEY = (os.getenv("RETRY_API_KEY") or "").strip()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "job-uploads")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("Supabase credentials are missing from environment variables.")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# -------------------------------------------------------------------
# Utility
# -------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _read_json(path: str, fallback):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return fallback

def _write_json(path: str, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def log_event(level: str, message: str, **extra):
    logs = _read_json(LOG_FILE, [])
    entry = {"time": now_iso(), "level": level, "message": message}
    if extra:
        entry.update(extra)
    logs.append(entry)
    _write_json(LOG_FILE, logs)
    print(f"[{level}] {message} {extra if extra else ''}")

# -------------------------------------------------------------------
# FastAPI app setup
# -------------------------------------------------------------------
app = FastAPI(title="AI Outreach Agent", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://signal-job.lovable.app",
        "https://lovable.app",
        "https://lovableproject.com",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response

app.add_middleware(RequestIDMiddleware)
app.include_router(auth_router)

# -------------------------------------------------------------------
# Models
# -------------------------------------------------------------------
class CaseStudy(BaseModel):
    title: str
    description: Optional[str] = None
    url: Optional[str] = None

class MessagingInputs(BaseModel):
    positioning_statement: Optional[str] = None
    case_studies: Optional[List[CaseStudy]] = []
    primary_cta: Optional[str] = None
    secondary_cta: Optional[str] = None
    tone_preference: Optional[str] = None

class TargetingCriteria(BaseModel):
    industries: Optional[List[str]] = []
    roles: Optional[List[str]] = []
    company_size: Optional[List[str]] = []
    regions: Optional[List[str]] = []

# -------------------------------------------------------------------
# Health check
# -------------------------------------------------------------------
@app.get("/health")
def health_check():
    try:
        db_ok = True
        try:
            _ = list_jobs()[:1]
        except Exception as db_err:
            db_ok = False
            log_event("WARN", "Health DB check failed", error=str(db_err))
        return {
            "status": "ok",
            "service": "ai_outreach_agent",
            "version": APP_VERSION,
            "time": now_iso(),
            "public_read": PUBLIC_READ,
            "db_ok": db_ok,
            "retry_api_key_set": bool(RETRY_API_KEY),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {e}")

# -------------------------------------------------------------------
# Background worker
# -------------------------------------------------------------------
work_q: "queue.Queue[int]" = queue.Queue()
_worker_started = False

def _ensure_worker():
    global _worker_started
    if not _worker_started:
        threading.Thread(target=_worker_loop, daemon=True).start()
        _worker_started = True
        log_event("INFO", "Worker thread started")

def _worker_loop():
    while True:
        jid = work_q.get()
        try:
            process_job(jid)
        except Exception as e:
            log_event("ERROR", "Worker crashed", job_id=jid, error=str(e))
        finally:
            work_q.task_done()

def _get_job_by_id(job_id: int) -> Optional[Dict[str, Any]]:
    try:
        j = get_job(job_id)
        if j:
            return j
    except Exception as e:
        log_event("ERROR", "DB read failed", job_id=job_id, error=str(e))
    for j in _read_json(JOBS_FILE, []):
        if str(j.get("id")) == str(job_id):
            return j
    return None

# -------------------------------------------------------------------
# 🧠 PROCESS JOB
# -------------------------------------------------------------------
def process_job(job_id: int):
    """
    Processes a queued job:
    1. Downloads the uploaded Excel from Supabase
    2. Runs the enrichment + outreach pipeline
    3. Uploads the processed Excel back to Supabase
    4. Updates the job status and logs progress
    """
    try:
        job = _get_job_by_id(job_id)
        if not job:
            log_event("ERROR", "Job not found", job_id=job_id)
            return

        if job.get("status") == "succeeded":
            log_event("INFO", "Skip already-succeeded job", job_id=job_id)
            return

        _update_job(job_id, status="processing", updated_at=now_iso(), progress=5)
        filename = job.get("filename")
        file_url = job.get("file_url")

        if not filename:
            raise ValueError("Missing filename for job")
        if not file_url:
            raise ValueError("Missing file_url for job")

        log_event("INFO", "Downloading input file", job_id=job_id, file_url=file_url)
        response = requests.get(file_url, timeout=30)
        response.raise_for_status()

        local_path = os.path.join(UPLOADS_DIR, filename)
        with open(local_path, "wb") as f:
            f.write(response.content)

        _update_job(job_id, progress=25)
        log_event("INFO", "Starting pipeline", job_id=job_id, input_file=filename)

        output_path = run_pipeline(local_path, str(job_id), OUTPUTS_DIR)
        _update_job(job_id, progress=90)
        log_event("INFO", "Pipeline complete", job_id=job_id, output_file=output_path)

        processed_name = os.path.basename(output_path)
        storage_key = f"processed/{processed_name}"
        with open(output_path, "rb") as f:
            supabase.storage.from_(SUPABASE_BUCKET).upload(storage_key, f, {"upsert": True})
        output_url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(storage_key)

        _update_job(job_id, status="succeeded", progress=100, output_url=output_url)
        log_event("INFO", "Job succeeded", job_id=job_id, output_url=output_url)

    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}"
        tb = traceback.format_exc()
        _update_job(job_id, status="failed", error=err_msg)
        log_event("ERROR", "Job failed", job_id=job_id, error=err_msg, traceback=tb)

def _update_job(job_id: int, **patch):
    try:
        update_job(job_id, **patch)
    except Exception as e:
        log_event("WARN", "DB update failed", job_id=job_id, error=str(e))
        jobs = _read_json(JOBS_FILE, [])
        for j in jobs:
            if str(j.get("id")) == str(job_id):
                j.update(patch)
                break
        _write_json(JOBS_FILE, jobs)

# -------------------------------------------------------------------
# Upload + Create Job
# -------------------------------------------------------------------
@app.post("/jobs")
def create_job_endpoint(
    file: UploadFile = File(...),
    notes: Optional[str] = Form(None),
    current: User = Depends(get_current_user)
):
    safe_name = f"{uuid.uuid4().hex}_{os.path.basename(file.filename)}"
    contents = file.file.read()
    file.file.close()

    try:
        supabase.storage.from_(SUPABASE_BUCKET).upload(f"jobs/{safe_name}", contents)
        file_url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(f"jobs/{safe_name}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload to Supabase failed: {e}")

    payload = {"notes": notes or ""}
    try:
        job = create_job(
            user_id=str(current.id),
            filename=safe_name,
            payload=payload,
            file_url=file_url,
        )
    except TypeError:
        job = create_job(user_id=str(current.id), filename=safe_name, payload=payload)
        update_job(job.get("id"), file_url=file_url)

    job_id = job.get("id")
    _ensure_worker()
    work_q.put(job_id)
    log_event("INFO", "Job created and queued", job_id=job_id, filename=safe_name)

    return {"ok": True, "job_id": job_id, "filename": safe_name, "file_url": file_url, "status": "queued"}

# -------------------------------------------------------------------
# Retry endpoints
# -------------------------------------------------------------------
@app.post("/retry-queued")
def retry_queued(request: Request, x_api_key: Optional[str] = Header(default=None)):
    supplied = (
        request.headers.get("authorization", "")
        .replace("Bearer ", "")
        .strip()
        or x_api_key
        or ""
    )

    if supplied != RETRY_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    jobs = list_jobs()
    queued = [j for j in jobs if j.get("status") == "queued"]
    if not queued:
        log_event("INFO", "No queued jobs found")
        return {"ok": True, "message": "No queued jobs found.", "count": 0}

    _ensure_worker()
    for j in queued:
        work_q.put(j["id"])

    log_event("INFO", f"Requeued {len(queued)} jobs", count=len(queued))
    return {"ok": True, "message": f"Requeued {len(queued)} job(s).", "count": len(queued)}

@app.post("/retry-job/{job_id}")
def retry_job(request: Request, job_id: int = Path(...), x_api_key: Optional[str] = Header(default=None)):
    supplied = (
        request.headers.get("authorization", "")
        .replace("Bearer ", "")
        .strip()
        or x_api_key
        or ""
    )

    if supplied != RETRY_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    job = _get_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.get("status") not in {"queued", "failed"}:
        return {"ok": False, "message": f"Job {job_id} is {job.get('status')}, not retried."}

    _ensure_worker()
    work_q.put(job_id)
    log_event("INFO", f"Manually retried job {job_id}")

    return {"ok": True, "message": f"Job {job_id} requeued."}

# -------------------------------------------------------------------
# Local entry point
# -------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=10000, reload=True)