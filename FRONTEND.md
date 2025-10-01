# Lovable Frontend Integration with Supabase

## Install Supabase Client
```bash
npm install @supabase/supabase-js
```

## Setup Client (lib/supabaseClient.ts)
```ts
import { createClient } from '@supabase/supabase-js'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!

export const supabase = createClient(supabaseUrl, supabaseAnonKey)
```

## Hooks (lib/jobs.ts)
```ts
import { supabase } from './supabaseClient'

export async function fetchJobs(userId: string) {
  const { data, error } = await supabase
    .from('jobs')
    .select('*')
    .eq('user_id', userId)
    .order('created_at', { ascending: false })
  if (error) throw error
  return data
}

export async function fetchJob(jobId: string) {
  const { data, error } = await supabase
    .from('jobs')
    .select('*')
    .eq('job_id', jobId)
    .single()
  if (error) throw error
  return data
}
```

## Example Component
```tsx
import { useEffect, useState } from 'react'
import { fetchJob } from '@/lib/jobs'

export default function JobStatus({ jobId }: { jobId: string }) {
  const [job, setJob] = useState<any>(null)

  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const result = await fetchJob(jobId)
        setJob(result)
      } catch (e) {
        console.error(e)
      }
    }, 5000)
    return () => clearInterval(interval)
  }, [jobId])

  if (!job) return <p>Loading...</p>
  if (job.status === 'succeeded') {
    return <a href={job.output_url} target="_blank" rel="noreferrer">Download Results</a>
  }
  if (job.status === 'failed') {
    return <p style={{color:"red"}}>Failed: {job.error}</p>
  }
  return <p>Status: {job.status}</p>
}
```

## Flow
1. Lovable UI uploads CSV -> Render API `/jobs` (returns job_id).
2. Render inserts job row in Supabase with `status=queued`.
3. Job runs -> updates Supabase with `running` -> `succeeded` + `output_url`.
4. Lovable UI polls Supabase for that `job_id` and shows status + download link.
