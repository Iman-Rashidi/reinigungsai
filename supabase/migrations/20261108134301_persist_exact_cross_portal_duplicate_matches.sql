CREATE OR REPLACE FUNCTION private.ingest_search_batch(p_source text, p_query text, p_city text, p_category text, p_records jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO ''
AS $function$
declare
  v_headers jsonb;
  v_token text;
  v_run_id uuid;
  v_record jsonb;
  v_source text;
  v_external_id text;
  v_original_url text;
  v_canonical_url text;
  v_title text;
  v_description text;
  v_location text;
  v_category text;
  v_deadline date;
  v_status text;
  v_status_reason text;
  v_metadata jsonb;
  v_snapshot jsonb;
  v_snapshot_hash text;
  v_previous_snapshot jsonb;
  v_changed_fields jsonb;
  v_lead_id uuid;
  v_key text;
  v_processed integer := 0;
  v_inserted integer := 0;
  v_updated integer := 0;
  v_snapshots integer := 0;
  v_inserted_rows integer;
  v_match record;
  v_pair_a uuid;
  v_pair_b uuid;
  v_reasons jsonb;
begin
  v_headers := nullif(pg_catalog.current_setting('request.headers', true), '')::jsonb;
  v_token := coalesce(v_headers ->> 'x-reinigungsradar-token', '');

  if pg_catalog.length(v_token) < 40
     or not exists (
       select 1
       from private.api_tokens t
       where t.token_hash = pg_catalog.md5(v_token)
         and t.revoked_at is null
     ) then
    raise exception 'Not authorized' using errcode = '42501';
  end if;

  if p_source is null or pg_catalog.length(pg_catalog.btrim(p_source)) = 0 then
    raise exception 'A source is required' using errcode = '22023';
  end if;

  if p_records is null
     or pg_catalog.jsonb_typeof(p_records) <> 'array'
     or pg_catalog.jsonb_array_length(p_records) > 100 then
    raise exception 'Records must be a JSON array with at most 100 items' using errcode = '22023';
  end if;

  insert into public.lead_search_runs (
    source, query, city, category, parameters, run_status
  ) values (
    pg_catalog.left(pg_catalog.btrim(p_source), 160),
    nullif(pg_catalog.left(coalesce(p_query, ''), 1000), ''),
    nullif(pg_catalog.left(coalesce(p_city, ''), 160), ''),
    nullif(pg_catalog.left(coalesce(p_category, ''), 160), ''),
    '{}'::jsonb,
    'running'
  )
  returning id into v_run_id;

  for v_record in
    select value from pg_catalog.jsonb_array_elements(p_records)
  loop
    if pg_catalog.jsonb_typeof(v_record) <> 'object' then
      continue;
    end if;

    v_source := coalesce(
      nullif(pg_catalog.btrim(v_record ->> 'source'), ''),
      pg_catalog.btrim(p_source)
    );
    v_title := coalesce(
      nullif(pg_catalog.btrim(coalesce(v_record ->> 'title', v_record ->> 'Titel')), ''),
      nullif(pg_catalog.btrim(v_record ->> 'headline'), ''),
      nullif(pg_catalog.btrim(v_record ->> 'name'), '')
    );

    if v_title is null then
      continue;
    end if;

    v_external_id := nullif(pg_catalog.left(pg_catalog.btrim(coalesce(
      v_record ->> 'external_id',
      v_record ->> 'publication_number',
      v_record ->> 'notice_id'
    )), 240), '');

    v_original_url := nullif(pg_catalog.left(pg_catalog.btrim(coalesce(
      v_record ->> 'url',
      v_record ->> 'source_url',
      v_record ->> 'Quellenlink',
      v_record ->> 'link'
    )), 2048), '');

    v_canonical_url := nullif(pg_catalog.left(pg_catalog.btrim(coalesce(
      v_record ->> 'canonical_url',
      v_original_url
    )), 2048), '');

    v_description := nullif(pg_catalog.left(pg_catalog.btrim(coalesce(
      v_record ->> 'description',
      v_record ->> 'Suchauszug',
      v_record ->> 'snippet'
    )), 6000), '');

    v_location := nullif(pg_catalog.left(pg_catalog.btrim(coalesce(
      v_record ->> 'location',
      v_record ->> 'city',
      v_record ->> 'Ort',
      p_city
    )), 500), '');

    v_category := nullif(pg_catalog.left(pg_catalog.btrim(coalesce(
      v_record ->> 'category',
      v_record ->> 'Kategorie',
      p_category
    )), 200), '');

    v_deadline := nullif(v_record ->> 'deadline', '')::date;

    v_status := coalesce(nullif(pg_catalog.lower(pg_catalog.btrim(
      v_record ->> 'ad_status'
    )), ''), 'unknown');

    if v_status not in ('active', 'expired', 'stale', 'unknown') then
      v_status := 'unknown';
    end if;

    v_status_reason := nullif(pg_catalog.left(pg_catalog.btrim(
      v_record ->> 'status_reason'
    ), 300), '');

    v_metadata := case
      when pg_catalog.jsonb_typeof(v_record -> 'source_metadata') = 'object'
        then v_record -> 'source_metadata'
      else '{}'::jsonb
    end;

    v_snapshot := pg_catalog.jsonb_build_object(
      'title', v_title,
      'description', v_description,
      'location', v_location,
      'category', v_category,
      'deadline', v_deadline,
      'status', v_status,
      'url', v_original_url
    );
    v_snapshot_hash := pg_catalog.md5(v_snapshot::text);

    v_lead_id := null;
    if v_external_id is not null then
      select id into v_lead_id
      from public.leads
      where source = v_source and external_id = v_external_id
      limit 1
      for update;
    end if;

    if v_lead_id is null and v_canonical_url is not null then
      select id into v_lead_id
      from public.leads
      where source = v_source and canonical_url = v_canonical_url
      limit 1
      for update;
    end if;

    if v_lead_id is null then
      insert into public.leads (
        source, source_name, external_id, canonical_url, original_url,
        title, description, location, category, deadline, ad_status,
        status_reason, source_metadata
      ) values (
        v_source,
        nullif(pg_catalog.left(pg_catalog.btrim(coalesce(v_record ->> 'source_name', v_source)), 240), ''),
        v_external_id, v_canonical_url, v_original_url,
        v_title, v_description, v_location, v_category, v_deadline, v_status,
        v_status_reason, v_metadata
      )
      returning id into v_lead_id;
      v_inserted := v_inserted + 1;
    else
      select snapshot into v_previous_snapshot
      from public.lead_snapshots
      where lead_id = v_lead_id
      order by observed_at desc
      limit 1;

      v_changed_fields := '{}'::jsonb;
      if v_previous_snapshot is not null then
        for v_key in select pg_catalog.jsonb_object_keys(v_snapshot)
        loop
          if v_previous_snapshot -> v_key is distinct from v_snapshot -> v_key then
            v_changed_fields := v_changed_fields || pg_catalog.jsonb_build_object(
              v_key,
              pg_catalog.jsonb_build_object(
                'before', v_previous_snapshot -> v_key,
                'after', v_snapshot -> v_key
              )
            );
          end if;
        end loop;
      end if;

      update public.leads
      set
        source_name = coalesce(nullif(pg_catalog.left(pg_catalog.btrim(v_record ->> 'source_name'), 240), ''), source_name),
        external_id = coalesce(v_external_id, external_id),
        canonical_url = coalesce(v_canonical_url, canonical_url),
        original_url = coalesce(v_original_url, original_url),
        title = v_title,
        description = v_description,
        location = v_location,
        category = v_category,
        deadline = v_deadline,
        ad_status = v_status,
        status_reason = v_status_reason,
        source_metadata = v_metadata,
        last_seen_at = now(),
        last_changed_at = case when v_changed_fields <> '{}'::jsonb then now() else last_changed_at end,
        updated_at = now()
      where id = v_lead_id;
      v_updated := v_updated + 1;
    end if;

    if v_changed_fields is null then
      v_changed_fields := '{}'::jsonb;
    end if;

    insert into public.lead_snapshots (
      lead_id, search_run_id, snapshot_hash, snapshot, changed_fields
    ) values (
      v_lead_id, v_run_id, v_snapshot_hash, v_snapshot, v_changed_fields
    )
    on conflict (lead_id, snapshot_hash) do nothing;

    get diagnostics v_inserted_rows = row_count;
    v_snapshots := v_snapshots + v_inserted_rows;

    -- Save exact cross-source matches; fuzzy matches still require app-side review.
    for v_match in
      select id, source, canonical_url, external_id
      from public.leads
      where id <> v_lead_id
        and source <> v_source
        and (
          (v_canonical_url is not null and canonical_url = v_canonical_url)
          or
          (v_external_id is not null and external_id = v_external_id)
        )
    loop
      v_pair_a := least(v_lead_id, v_match.id);
      v_pair_b := greatest(v_lead_id, v_match.id);
      v_reasons := '[]'::jsonb;

      if v_canonical_url is not null
         and v_match.canonical_url = v_canonical_url then
        v_reasons := v_reasons || pg_catalog.jsonb_build_array('same_canonical_url');
      end if;

      if v_external_id is not null
         and v_match.external_id = v_external_id then
        v_reasons := v_reasons || pg_catalog.jsonb_build_array('same_external_id');
      end if;

      insert into public.lead_duplicate_matches (
        lead_a_id, lead_b_id, similarity, reasons, cross_portal
      ) values (
        v_pair_a, v_pair_b, 1.0, v_reasons, true
      )
      on conflict (lead_a_id, lead_b_id) do update
      set similarity = greatest(
            public.lead_duplicate_matches.similarity,
            excluded.similarity
          ),
          reasons = (
            select pg_catalog.jsonb_agg(distinct reason)
            from pg_catalog.jsonb_array_elements(
              public.lead_duplicate_matches.reasons || excluded.reasons
            ) as item(reason)
          ),
          cross_portal = true;
    end loop;

    v_processed := v_processed + 1;
    v_previous_snapshot := null;
    v_changed_fields := null;
  end loop;

  update public.lead_search_runs
  set run_status = 'completed',
      result_count = v_processed,
      completed_at = now()
  where id = v_run_id;

  return pg_catalog.jsonb_build_object(
    'search_run_id', v_run_id,
    'processed', v_processed,
    'inserted', v_inserted,
    'updated', v_updated,
    'new_snapshots', v_snapshots
  );
end;
$function$;
revoke all on function private.ingest_search_batch(text, text, text, text, jsonb)
  from public, authenticated;
grant execute on function private.ingest_search_batch(text, text, text, text, jsonb)
  to anon;
