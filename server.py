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

# ✅ Diagnostic: confirm parser file visibility at runtime
print("DEBUG: backend/parser.py exists?", os.path.exists("backend/parser.py"))

# 🧩 FIXED IMPORT PATHS (after renaming app → backend)
from backend.parser import read_input_file, validate_columns
from auth import router as auth_router, get_current_user, User
from backend.db_helper import create_job, update_job, get_job, list_jobs
from backend.pipeline import run_pipeline  # ✅ key fix

# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------
APP_VERSION = "1.4.6 — Refactor imports to backend package"

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
# (Remaining functions unchanged)
# -------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=10000, reload=True)