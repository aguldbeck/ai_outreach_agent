def process_job(job_id: int):
    """
    Processes a queued job:
    1. Downloads the uploaded Excel from Supabase
    2. Runs the enrichment + outreach pipeline
    3. Uploads the processed Excel back to Supabase
    4. Updates the job status + logs
    """
    job = _get_job_by_id(job_id)
    if not job:
        log_event("ERROR", "Job not found", job_id=job_id)
        return

    if job.get("status") == "succeeded":
        log_event("INFO", "Skip already-succeeded job", job_id=job_id)
        return

    try:
        _update_job(job_id, status="processing", updated_at=now_iso(), progress=5)
        filename = job["filename"]
        file_url = job.get("file_url")

        if not file_url:
            raise Exception("Missing file_url for job")

        log_event("INFO", "Downloading input file", job_id=job_id, file_url=file_url)
        response = requests.get(file_url, timeout=30)
        response.raise_for_status()

        local_path = os.path.join(UPLOADS_DIR, filename)
        with open(local_path, "wb") as f:
            f.write(response.content)

        # -------------------------------------------------------------------
        # 🧠 Run full enrichment pipeline
        # -------------------------------------------------------------------
        from pipeline import run_pipeline

        _update_job(job_id, progress=25)
        log_event("INFO", "Starting pipeline", job_id=job_id, input=filename)

        output_path = run_pipeline(local_path, str(job_id), OUTPUTS_DIR)

        _update_job(job_id, progress=90)
        log_event("INFO", "Pipeline complete", job_id=job_id, output=output_path)

        # -------------------------------------------------------------------
        # ☁️ Upload processed file to Supabase
        # -------------------------------------------------------------------
        processed_name = os.path.basename(output_path)
        storage_key = f"processed/{processed_name}"

        with open(output_path, "rb") as f:
            supabase.storage.from_(SUPABASE_BUCKET).upload(storage_key, f, {"upsert": True})

        output_url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(storage_key)

        # -------------------------------------------------------------------
        # ✅ Finalize job
        # -------------------------------------------------------------------
        _update_job(job_id, status="succeeded", progress=100, output_url=output_url)
        log_event("INFO", "Job succeeded", job_id=job_id, output_url=output_url)

    except Exception as e:
        _update_job(job_id, status="failed", error=str(e))
        log_event("ERROR", "Job failed", job_id=job_id, error=str(e))