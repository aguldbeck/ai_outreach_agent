# server.py
# FastAPI server for AI Outreach Agent
# Handles job management, CSV processing, and background worker
# Authentication is handled via auth.py (JWT-based)

import os
import csv
import json
import uuid
import shutil
import threading
import queue
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# Internal imports
from parser import read_input_file, validate_columns
from auth import router as auth_router, get_current_user, get_current_user_optional, User
from app.db_helper import create_job, update_job, get_job, list_jobs

# -------------------------------------------------------------------
# Setup and paths
# -------------------------------------------------------------------
ROOT = os.getcwd()
UPLOADS_DIR = os.path.join(ROOT, "uploads")
OUTPUTS_DIR = os.path.join(ROOT, "outputs")
DOWNLOADS_DIR = os.path.join(ROOT, "downloads")
LOG_FILE = os.path.join(ROOT, "logging.json")
JOBS_FILE = os.path.join(ROOT, "jobs.json")
SAMPLE_FILE = os.path.join(ROOT, "sample_template.csv")

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
# Utility helpers
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

# -------------------------------------------------------------------
# FastAPI app and CORS
# -------------------------------------------------------------------
ALLOWED_ORIGINS = [
    "https://signal-job.lovable.app",
    "https://c67ff193-6790-48e9-ae0f-339691a82137.lovableproject.com",  # current Lovable preview
    "https://*.lovableproject.com",  # wildcard for future previews
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://ai-outreach-agent-fs4e.onrender.com",
]

