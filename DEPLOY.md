# Deploy to Render (Backend) + Supabase (DB/Storage)

## Environment variables (Render service)
- `OPENAI_API_KEY` = your OpenAI key
- `SUPABASE_URL` = your Supabase project URL
- `SUPABASE_SERVICE_ROLE_KEY` = Supabase Service Role key (server-only)
- `SUPABASE_BUCKET` = outreach-results

## Run command (Render)
```
uvicorn server:app --host 0.0.0.0 --port 10000
```

## Health check path
`/health`

## Supabase setup
Run the SQL in `migrations/` inside your Supabase SQL editor, in order:
1. `001_create_jobs.sql`  (jobs table + RLS)
2. `002_create_outreach_results_bucket.sql` (public storage bucket)

## Local run
```
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...
uvicorn server:app --reload --port 8000
```
