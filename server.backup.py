# server.py
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from dotenv import load_dotenv
from datetime import datetime
import os, json, shutil, uuid, traceback

# ───────── Setup ─────────
load_dotenv()
BASE_DIR   = os.getcwd()
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
JOBS_FILE  = os.path.join(BASE_DIR, "jobs.json")
LOG_FILE   = os.path.join(BASE_DIR, "logging.json")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
if not os.path.exists(JOBS_FILE): open(JOBS_FILE, "w").write("[]")
if not os.path.exists(LOG_FILE): open(LOG_FILE, "w").write("[]")

app = FastAPI(title="AI Outreach Agent - Queue")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# ───────── Helpers ─────────
def now_iso(): return datetime.utcnow().isoformat() + "Z"

def load_jobs():
    try:
        with open(JOBS_FILE, "r") as f: return json.load(f)
    except: return []
def save_jobs(jobs): open(JOBS_FILE, "w").write(json.dumps(jobs, indent=2))

def find_job(jobs, job_id):
    for j in jobs:
        if j["id"] == job_id: return j
    return None

def ensure_job_dirs(job_id):
    jdir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(jdir, exist_ok=True)
    return jdir

def append_log(entry: dict):
    try:
        logs = []
        with open(LOG_FILE, "r") as f:
            try: logs = json.load(f)
            except: logs = []
        entry["time"] = now_iso()
        logs.append(entry)
        with open(LOG_FILE, "w") as f: json.dump(logs, f, indent=2)
    except: pass

def status_from_outputs(job_id):
    """Infer progress by which stage files exist: 0/33/66/100"""
    jdir = os.path.join(OUTPUT_DIR, job_id)
    if not os.path.isdir(jdir): return 0
    s1 = os.path.exists(os.path.join(jdir, "stage1.csv"))
    s2 = os.path.exists(os.path.join(jdir, "stage2.csv"))
    s3 = os.path.exists(os.path.join(jdir, "stage3.csv"))
    if s3: return 100
    if s2: return 66
    if s1: return 33
    return 0

def build_download_url(job_id, stage_filename="stage3.csv"):
    return f"/downloads/{job_id}/{stage_filename}"

# ───────── Pipeline (stubs call out to app/pipeline.py) ─────────
# Keep logic in a separate module for clarity.
from app.pipeline import enrich_stage1, scrape_stage2, generate_stage3

async def run_job(job_id: str):
    """Process Stage1→Stage2→Stage3 sequentially as a background task."""
    jobs = load_jobs()
    job = find_job(jobs, job_id)
    if not job: return

    # mark processing
    job["status"] = "processing"
    job["progress"] = 0
    job["updated_at"] = now_iso()
    job["error"] = None
    save_jobs(jobs)
    append_log({"job": job_id, "event": "start_processing"})

    try:
        jdir = ensure_job_dirs(job_id)
        input_csv = job["upload_path"]

        # Stage 1
        stage1_out = os.path.join(jdir, "stage1.csv")
        enrich_stage1(input_csv, stage1_out, config=job.get("config", "weclick"))
        job["progress"] = 33
        job["updated_at"] = now_iso()
        save_jobs(jobs)
        append_log({"job": job_id, "event": "stage1_done", "output": stage1_out})

        # Stage 2
        stage2_out = os.path.join(jdir, "stage2.csv")
        scrape_stage2(stage1_out, stage2_out)
        job["progress"] = 66
        job["updated_at"] = now_iso()
        save_jobs(jobs)
        append_log({"job": job_id, "event": "stage2_done", "output": stage2_out})

        # Stage 3
        stage3_out = os.path.join(jdir, "stage3.csv")
        generate_stage3(stage2_out, stage3_out)
        job["progress"] = 100
        job["status"] = "succeeded"
        job["output_url"] = build_download_url(job_id, "stage3.csv")
        job["updated_at"] = now_iso()
        save_jobs(jobs)
        append_log({"job": job_id, "event": "stage3_done", "output": stage3_out})

    except Exception as e:
        tb = traceback.format_exc()
        job["status"] = "failed"
        job["error"] = str(e)
        job["updated_at"] = now_iso()
        save_jobs(jobs)
        append_log({"job": job_id, "event": "error", "error": str(e), "trace": tb})

# ───────── API ─────────

