create extension if not exists pgcrypto;

create table public.leads (
  id uuid primary key default gen_random_uuid(),
  source text not null check (length(trim(source)) > 0),
  source_name text,
  external_id text,
  canonical_url text,
  original_url text,
  title text not null check (length(trim(title)) > 0),
  description text,
  location text,
  category text,
  deadline date,
  ad_status text not null default 'unknown'
    check (ad_status in ('active', 'expired', 'stale', 'unknown')),
  status_reason text,
  source_metadata jsonb not null default '{}'::jsonb
    check (jsonb_typeof(source_metadata) = 'object'),
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  last_changed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index leads_source_external_id_uq
  on public.leads (source, external_id)
  where external_id is not null and external_id <> '';

create unique index leads_source_canonical_url_uq
  on public.leads (source, canonical_url)
  where canonical_url is not null and canonical_url <> '';

create index leads_city_category_idx on public.leads (location, category);
create index leads_status_deadline_idx on public.leads (ad_status, deadline);
create index leads_last_seen_idx on public.leads (last_seen_at desc);

create table public.lead_search_runs (
  id uuid primary key default gen_random_uuid(),
  source text not null check (length(trim(source)) > 0),
  query text,
  city text,
  category text,
  parameters jsonb not null default '{}'::jsonb
    check (jsonb_typeof(parameters) = 'object'),
  run_status text not null default 'running'
    check (run_status in ('running', 'completed', 'failed')),
  result_count integer not null default 0 check (result_count >= 0),
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  error_code text
);
create index lead_search_runs_started_idx
  on public.lead_search_runs (started_at desc);
create index lead_search_runs_filters_idx
  on public.lead_search_runs (city, category, source);

create table public.lead_snapshots (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid not null references public.leads(id) on delete cascade,
  search_run_id uuid references public.lead_search_runs(id) on delete set null,
  snapshot_hash text not null check (length(trim(snapshot_hash)) > 0),
  snapshot jsonb not null check (jsonb_typeof(snapshot) = 'object'),
  changed_fields jsonb not null default '{}'::jsonb
    check (jsonb_typeof(changed_fields) = 'object'),
  observed_at timestamptz not null default now(),
  constraint lead_snapshots_lead_hash_uq unique (lead_id, snapshot_hash)
);
create index lead_snapshots_lead_observed_idx
  on public.lead_snapshots (lead_id, observed_at desc);

create table public.lead_duplicate_matches (
  id uuid primary key default gen_random_uuid(),
  lead_a_id uuid not null references public.leads(id) on delete cascade,
  lead_b_id uuid not null references public.leads(id) on delete cascade,
  similarity numeric(5,4) not null check (similarity >= 0 and similarity <= 1),
  reasons jsonb not null default '[]'::jsonb
    check (jsonb_typeof(reasons) = 'array'),
  cross_portal boolean not null default false,
  review_status text not null default 'pending'
    check (review_status in ('pending', 'confirmed_duplicate', 'not_duplicate')),
  detected_at timestamptz not null default now(),
  reviewed_at timestamptz,
  constraint lead_duplicate_pair_order_ck check (lead_a_id < lead_b_id),
  constraint lead_duplicate_pair_uq unique (lead_a_id, lead_b_id)
);
create index lead_duplicate_review_idx
  on public.lead_duplicate_matches (review_status, detected_at desc);

alter table public.leads enable row level security;
alter table public.lead_search_runs enable row level security;
alter table public.lead_snapshots enable row level security;
alter table public.lead_duplicate_matches enable row level security;

revoke all on public.leads, public.lead_search_runs,
  public.lead_snapshots, public.lead_duplicate_matches
  from public, anon, authenticated;

grant all on public.leads, public.lead_search_runs,
  public.lead_snapshots, public.lead_duplicate_matches
  to service_role;

create policy "service role manages leads"
  on public.leads for all to service_role
  using (true) with check (true);
create policy "service role manages search runs"
  on public.lead_search_runs for all to service_role
  using (true) with check (true);
create policy "service role manages snapshots"
  on public.lead_snapshots for all to service_role
  using (true) with check (true);
create policy "service role manages duplicate matches"
  on public.lead_duplicate_matches for all to service_role
  using (true) with check (true);
