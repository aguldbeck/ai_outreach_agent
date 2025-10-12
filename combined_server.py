import asyncio
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db_helper import get_next_job, mark_job_done, init_db  # adjust if your db helper path differs
from app.job_processor import process_job  # adjust import if needed

# --- CONFIG ---
POLL_INTERVAL = 10  # seconds between job polls

# --- LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")

# --- FASTAPI APP ---
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"message": "AI Outreach Agent active"}

# --- BACKGROUND JOB LOOP ---
async def worker_loop():
    await init_db()
    logger.info("Background worker started.")
    while True:
        try:
            job = await get_next_job()
            if job:
                logger.info(f"Processing job: {job['id']}")
                await process_job(job)
                await mark_job_done(job["id"])
            else:
                await asyncio.sleep(POLL_INTERVAL)
        except Exception as e:
            logger.error(f"Worker error: {e}")
            await asyncio.sleep(POLL_INTERVAL)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(worker_loop())