app = FastAPI(title="AI Outreach Agent", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

# -------------------------------------------------------------------
# Routers
# -------------------------------------------------------------------
app.include_router(auth_router)

# -------------------------------------------------------------------
# Health Check
# -------------------------------------------------------------------
@app.get("/health")
def health_check():
    """Lightweight health check for uptime and DB connectivity."""
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
            "time": now_iso(),
            "public_read": PUBLIC_READ,
            "db_ok": db_ok,
            "allowed_origins": ALLOWED_ORIGINS,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {e}")

# -------------------------------------------------------------------
# Root endpoint
# -------------------------------------------------------------------
@app.get("/")
def root(request: Request):
    origin = request.headers.get("origin")
    return {
        "ok": True,
        "service": "ai_outreach_agent",
        "time": now_iso(),
        "origin": origin,
        "public_read": PUBLIC_READ,
    }

# -------------------------------------------------------------------
# Downloads
# -------------------------------------------------------------------
@app.get("/downloads/sample")
def download_sample():
    """Provide downloadable CSV template."""
    if not os.path.exists(SAMPLE_FILE):
        with open(SAMPLE_FILE, "w", newline="") as f:
            f.write(
                "name,company,job_title,linkedin_url,email,notes\n"
                "Jane Doe,Example Inc,Marketing Manager,https://linkedin.com/in/janedoe,"
                "jane@example.com,Interested in retention tools\n"
            )
    return FileResponse(SAMPLE_FILE, filename="sample_template.csv", media_type="text/csv")

@app.get("/downloads/{filename}")
def download_output(filename: str):
    """Allow users to download their processed output file."""
    path = os.path.join(OUTPUTS_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=filename)

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

def _worker_loop():
    while True:
        jid = work_q.get()
        try:
            process_job(jid)
        finally:
            work_q.task_done()

def csv_copy(src: str, dst: str):
    shutil.copyfile(src, dst)

def csv_with_extra_columns(src: str, dst: str, extra_headers: List[str], extra_vals: List[str]):
    """Add placeholder enrichment columns."""
    with open(src, newline="", encoding="utf-8") as fin:
        rows = list(csv.reader(fin))
    if not rows:
        rows = [[]]
    header = rows[0]
    body = rows[1:]
    header = header + extra_headers
    out = [header] + [r + extra_vals for r in body]
    with open(dst, "w", newline="", encoding="utf-8") as fout:
        csv.writer(fout).writerows(out)

def _get_job_by_id(job_id: int) -> Optional[Dict[str, Any]]:
    """Fetch one job from DB or fallback JSON."""
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

def process_job(job_id: int):
    """Simulate enrichment pipeline."""
    job = _get_job_by_id(job_id)
    if not job:
        log_event("ERROR", "Job not found", job_id=job_id)
        return
    try:
        _update_job(job_id, status="processing", updated_at=now_iso(), progress=5)
        filename = job["filename"]
        base = os.path.splitext(filename)[0]
        upload_path = os.path.join(UPLOADS_DIR, filename)
        p1 = os.path.join(OUTPUTS_DIR, f"{base}_{job_id}_stage1.csv")
        p2 = os.path.join(OUTPUTS_DIR, f"{base}_{job_id}_stage2.csv")
        p3 = os.path.join(OUTPUTS_DIR, f"{base}_{job_id}_stage3.csv")

        csv_copy(upload_path, p1)
        _update_job(job_id, progress=35)
        csv_with_extra_columns(p1, p2, ["post_1", "post_2", "post_3"], ["(p1)", "(p2)", "(p3)"])
        _update_job(job_id, progress=65)
        csv_with_extra_columns(
            p2, p3,
            ["email_subject", "email_body"],
            [
                "Quick idea to boost retention",
                "Hi {first_name}, saw your work at {company_name}. Open to a quick audit?",
            ],
        )
        _update_job(job_id, status="succeeded", progress=100, output_url=f"/downloads/{os.path.basename(p3)}")
        log_event("INFO", "Job succeeded", job_id=job_id)
    except Exception as e:
        _update_job(job_id, status="failed", error=str(e))
        log_event("ERROR", "Job failed", job_id=job_id, error=str(e))

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
# Jobs endpoints
# -------------------------------------------------------------------
def _filter_for_user(rows: List[Dict[str, Any]], user: Optional[User]) -> List[Dict[str, Any]]:
    if user is None:
        return rows
    return [r for r in rows if str(r.get("user_id")) == str(user.id)]

@app.get("/jobs")
def list_jobs_endpoint(current: Optional[User] = Depends(get_current_user_optional)):
    """List all jobs (filtered by user unless PUBLIC_READ)."""
    if not PUBLIC_READ and current is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        rows = list_jobs()
    except Exception as e:
        log_event("WARN", "DB read failed in /jobs", error=str(e))
        rows = _read_json(JOBS_FILE, [])
    rows = _filter_for_user(rows, current)
    rows.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return rows

@app.get("/status")
def status(current: Optional[User] = Depends(get_current_user_optional)):
    """Summarize job statuses."""
    if not PUBLIC_READ and current is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        rows = list_jobs()
    except Exception as e:
        log_event("WARN", "DB read failed in /status", error=str(e))
        rows = _read_json(JOBS_FILE, [])
    rows = _filter_for_user(rows, current)
    summary = {"queued": [], "processing": [], "succeeded": [], "failed": []}
    for j in rows:
        st = j.get("status", "queued")
        summary.setdefault(st, []).append(j)
    return summary

# -------------------------------------------------------------------
# Upload & Create Job
# -------------------------------------------------------------------
@app.post("/jobs")
def create_job_endpoint(
    file: UploadFile = File(...),
    notes: Optional[str] = Form(None),
    current: User = Depends(get_current_user)
):
    """Upload CSV, create DB job row, and queue for processing."""
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv file.")

    safe_name = f"{uuid.uuid4().hex}_{os.path.basename(file.filename)}"
    upload_path = os.path.join(UPLOADS_DIR, safe_name)
    with open(upload_path, "wb") as out:
        out.write(file.file.read())
    file.file.close()

    try:
        df = read_input_file(upload_path)
        validate_columns(df)
    except Exception as e:
        os.remove(upload_path)
        raise HTTPException(status_code=400, detail=f"Invalid CSV: {e}")

    payload = {"notes": notes or ""}
    try:
        job = create_job(user_id=str(current.id), filename=safe_name, payload=payload)
        job_id = job.get("id", None)
    except Exception as e:
        log_event("WARN", "DB insert failed; using local JSON", error=str(e))
        jobs = _read_json(JOBS_FILE, [])
        job_id = (max([j.get("id", 0) for j in jobs], default=0) or 0) + 1
        jobs.append({
            "id": job_id,
            "user_id": str(current.id),
            "filename": safe_name,
            "status": "queued",
            "progress": 0,
            "payload": payload,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
        _write_json(JOBS_FILE, jobs)

    _ensure_worker()
    work_q.put(job_id)
    return {"ok": True, "job_id": job_id, "filename": safe_name, "status": "queued"}

# -------------------------------------------------------------------
# Retry Queued Jobs
# -------------------------------------------------------------------
@app.post("/retry-queued")
def retry_queued(current: User = Depends(get_current_user)):
    """
    Requeue all jobs still marked as 'queued' in the database (or fallback JSON).
    Useful after a restart or deploy to resume unprocessed jobs.
    """
    try:
        jobs = list_jobs()
    except Exception as e:
        log_event("WARN", "DB read failed in /retry-queued; using local fallback", error=str(e))
        jobs = _read_json(JOBS_FILE, [])

    queued_jobs = [j for j in jobs if j.get("status") == "queued"]
    if not queued_jobs:
        return {"ok": True, "message": "No queued jobs found."}

    _ensure_worker()
    for j in queued_jobs:
        jid = j.get("id")
        if jid:
            work_q.put(jid)
            log_event("INFO", "Requeued job", job_id=jid)

    return {
        "ok": True,
        "message": f"Requeued {len(queued_jobs)} job(s).",
        "count": len(queued_jobs),
    }

# -------------------------------------------------------------------
# Local entry point
# -------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=10000, reload=True)