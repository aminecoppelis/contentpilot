/* UNIFIED_CALENDAR_WORKER_MARK_FAILURE_V1 */
WITH input AS (
  SELECT
    CASE WHEN $1::text ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN $1::uuid ELSE NULL END AS calendar_id,
    CASE WHEN $2::text ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN $2::uuid ELSE NULL END AS request_id,
    LEFT(COALESCE(NULLIF($3::text,''),'Pipeline calendrier'),180) AS error_node,
    LEFT(COALESCE(NULLIF($4::text,''),'Erreur de génération.'),2800) AS error_message,
    LEFT(COALESCE(NULLIF($5::text,''),'calendar_clean_worker_failed'),120) AS error_stage
), ctx AS MATERIALIZED (
  SELECT
    c.id AS calendar_id,
    COALESCE(i.request_id,c.request_id) AS request_id,
    CASE
      WHEN COALESCE(c.payload->>'clean_worker_attempt_count','') ~ '^[0-9]+$'
      THEN (c.payload->>'clean_worker_attempt_count')::int
      ELSE 1
    END AS attempt_count,
    i.error_node,
    i.error_message,
    i.error_stage
  FROM input i
  JOIN public.app_growth_strategy_action_calendar c
    ON (
      (i.calendar_id IS NOT NULL AND c.id = i.calendar_id)
      OR (i.calendar_id IS NULL AND i.request_id IS NOT NULL AND c.request_id = i.request_id)
    )
   AND lower(COALESCE(c.status,'')) NOT IN ('obsolete','skipped','cancelled','canceled','archived')
  ORDER BY c.updated_at DESC NULLS LAST, c.id
  LIMIT 1
  FOR UPDATE OF c
), calendar_failed AS (
  UPDATE public.app_growth_strategy_action_calendar c
  SET status = CASE WHEN x.attempt_count < 3 THEN 'retry' ELSE 'failed' END,
      error_message = x.error_message,
      updated_at = now(),
      payload = (COALESCE(c.payload,'{}'::jsonb) - 'clean_worker_lock_until')
        || jsonb_build_object(
          'generation_stage',x.error_stage,
          'clean_worker_last_error_node',x.error_node,
          'clean_worker_last_error',x.error_message,
          'clean_worker_last_error_at',now()::text,
          'clean_worker_next_retry_at',CASE WHEN x.attempt_count < 3 THEN (now()+interval '2 minutes')::text ELSE '' END,
          'worker_version','UNIFIED_V19'
        )
  FROM ctx x
  WHERE c.id = x.calendar_id
  RETURNING c.id
), request_failed AS (
  UPDATE public.post_requests pr
  SET status = 'failed',
      last_error = x.error_message,
      form_data = COALESCE(pr.form_data,'{}'::jsonb) || jsonb_build_object(
        'calendar_generation_error',jsonb_build_object(
          'stage',x.error_stage,
          'node',x.error_node,
          'message',x.error_message,
          'attempt',x.attempt_count,
          'updated_at',now()::text,
          'worker_version','UNIFIED_V19'
        )
      )
  FROM ctx x
  WHERE pr.id = x.request_id
    AND NOT EXISTS (
      SELECT 1
      FROM public.post_ideas pi
      JOIN public.post_versions pv ON pv.idea_id = pi.id
      WHERE pi.request_id = pr.id
        AND pi.deleted_at IS NULL
        AND NULLIF(btrim(COALESCE(pv.post_text,'')),'') IS NOT NULL
    )
  RETURNING pr.id
)
SELECT
  COALESCE((SELECT calendar_id::text FROM ctx LIMIT 1),'') AS calendar_id,
  COALESCE((SELECT request_id::text FROM ctx LIMIT 1),'') AS request_id,
  COALESCE((SELECT attempt_count FROM ctx LIMIT 1),0)::int AS attempt_count,
  CASE WHEN COALESCE((SELECT attempt_count FROM ctx LIMIT 1),3) < 3 THEN 'retry' ELSE 'failed' END AS next_status;