@app.post("/jobs")
async def create_job(
    background_tasks: BackgroundTasks,
    user_id: str = Form("anonymous"),
    config: str = Form("weclick"),
    file: UploadFile = File(...),
):
    jobs = load_jobs()
    job_id = str(uuid.uuid4())
    filename = file.filename

    # save upload
    upload_path = os.path.join(UPLOAD_DIR, f"{job_id}__{filename}")
    with open(upload_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    job = {
        "id": job_id,
        "user_id": user_id,
        "config": config,
        "filename": filename,
        "upload_path": upload_path,
        "status": "queued",
        "progress": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "error": None,
        "output_url": None,
    }
    jobs.append(job)
    save_jobs(jobs)
    append_log({"job": job_id, "event": "created"})

    # queue
    background_tasks.add_task(run_job, job_id)
    return job

@app.get("/jobs")
def list_jobs():
    jobs = load_jobs()
    # re-infer progress from outputs if processing
    for j in jobs:
        if j["status"] in ("queued", "processing"):
            j["progress"] = status_from_outputs(j["id"])
    # newest first
    jobs.sort(key=lambda x: x.get("created_at",""), reverse=True)
    return jobs

@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    jobs = load_jobs()
    job = find_job(jobs, job_id)
    if not job: return JSONResponse({"error":"Not found"}, status_code=404)
    if job["status"] in ("queued", "processing"):
        job["progress"] = status_from_outputs(job_id)
    return job

@app.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    jobs = load_jobs()
    job = find_job(jobs, job_id)
    if not job: return JSONResponse({"error":"Not found"}, status_code=404)

    # remove output dir
    out_dir = os.path.join(OUTPUT_DIR, job_id)
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir, ignore_errors=True)

    # remove upload
    try:
        if os.path.exists(job.get("upload_path","")):
            os.remove(job["upload_path"])
    except: pass

    # remove from jobs
    jobs = [j for j in jobs if j["id"] != job_id]
    save_jobs(jobs)
    append_log({"job": job_id, "event": "deleted"})
    return {"status": "deleted", "id": job_id}

@app.post("/restart/{job_id}")
def restart_job(job_id: str, background_tasks: BackgroundTasks):
    jobs = load_jobs()
    job = find_job(jobs, job_id)
    if not job: return JSONResponse({"error":"Not found"}, status_code=404)

    # reset status/progress/error, clear outputs
    out_dir = os.path.join(OUTPUT_DIR, job_id)
    if os.path.isdir(out_dir): shutil.rmtree(out_dir, ignore_errors=True)
    ensure_job_dirs(job_id)
    job["status"] = "queued"
    job["progress"] = 0
    job["error"] = None
    job["output_url"] = None
    job["updated_at"] = now_iso()
    save_jobs(jobs)
    append_log({"job": job_id, "event": "restarted"})

    background_tasks.add_task(run_job, job_id)
    return {"status":"queued", "id": job_id}

@app.get("/status")
def status():
    jobs = load_jobs()
    for j in jobs:
        if j["status"] in ("queued","processing"):
            j["progress"] = status_from_outputs(j["id"])
    # counts per status
    counts = {"queued":0,"processing":0,"succeeded":0,"failed":0}
    for j in jobs:
        counts[j["status"]] = counts.get(j["status"],0) + 1
    return {"counts": counts, "jobs": jobs}

# Download: per-job path
@app.get("/downloads/{job_id}/{filename}")
def download_job_file(job_id: str, filename: str):
    path = os.path.join(OUTPUT_DIR, job_id, filename)
    if os.path.exists(path): return FileResponse(path, filename=filename)
    return JSONResponse({"error":"File not found"}, status_code=404)

# Back-compat: /downloads/{stage}/{filename} -> try to find it under any job
@app.get("/downloads/{stage}/{filename}")
def download_compat(stage: str, filename: str):
    # scan jobs for a matching filename
    for j in os.listdir(OUTPUT_DIR):
        jp = os.path.join(OUTPUT_DIR, j)
        if os.path.isdir(jp):
            cand = os.path.join(jp, filename)
            if os.path.exists(cand): return FileResponse(cand, filename=filename)
    return JSONResponse({"error":"File not found"}, status_code=404)

@app.get("/health")
def health(): return {"ok": True, "time": now_iso()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)