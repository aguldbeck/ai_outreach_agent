"""
worker.py
Continuous job processor for AI Outreach Agent.
Polls the Supabase 'jobs' table for queued jobs and processes them using server.process_job.
Safe for multi-tenant Lovable + Supabase setup.
"""

import os
import time
import traceback
from dotenv import load_dotenv

from app.db_helper import list_jobs, update_job, get_job
from server import process_job, log_event, now_iso

load_dotenv()

# Polling interval (in seconds)
POLL_INTERVAL = int(os.getenv("WORKER_POLL_INTERVAL", "30"))

def main():
    print("🚀 Worker started: polling Supabase for queued jobs...")
    while True:
        try:
            jobs = list_jobs()
            queued = [j for j in jobs if j.get("status") == "queued"]
            if queued:
                print(f"🔄 Found {len(queued)} queued job(s) to process.")
            for job in queued:
                job_id = job.get("id")
                print(f"⚙️ Processing job {job_id} ({job.get('filename')})")
                try:
                    update_job(job_id, status="processing", updated_at=now_iso())
                    process_job(job_id)
                    print(f"✅ Job {job_id} completed.")
                except Exception as job_err:
                    err = traceback.format_exc()
                    print(f"❌ Job {job_id} failed: {err}")
                    update_job(job_id, status="failed", error=str(job_err), updated_at=now_iso())
                    log_event("ERROR", "Worker job failure", job_id=job_id, error=str(job_err))
            time.sleep(POLL_INTERVAL)
        except Exception as loop_err:
            err = traceback.format_exc()
            print(f"🔥 Worker loop error: {err}")
            log_event("ERROR", "Worker main loop failure", error=str(loop_err))
            time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()