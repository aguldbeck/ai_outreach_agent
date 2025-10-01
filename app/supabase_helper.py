import os
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "outreach-results")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def insert_job(job_id, user_id, config, filename, status):
    try:
        data = {
            "id": job_id,
            "user_id": user_id,
            "config": config,
            "filename": filename,
            "status": status
        }
        supabase.table("jobs").insert(data).execute()
    except Exception as e:
        print("[WARN] insert_job failed:", e)

def update_job(job_id, status=None, error=None, output_url=None):
    try:
        update_data = {}
        if status:
            update_data["status"] = str(status)
        if error:
            update_data["error"] = str(error)
        if output_url:
            update_data["output_url"] = str(output_url)
        supabase.table("jobs").update(update_data).eq("id", job_id).execute()
    except Exception as e:
        print("[WARN] update_job failed:", e)

def upload_result(job_id, file_path):
    try:
        with open(file_path, "rb") as f:
            file_data = f.read()
        dest_path = f"{job_id}.csv"
        supabase.storage.from_(SUPABASE_BUCKET).upload(dest_path, file_data, {"content-type": "text/csv"})
        url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(dest_path)
        return url
    except Exception as e:
        print("[WARN] upload_result failed:", e)
        return None
