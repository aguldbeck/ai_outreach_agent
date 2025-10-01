# server.py
# FastAPI server with:
# - Job persistence (jobs.json) with safe writes
# - CSV "enrichment" background worker (stub you can replace)
# - Full CRUD: create/list/get/patch/delete
# - Downloads endpoint
# - CORS (configurable), request/response middleware
# - Structured JSON logging (or plain), via logging.json or env
# - Startup recovery: moves queued/processing -> failed (restart)
# - Progress field (0..100) and metadata dict
# - Thread-safe updates

import csv
import json
import os
import shutil
import threading
import time
import uuid
import logging
import logging.config
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import (
    FastAPI, UploadFile, File, Form, BackgroundTasks,
    HTTPException, Request, Response
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

# ------------------------------
# Config via env
# ------------------------------
APP_ROOT = Path(os.getenv("APP_ROOT", ".")).resolve()
LOG_CONFIG_PATH = os.getenv("LOG_CONFIG", "")      # e.g., "logging.json"
LOG_FORMAT = os.getenv("LOG_FORMAT", "json")       # "json" or "plain"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
ALLOW_RESET = os.getenv("ALLOW_RESET", "0") == "1" # dev-only purge endpoint
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")      # comma-separated or "*"

UPLOADS_DIR = APP_ROOT / "uploads"
OUTPUTS_DIR = APP_ROOT / "outputs"
STATE_FILE  = APP_ROOT / "jobs.json"

for p in (UPLOADS_DIR, OUTPUTS_DIR):
    p.mkdir(parents=True, exist_ok=True)

# ------------------------------
# Logging setup
# ------------------------------
def _setup_logging():
    if LOG_CONFIG_PATH and Path(LOG_CONFIG_PATH).exists():
        with open(LOG_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        logging.config.dictConfig(cfg)
        return

    # Fallback: code-defined config (JSON or plain)
    class JsonFormatter(logging.Formatter):
        def format(self, record):
            obj = {
                "time": datetime.utcnow().isoformat() + "Z",
                "level": record.levelname,
                "message": record.getMessage(),
                "logger": record.name,
            }
            if record.exc_info:
                obj["exception"] = self.formatException(record.exc_info)
            return json.dumps(obj, ensure_ascii=False)

    handler = logging.StreamHandler()
    if LOG_FORMAT.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(LOG_LEVEL)

_setup_logging()
logger = logging.getLogger("server")

# ------------------------------
# Persistence
# ------------------------------
_jobs_lock = threading.Lock()

def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"

def _safe_write_json(path: Path, payload: Any):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    tmp.replace(path)

def _load_jobs() -> Dict[str, Dict[str, Any]]:
    if not STATE_FILE.exists():
        return {}
    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {}
            return data
    except Exception as e:
        logger.error("Failed to load jobs.json", exc_info=True)
        return {}

def _save_jobs(jobs: Dict[str, Dict[str, Any]]):
    _safe_write_json(STATE_FILE, jobs)

JOBS: Dict[str, Dict[str, Any]] = _load_jobs()
logger.info(f"Loaded {len(JOBS)} jobs from state")

# On startup: recover any in-flight jobs
with _jobs_lock:
    recovered = 0
    for j in JOBS.values():
        if j.get("status") in ("queued", "processing"):
            j["status"] = "failed"
            j["error"]  = "Recovered after server restart"
            j["updated_at"] = _now()
            recovered += 1
    if recovered:
        _save_jobs(JOBS)
        logger.warning(f"Recovered {recovered} job(s) to 'failed' due to restart")

# ------------------------------
# Helpers / Model
# ------------------------------
def _public(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": job["id"],
        "user_id": job.get("user_id"),
        "config": job.get("config"),
        "filename": job.get("filename"),
        "status": job.get("status"),
        "progress": job.get("progress", 0),
        "error": job.get("error"),
        "output_url": job.get("output_url"),
        "metadata": job.get("metadata", {}),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }

def _safe_filename(name: str) -> str:
    name = name.replace("/", "_").replace("\\", "_")
    if len(name) > 120:
        base, ext = os.path.splitext(name)
        name = base[:100] + "_trim" + ext
    return name

def _update_job(job_id: str, **patch):
    with _jobs_lock:
        job = JOBS.get(job_id)
        if not job:
            logger.warning(f"Update ignored; job {job_id} not found")
            return
        job.update(patch)
        job["updated_at"] = _now()
        _save_jobs(JOBS)
    logger.info(f"job.update id={job_id} patch={patch}")

def _new_job(user_id: str, config_key: str, upload_path: Path, original_name: str) -> Dict[str, Any]:
    jid = str(uuid.uuid4())
    job = {
        "id": jid,
        "user_id": user_id,
        "config": config_key,
        "filename": original_name,
        "upload_path": str(upload_path),
        "status": "queued",
        "progress": 0,
        "error": None,
        "output_url": None,
        "metadata": {},
        "created_at": _now(),
        "updated_at": _now(),
    }
    with _jobs_lock:
        JOBS[jid] = job
        _save_jobs(JOBS)
    logger.info(f"job.created id={jid} user={user_id} config={config_key} file={original_name}")
    return job

# ------------------------------
# Worker (replace with your real pipeline later)
# ------------------------------
def _enrich_csv(input_csv: Path, output_csv: Path, note: str):
    with input_csv.open("r", encoding="utf-8", newline="") as fin, \
         output_csv.open("w", encoding="utf-8", newline="") as fout:
        reader = csv.reader(fin)
        writer = csv.writer(fout)
        first = True
        for row in reader:
            if first:
                row = list(row) + ["enriched_note"]
                first = False
            else:
                row = list(row) + [note]
            writer.writerow(row)

def _process_job(job_id: str):
    with _jobs_lock:
        job = JOBS.get(job_id)
        if not job:
            logger.error(f"worker: missing job id={job_id}")
            return
        job["status"] = "processing"
        job["progress"] = 5
        job["updated_at"] = _now()
        _save_jobs(JOBS)
    logger.info(f"worker.start id={job_id}")

    try:
        upload_path = Path(job["upload_path"])
        if not upload_path.exists():
            _update_job(job_id, status="failed", error=f"Uploaded file not found: {upload_path}")
            logger.error(f"worker.fail id={job_id} reason=missing_upload path={upload_path}")
            return

        # Simulate stages (so progress moves)
        _update_job(job_id, progress=25)
        time.sleep(0.05)

        out_name = f"{Path(job['filename']).stem}_{job_id[:8]}_enriched.csv"
        out_path = OUTPUTS_DIR / out_name

        note = f"config={job.get('config')} processed={_now()}"
        _enrich_csv(upload_path, out_path, note)

        _update_job(job_id, progress=75)
        time.sleep(0.05)

        _update_job(job_id, status="succeeded", progress=100, output_url=f"/downloads/{out_name}")
        logger.info(f"worker.ok id={job_id} output={out_path}")
    except Exception as e:
        _update_job(job_id, status="failed", error=str(e))
        logger.exception(f"worker.exception id={job_id}")

# ------------------------------
# FastAPI app & middleware
# ------------------------------
app = FastAPI(title="AI Outreach Agent API", version="3.0.0")

# CORS config
if CORS_ORIGINS == "*":
    allow_origins = ["*"]
else:
    allow_origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Request/response logging
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    try:
        response: Response = await call_next(request)
    except Exception as e:
        dur = (time.time() - start) * 1000
        logger.error(
            json.dumps({
                "method": request.method,
                "path": request.url.path,
                "status": 500,
                "duration_ms": round(dur, 2),
                "error": str(e),
            }),
            exc_info=True
        )
        raise
    dur = (time.time() - start) * 1000
    logger.info(json.dumps({
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "duration_ms": round(dur, 2),
    }))
    return response

# ------------------------------
# Routes
# ------------------------------
@app.get("/health")
def health():
    return {"ok": True, "time": _now()}

@app.get("/jobs")
def list_jobs():
    with _jobs_lock:
        jobs = list(JOBS.values())
    jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return {"jobs": [_public(j) for j in jobs]}

@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    with _jobs_lock:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return {"job": _public(job)}

@app.post("/jobs")
async def create_job(
    background_tasks: BackgroundTasks,
    user_id: str = Form(...),
    config: str = Form(...),
    file: UploadFile = File(...),
):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are supported")

    safe_name = _safe_filename(file.filename)
    upload_path = UPLOADS_DIR / f"{uuid.uuid4()}_{safe_name}"
    try:
        with upload_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        logger.exception("upload.save_failed")
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {e}")

    job = _new_job(user_id=user_id, config_key=config, upload_path=upload_path, original_name=safe_name)
    background_tasks.add_task(_process_job, job["id"])
    return {"job_id": job["id"], "status": job["status"], "config": job["config"]}

@app.patch("/jobs/{job_id}")
def patch_job(job_id: str, payload: Dict[str, Any]):
    # Allowed mutable fields: status, progress, output_url, metadata, error
    allowed = {"status", "progress", "output_url", "metadata", "error"}
    patch = {k: v for k, v in payload.items() if k in allowed}
    if not patch:
        raise HTTPException(status_code=400, detail="No allowed fields to update")
    _update_job(job_id, **patch)
    with _jobs_lock:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return {"job": _public(job)}

@app.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    with _jobs_lock:
        job = JOBS.pop(job_id, None)
        _save_jobs(JOBS)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")

    # Best-effort cleanup
    try:
        up = Path(job.get("upload_path", ""))
        if up.exists():
            up.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        if job.get("output_url"):
            name = job["output_url"].split("/")[-1]
            op = OUTPUTS_DIR / name
            if op.exists():
                op.unlink(missing_ok=True)
    except Exception:
        pass

    logger.info(f"job.deleted id={job_id}")
    return {"ok": True}

@app.get("/downloads/{filename}")
def download_file(filename: str):
    path = OUTPUTS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    logger.info(f"download.serve file={filename}")
    return FileResponse(path, filename=filename, media_type="text/csv")

# DEV ONLY: wipe jobs & files (guarded by ALLOW_RESET=1)
@app.post("/__reset__")
def reset_all():
    if not ALLOW_RESET:
        raise HTTPException(status_code=403, detail="reset disabled")
    with _jobs_lock:
        JOBS.clear()
        _save_jobs(JOBS)
    for d in (UPLOADS_DIR, OUTPUTS_DIR):
        for p in d.glob("*"):
            try: p.unlink(missing_ok=True)
            except Exception: pass
    return {"ok": True}