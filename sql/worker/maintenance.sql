/* UNIFIED_CALENDAR_WORKER_MAINTENANCE_V22 */
WITH detached AS MATERIALIZED (
  SELECT c.id, c.request_id
  FROM public.app_growth_strategy_action_calendar c
  LEFT JOIN public.post_requests pr
    ON pr.id = c.request_id
   AND pr.deleted_at IS NULL
  WHERE c.request_id IS NOT NULL
    AND pr.id IS NULL
    AND lower(COALESCE(c.status,'')) NOT IN ('published','cancelled','canceled','obsolete','skipped','archived')
  ORDER BY c.updated_at ASC NULLS FIRST, c.id
  LIMIT 100
  FOR UPDATE OF c SKIP LOCKED
), detached_updated AS (
  UPDATE public.app_growth_strategy_action_calendar c
  SET request_id = NULL,
      status = 'pending_reschedule',
      triggered_at = NULL,
      error_message = NULL,
      updated_at = now(),
      payload = (COALESCE(c.payload,'{}'::jsonb)
        - 'clean_worker_lock_until'
        - 'clean_worker_last_error'
        - 'clean_worker_last_error_node')
        || jsonb_build_object(
          'generation_stage','deleted_subject_waiting_reschedule',
          'requires_reschedule',true,
          'detached_request_id',d.request_id::text,
          'worker_version','UNIFIED_V20',
          'updated_at',now()::text
        )
  FROM detached d
  WHERE c.id = d.id
  RETURNING c.id
), published_calendar_candidates AS MATERIALIZED (
  SELECT c.id, c.workspace_id, c.action_ids
  FROM public.app_growth_strategy_action_calendar c
  WHERE c.request_id IS NOT NULL
    AND lower(COALESCE(c.status,'')) NOT IN ('published','cancelled','canceled','obsolete','skipped','archived')
    AND EXISTS (
      SELECT 1
      FROM public.post_requests pr
      JOIN public.post_ideas pi
        ON pi.request_id = pr.id
       AND pi.workspace_id = pr.workspace_id
       AND pi.deleted_at IS NULL
      JOIN public.post_publications pp
        ON pp.idea_id = pi.id
       AND pp.workspace_id = pi.workspace_id
      WHERE pr.id = c.request_id
        AND pr.deleted_at IS NULL
        AND lower(COALESCE(pp.status,'')) IN ('published','sent','success','posted')
        AND (
          lower(COALESCE(pp.publish_mode,'now')) <> 'scheduled'
          OR pp.scheduled_at IS NULL
          OR pp.scheduled_at <= now()
        )
    )
  ORDER BY c.updated_at ASC NULLS FIRST, c.id
  LIMIT 200
  FOR UPDATE OF c SKIP LOCKED
), published_actions_done AS (
  UPDATE public.app_growth_strategy_actions a
  SET status = 'done',
      updated_at = now()
  FROM published_calendar_candidates pc
  WHERE a.workspace_id = pc.workspace_id
    AND COALESCE(a.status,'pending') <> 'done'
    AND EXISTS (
      SELECT 1
      FROM jsonb_array_elements(
        CASE
          WHEN jsonb_typeof(COALESCE(pc.action_ids,'[]'::jsonb)) = 'array'
            THEN COALESCE(pc.action_ids,'[]'::jsonb)
          ELSE '[]'::jsonb
        END
      ) AS elem(value)
      CROSS JOIN LATERAL (
        SELECT CASE
          WHEN jsonb_typeof(elem.value) = 'string'
            THEN trim(both '"' from elem.value::text)
          WHEN jsonb_typeof(elem.value) = 'object'
            THEN COALESCE(elem.value->>'id',elem.value->>'action_id')
          ELSE NULL
        END AS action_id
      ) AS parsed
      WHERE parsed.action_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
        AND a.id = parsed.action_id::uuid
    )
  RETURNING a.id
), published_calendars_done AS (
  UPDATE public.app_growth_strategy_action_calendar c
  SET status = 'published',
      error_message = NULL,
      updated_at = now(),
      payload = COALESCE(c.payload,'{}'::jsonb) || jsonb_build_object(
        'publication_status','published',
        'action_auto_completed',true,
        'action_auto_completed_at',now()::text,
        'worker_version','UNIFIED_V22'
      )
  FROM published_calendar_candidates pc
  WHERE c.id = pc.id
  RETURNING c.id
), placeholder_ideas AS MATERIALIZED (
  SELECT pi.id
  FROM public.post_ideas pi
  JOIN public.app_growth_strategy_action_calendar c ON c.request_id = pi.request_id
  WHERE pi.deleted_at IS NULL
    AND (
      lower(COALESCE(pi.raw_idea->>'calendar_placeholder','false')) IN ('true','t','1','yes','on')
      OR lower(COALESCE(pi.raw_idea->>'calendar_atomic_fallback','false')) IN ('true','t','1','yes','on')
      OR lower(COALESCE(pi.raw_idea->>'calendar_guaranteed','false')) IN ('true','t','1','yes','on')
      OR lower(COALESCE(pi.raw_idea->>'generation_source','')) IN (
        'calendar_guaranteed_baseline','calendar_fallback','calendar_atomic_v8','calendar_atomic_v9'
      )
      OR EXISTS (
        SELECT 1
        FROM public.post_versions badv
        WHERE badv.idea_id = pi.id
          AND (
            lower(COALESCE(badv.post_text,'')) LIKE '%objectif stratégique :%'
            OR lower(COALESCE(badv.post_text,'')) LIKE '%action à transformer en contenu :%'
            OR lower(COALESCE(badv.post_text,'')) LIKE '%livrable attendu :%'
            OR lower(COALESCE(badv.post_text,'')) LIKE '%contrainte de planning ia :%'
            OR lower(COALESCE(badv.post_text,'')) LIKE 'post depuis stratégie :%'
          )
      )
    )
  ORDER BY pi.created_at ASC
  LIMIT 200
  FOR UPDATE OF pi SKIP LOCKED
), placeholders_archived AS (
  UPDATE public.post_ideas pi
  SET deleted_at = now(),
      status = 'archived',
      current_version_id = NULL,
      updated_at = now()
  FROM placeholder_ideas p
  WHERE pi.id = p.id
  RETURNING pi.request_id
), repair_candidates AS MATERIALIZED (
  SELECT DISTINCT ON (c.id)
    c.id AS calendar_id,
    c.request_id,
    pi.id AS idea_id,
    pv.id AS version_id
  FROM public.app_growth_strategy_action_calendar c
  JOIN public.post_requests pr
    ON pr.id = c.request_id
   AND pr.deleted_at IS NULL
  JOIN public.post_ideas pi
    ON pi.request_id = pr.id
   AND pi.workspace_id = pr.workspace_id
   AND pi.deleted_at IS NULL
  JOIN public.post_versions pv
    ON pv.idea_id = pi.id
   AND pv.workspace_id = pi.workspace_id
   AND NULLIF(btrim(COALESCE(pv.post_text,'')),'') IS NOT NULL
   AND lower(COALESCE(pv.post_text,'')) NOT LIKE '%objectif stratégique :%'
   AND lower(COALESCE(pv.post_text,'')) NOT LIKE '%action à transformer en contenu :%'
   AND lower(COALESCE(pv.post_text,'')) NOT LIKE '%livrable attendu :%'
   AND lower(COALESCE(pv.post_text,'')) NOT LIKE '%contrainte de planning ia :%'
   AND lower(COALESCE(pv.post_text,'')) NOT LIKE 'post depuis stratégie :%'
  WHERE lower(COALESCE(c.status,'')) NOT IN ('published','cancelled','canceled','obsolete','skipped','archived')
    AND lower(COALESCE(pi.raw_idea->>'calendar_placeholder','false')) NOT IN ('true','t','1','yes','on')
    AND lower(COALESCE(pi.raw_idea->>'calendar_atomic_fallback','false')) NOT IN ('true','t','1','yes','on')
  ORDER BY c.id,
           (pi.current_version_id = pv.id) DESC,
           pv.is_current DESC,
           pv.version_number DESC,
           pv.id DESC
  LIMIT 200
), repaired_ideas AS (
  UPDATE public.post_ideas pi
  SET current_version_id = r.version_id,
      status = 'ready_for_review',
      updated_at = now()
  FROM repair_candidates r
  WHERE pi.id = r.idea_id
    AND (pi.current_version_id IS DISTINCT FROM r.version_id
         OR lower(COALESCE(pi.status,'')) <> 'ready_for_review')
  RETURNING pi.id
), repaired_requests AS (
  UPDATE public.post_requests pr
  SET status = 'ready_for_review',
      generated_at = COALESCE(pr.generated_at,now()),
      last_error = NULL,
      post_count = GREATEST(COALESCE(pr.post_count,0),1)
  FROM repair_candidates r
  WHERE pr.id = r.request_id
  RETURNING pr.id
), repaired_calendars AS (
  UPDATE public.app_growth_strategy_action_calendar c
  SET status = 'generated',
      error_message = NULL,
      updated_at = now(),
      payload = (COALESCE(c.payload,'{}'::jsonb)
        - 'clean_worker_lock_until'
        - 'clean_worker_last_error'
        - 'clean_worker_last_error_node')
        || jsonb_build_object(
          'generation_stage','existing_post_repaired',
          'worker_version','UNIFIED_V20',
          'generation_stage_updated_at',now()::text
        )
  FROM repair_candidates r
  WHERE c.id = r.calendar_id
  RETURNING c.id
), stale AS MATERIALIZED (
  SELECT c.id
  FROM public.app_growth_strategy_action_calendar c
  JOIN public.post_requests pr
    ON pr.id = c.request_id
   AND pr.deleted_at IS NULL
  WHERE c.request_id IS NOT NULL
    AND lower(COALESCE(c.status,'')) IN ('processing','generating','running','queued','generated','failed','error')
    AND NOT EXISTS (
      SELECT 1
      FROM public.post_ideas pi
      JOIN public.post_versions pv ON pv.idea_id = pi.id
      WHERE pi.request_id = c.request_id
        AND pi.deleted_at IS NULL
        AND NULLIF(btrim(COALESCE(pv.post_text,'')),'') IS NOT NULL
        AND lower(COALESCE(pv.post_text,'')) NOT LIKE '%objectif stratégique :%'
        AND lower(COALESCE(pv.post_text,'')) NOT LIKE '%action à transformer en contenu :%'
        AND lower(COALESCE(pv.post_text,'')) NOT LIKE '%livrable attendu :%'
        AND lower(COALESCE(pv.post_text,'')) NOT LIKE '%contrainte de planning ia :%'
        AND lower(COALESCE(pv.post_text,'')) NOT LIKE 'post depuis stratégie :%'
        AND lower(COALESCE(pi.raw_idea->>'calendar_placeholder','false')) NOT IN ('true','t','1','yes','on')
        AND lower(COALESCE(pi.raw_idea->>'calendar_atomic_fallback','false')) NOT IN ('true','t','1','yes','on')
    )
    AND NOT EXISTS (SELECT 1 FROM repaired_calendars rc WHERE rc.id = c.id)
    AND (
      COALESCE(c.payload->>'clean_worker_lock_until','') = ''
      OR (
        c.payload->>'clean_worker_lock_until' ~ '^\d{4}-\d{2}-\d{2}'
        AND (c.payload->>'clean_worker_lock_until')::timestamptz <= now()
      )
      OR c.payload->>'clean_worker_lock_until' !~ '^\d{4}-\d{2}-\d{2}'
    )
    AND CASE
      WHEN COALESCE(c.payload->>'clean_worker_attempt_count','') ~ '^[0-9]+$'
      THEN (c.payload->>'clean_worker_attempt_count')::int
      ELSE 0
    END < 3
  ORDER BY COALESCE(c.updated_at,c.triggered_at,c.planned_for) ASC
  LIMIT 100
  FOR UPDATE OF c SKIP LOCKED
), stale_retried AS (
  UPDATE public.app_growth_strategy_action_calendar c
  SET status = 'retry',
      updated_at = now(),
      payload = COALESCE(c.payload,'{}'::jsonb)
        - 'clean_worker_lock_until'
        || jsonb_build_object(
          'generation_stage','waiting_retry',
          'worker_version','UNIFIED_V20',
          'generation_stage_updated_at',now()::text
        )
  FROM stale s
  WHERE c.id = s.id
  RETURNING c.id
)
SELECT
  (SELECT COUNT(*) FROM detached_updated)::int AS detached_count,
  (SELECT COUNT(*) FROM published_actions_done)::int AS auto_completed_action_count,
  (SELECT COUNT(*) FROM published_calendars_done)::int AS published_calendar_count,
  (SELECT COUNT(*) FROM placeholders_archived)::int AS placeholders_archived_count,
  (SELECT COUNT(*) FROM repaired_calendars)::int AS repaired_count,
  (SELECT COUNT(*) FROM stale_retried)::int AS retry_count;