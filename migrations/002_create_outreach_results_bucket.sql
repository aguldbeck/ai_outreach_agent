-- Supabase migration: ensure public storage bucket for results
do $$
begin
  if not exists (select 1 from storage.buckets where name = 'outreach-results') then
    perform storage.create_bucket('outreach-results', public => true);
  end if;
end $$;
