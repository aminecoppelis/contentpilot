/* UNIFIED_CALENDAR_WORKER_LINK_AND_FINALIZE_V1 */
WITH input AS (
  SELECT
    CASE WHEN $1::text ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN $1::uuid ELSE NULL END AS request_id,
    CASE WHEN $2::text ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN $2::uuid ELSE NULL END AS calendar_id,
    CASE WHEN $3::text ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN $3::uuid ELSE NULL END AS idea_id,
    CASE WHEN $4::text ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN $4::uuid ELSE NULL END AS version_id
), valid AS MATERIALIZED (
  SELECT i.*, pi.workspace_id
  FROM input i
  JOIN public.post_ideas pi
    ON pi.id = i.idea_id
   AND pi.request_id = i.request_id
   AND pi.deleted_at IS NULL
  JOIN public.post_versions pv
    ON pv.id = i.version_id
   AND pv.idea_id = pi.id
   AND pv.workspace_id = pi.workspace_id
   AND NULLIF(btrim(COALESCE(pv.post_text,'')),'') IS NOT NULL
   AND lower(COALESCE(pv.post_text,'')) NOT LIKE '%objectif stratégique :%'
   AND lower(COALESCE(pv.post_text,'')) NOT LIKE '%action à transformer en contenu :%'
   AND lower(COALESCE(pv.post_text,'')) NOT LIKE '%livrable attendu :%'
   AND lower(COALESCE(pv.post_text,'')) NOT LIKE '%contrainte de planning ia :%'
   AND lower(COALESCE(pv.post_text,'')) NOT LIKE 'post depuis stratégie :%'
  JOIN public.app_growth_strategy_action_calendar c
    ON c.id = i.calendar_id
   AND c.request_id = i.request_id
   AND lower(COALESCE(c.status,'')) NOT IN ('obsolete','skipped','cancelled','canceled','archived')
  WHERE i.request_id IS NOT NULL
    AND i.calendar_id IS NOT NULL
    AND i.idea_id IS NOT NULL
    AND i.version_id IS NOT NULL
), linked AS (
  UPDATE public.post_ideas pi
  SET current_version_id = v.version_id,
      status = 'ready_for_review',
      updated_at = now()
  FROM valid v
  WHERE pi.id = v.idea_id
  RETURNING pi.id
), request_done AS (
  UPDATE public.post_requests pr
  SET status = 'ready_for_review',
      generated_at = COALESCE(pr.generated_at,now()),
      last_error = NULL,
      post_count = GREATEST(COALESCE(pr.post_count,0),1),
      form_data = COALESCE(pr.form_data,'{}'::jsonb) || jsonb_build_object(
        'calendar_generation_debug',jsonb_build_object(
          'worker_version','UNIFIED_V19',
          'stage','openrouter_post_saved',
          'node','Worker - Link and finalize',
          'updated_at',now()::text
        )
      )
  FROM valid v
  WHERE pr.id = v.request_id
    AND EXISTS (SELECT 1 FROM linked)
  RETURNING pr.id
), calendar_done AS (
  UPDATE public.app_growth_strategy_action_calendar c
  SET status = 'generated',
      error_message = NULL,
      updated_at = now(),
      payload = (COALESCE(c.payload,'{}'::jsonb)
        - 'clean_worker_lock_until'
        - 'clean_worker_last_error'
        - 'clean_worker_last_error_node')
        || jsonb_build_object(
          'generation_stage','openrouter_post_saved',
          'generation_provider','openrouter',
          'worker_version','UNIFIED_V19',
          'generated_request_id',v.request_id::text,
          'generated_idea_id',v.idea_id::text,
          'generated_version_id',v.version_id::text,
          'generation_stage_updated_at',now()::text
        )
  FROM valid v
  WHERE c.id = v.calendar_id
    AND EXISTS (SELECT 1 FROM request_done)
  RETURNING c.id
)
SELECT
  EXISTS (SELECT 1 FROM valid)
    AND EXISTS (SELECT 1 FROM linked)
    AND EXISTS (SELECT 1 FROM request_done)
    AND EXISTS (SELECT 1 FROM calendar_done) AS finalized,
  COALESCE((SELECT request_id::text FROM valid LIMIT 1),'') AS request_id,
  COALESCE((SELECT calendar_id::text FROM valid LIMIT 1),'') AS calendar_id,
  COALESCE((SELECT idea_id::text FROM valid LIMIT 1),'') AS idea_id,
  COALESCE((SELECT version_id::text FROM valid LIMIT 1),'') AS version_id,
  CASE WHEN EXISTS (SELECT 1 FROM calendar_done) THEN 'generated' ELSE 'invalid_link_context' END AS status;
