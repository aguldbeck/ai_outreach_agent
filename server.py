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

from fastapi import (
    FastAPI, UploadFile, File, Form, HTTPException, Depends
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr
from dotenv import load_dotenv

# Internal imports
from parser import read_input_file, validate_columns
from auth import router as auth_router, get_current_user, get_current_user_optional, User

# -----------------------------
# Setup and paths
# -----------------------------
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

# -----------------------------
# Models
# -----------------------------
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

# -----------------------------
# Utils
# -----------------------------
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

# -----------------------------
# App & CORS
# -----------------------------
app = FastAPI(title="AI Outreach Agent", version="0.5.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Routers
# -----------------------------
# Include the authentication router
app.include_router(auth_router)

# -----------------------------
# Health Check
# -----------------------------
@app.get("/health")
def health_check():
    """Lightweight health check for Render uptime monitoring."""
    try:
        _ = _read_json(JOBS_FILE, [])
        return {
            "status": "ok",
            "service": "ai_outreach_agent",
            "time": now_iso(),
            "public_read": PUBLIC_READ,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {e}")

# -----------------------------
# Root Endpoint
# -----------------------------
@app.get("/")
def root():
    return {
        "ok": True,
        "service": "ai_outreach_agent",
        "time": now_iso(),
        "public_read": PUBLIC_READ
    }

# -----------------------------
# Downloads
# -----------------------------
@app.get("/downloads/sample")
def download_sample():
    """Provide a downloadable CSV template."""
    if not os.path.exists(SAMPLE_FILE):
        with open(SAMPLE_FILE, "w", newline="") as f:
            f.write(
                "first_name,last_name,full_name,role_title,company_name,"
                "company_industry,company_size,company_website,company_location,"
                "linkedin_url,email,notes\n"
                "Jane,Doe,Jane Doe,Marketing Manager,Example Inc,Beauty,11-50,"
                "https://example.com,New York,https://linkedin.com/in/janedoe,"
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

# -----------------------------
# Background Worker
# -----------------------------
work_q: "queue.Queue[str]" = queue.Queue()
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
    """Add placeholder enrichment columns to simulate the AI pipeline."""
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

def process_job(job_id: str):
    """Simulate the enrichment pipeline in 3 stages."""
    jobs = _read_json(JOBS_FILE, [])
    job = next((j for j in jobs if j.get("id") == job_id), None)
    if not job:
        log_event("ERROR", "Job not found", job_id=job_id)
        return
    try:
        _update_job(job_id, status="processing", updated_at=now_iso(), progress=5)

        filename = job["filename"]
        base = os.path.splitext(filename)[0]
        s1 = f"{base}_{job_id}_stage1.csv"
        s2 = f"{base}_{job_id}_stage2.csv"
        s3 = f"{base}_{job_id}_stage3.csv"

        upload_path = os.path.join(UPLOADS_DIR, filename)
        p1 = os.path.join(OUTPUTS_DIR, s1)
        p2 = os.path.join(OUTPUTS_DIR, s2)
        p3 = os.path.join(OUTPUTS_DIR, s3)

        csv_copy(upload_path, p1)
        _update_job(job_id, progress=35, updated_at=now_iso())

        csv_with_extra_columns(p1, p2, ["post_1","post_2","post_3"], ["(p1)","(p2)","(p3)"])
        _update_job(job_id, progress=65, updated_at=now_iso())

        csv_with_extra_columns(p2, p3, ["email_subject","email_body"],
                               ["Quick idea to boost retention",
                                "Hi {first_name}, saw your work at {company_name}. Open to a quick audit?"])
        _update_job(job_id,
                    status="succeeded",
                    progress=100,
                    output_url=f"/downloads/{s3}",
                    updated_at=now_iso())
        log_event("INFO", "Job succeeded", job_id=job_id)
    except Exception as e:
        _update_job(job_id, status="failed", error=str(e), updated_at=now_iso())
        log_event("ERROR", "Job failed", job_id=job_id, error=str(e))

def _update_job(job_id: str, **patch):
    jobs = _read_json(JOBS_FILE, [])
    for j in jobs:
        if j.get("id") == job_id:
            j.update(patch)
            break
    _write_json(JOBS_FILE, jobs)

# -----------------------------
# Jobs Endpoints
# -----------------------------
def _filter_for_user(jobs: List[Dict[str, Any]], user: Optional[User]) -> List[Dict[str, Any]]:
    if user is None:
        return jobs
    return [j for j in jobs if j.get("user_id") == user.id]

@app.get("/jobs")
def list_jobs(current: Optional[User] = Depends(get_current_user_optional)):
    """List all jobs (filtered to current user unless PUBLIC_READ)."""
    if not PUBLIC_READ and current is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    jobs = _read_json(JOBS_FILE, [])
    jobs = _filter_for_user(jobs, current if not PUBLIC_READ else current)
    jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return jobs

@app.get("/status")
def status(current: Optional[User] = Depends(get_current_user_optional)):
    """Show summary of job statuses and progress."""
    if not PUBLIC_READ and current is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    jobs = _read_json(JOBS_FILE, [])
    jobs = _filter_for_user(jobs, current if not PUBLIC_READ else current)

    summary = {"queued": [], "processing": [], "succeeded": [], "failed": []}
    for j in jobs:
        st = j.get("status", "queued")
        if st not in summary:
            summary[st] = []
        job_id = j.get("id", "")
        filename = j.get("filename", "")
        stages = {"stage1": False, "stage2": False, "stage3": False}
        for nm in os.listdir(OUTPUTS_DIR):
            if job_id in nm:
                if nm.endswith("_stage1.csv"): stages["stage1"] = True
                if nm.endswith("_stage2.csv"): stages["stage2"] = True
                if nm.endswith("_stage3.csv"): stages["stage3"] = True
        summary[st].append({
            "id": job_id,
            "filename": filename,
            "status": st,
            "progress": j.get("progress", 0),
            "output_url": j.get("output_url"),
            "stages": stages,
            "updated_at": j.get("updated_at"),
        })
    return summary


# -----------------------------
# Local Entry Point
# -----------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=10000, reload=True)