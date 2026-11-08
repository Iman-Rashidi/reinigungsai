create index if not exists lead_duplicate_matches_lead_b_idx
  on public.lead_duplicate_matches (lead_b_id);

create index if not exists lead_snapshots_search_run_idx
  on public.lead_snapshots (search_run_id)
  where search_run_id is not null;
