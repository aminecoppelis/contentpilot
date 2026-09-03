/* UNIFIED_CALENDAR_WORKER_CLAIM_V20 */
WITH candidate AS MATERIALIZED (
  SELECT
    c.*,
    s.workspace_id AS strategy_workspace_id,
    s.created_by AS strategy_created_by,
    COALESCE(NULLIF(s.title,''),'Stratégie de croissance') AS strategy_title,
    COALESCE(NULLIF(s.objective_label,''),'croissance du compte') AS strategy_objective
  FROM public.app_growth_strategy_action_calendar c
  LEFT JOIN public.app_growth_strategies s ON s.id = c.strategy_id
  WHERE c.planned_for <= now()
    AND lower(COALESCE(c.status,'scheduled')) IN ('scheduled','retry','processing','generating')
    AND (
      lower(COALESCE(c.payload->>'kind','')) = 'adaptive_checkpoint'
      OR lower(COALESCE(c.payload->>'generation_required','')) IN ('true','t','1','yes','on')
      OR (
        NOT (COALESCE(c.payload,'{}'::jsonb) ? 'generation_required')
        AND COALESCE(
          NULLIF(lower(c.payload#>>'{ai_calendar,schedule_kind}'),''),
          NULLIF(lower(c.payload#>>'{action,schedule_kind}'),''),
          CASE
            WHEN lower(COALESCE(c.payload#>>'{action,category}','')) IN (
              'profil','profile','mesure','measurement','analysis','analyse','engagement'
            ) THEN 'manual'
            WHEN lower(COALESCE(c.payload->>'deliverable_kind',c.payload#>>'{action,deliverable_kind}','')) IN (
              'profile_update','analysis','planning'
            ) THEN 'manual'
            WHEN lower(COALESCE(c.payload->>'format_kind',c.payload#>>'{action,format_kind}','')) IN (
              'checklist','report'
            ) THEN 'manual'
            ELSE 'publishable_content'
          END
        ) = 'publishable_content'
      )
    )
    AND lower(COALESCE(c.status,'')) <> 'pending_reschedule'
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
    AND (
      COALESCE(c.payload->>'clean_worker_lock_until','') = ''
      OR (
        c.payload->>'clean_worker_lock_until' ~ '^\d{4}-\d{2}-\d{2}'
        AND (c.payload->>'clean_worker_lock_until')::timestamptz <= now()
      )
      OR c.payload->>'clean_worker_lock_until' !~ '^\d{4}-\d{2}-\d{2}'
    )
    AND (
      lower(COALESCE(c.status,'scheduled')) = 'scheduled'
      OR CASE
        WHEN COALESCE(c.payload->>'clean_worker_attempt_count','') ~ '^[0-9]+$'
        THEN (c.payload->>'clean_worker_attempt_count')::int
        ELSE 0
      END < 3
    )
  ORDER BY c.planned_for ASC, c.created_at ASC NULLS LAST, c.id
  LIMIT 1
  FOR UPDATE OF c SKIP LOCKED
), action_workspace AS MATERIALIZED (
  SELECT c.id AS calendar_id, a.workspace_id
  FROM candidate c
  JOIN LATERAL (
    SELECT ga.workspace_id
    FROM jsonb_array_elements_text(
      CASE
        WHEN jsonb_typeof(COALESCE(c.action_ids,'[]'::jsonb)) = 'array'
        THEN COALESCE(c.action_ids,'[]'::jsonb)
        ELSE '[]'::jsonb
      END
    ) x(value)
    JOIN public.app_growth_strategy_actions ga
      ON x.value ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
     AND ga.id = x.value::uuid
    WHERE ga.workspace_id IS NOT NULL
    ORDER BY ga.created_at ASC, ga.id
    LIMIT 1
  ) a ON true
), resolved AS MATERIALIZED (
  SELECT
    c.*,
    COALESCE(c.workspace_id,c.strategy_workspace_id,aw.workspace_id) AS resolved_workspace_id,
    ru.user_id AS resolved_user_id
  FROM candidate c
  LEFT JOIN action_workspace aw ON aw.calendar_id = c.id
  LEFT JOIN LATERAL (
    SELECT u.id AS user_id
    FROM (
      SELECT pr.user_id, 0 AS priority
      FROM public.post_requests pr
      WHERE pr.id = c.request_id AND pr.deleted_at IS NULL
      UNION ALL SELECT c.created_by, 1
      UNION ALL SELECT c.strategy_created_by, 2
      UNION ALL
      SELECT wm.user_id, 3
      FROM public.workspace_members wm
      WHERE wm.workspace_id = COALESCE(c.workspace_id,c.strategy_workspace_id,aw.workspace_id)
        AND wm.status = 'active'
      UNION ALL
      SELECT au.id, 4
      FROM public.app_users au
      WHERE au.is_active = true
        AND au.deleted_at IS NULL
        AND lower(COALESCE(au.role,'user')) = 'admin'
    ) q
    JOIN public.app_users u
      ON u.id = q.user_id
     AND u.is_active = true
     AND u.deleted_at IS NULL
    WHERE q.user_id IS NOT NULL
    ORDER BY q.priority, q.user_id
    LIMIT 1
  ) ru ON true
), existing_request AS MATERIALIZED (
  SELECT pr.*
  FROM resolved r
  JOIN public.post_requests pr
    ON pr.id = r.request_id
   AND pr.deleted_at IS NULL
  WHERE r.resolved_workspace_id IS NOT NULL
    AND r.resolved_user_id IS NOT NULL
    AND (pr.workspace_id = r.resolved_workspace_id OR pr.workspace_id IS NULL)
  LIMIT 1
), existing_marked AS (
  UPDATE public.post_requests pr
  SET status = 'generating',
      generated_at = NULL,
      last_error = NULL,
      user_id = COALESCE(pr.user_id,r.resolved_user_id),
      workspace_id = COALESCE(pr.workspace_id,r.resolved_workspace_id)
  FROM resolved r, existing_request e
  WHERE pr.id = e.id
  RETURNING pr.*
), created_request AS (
  INSERT INTO public.post_requests (
    title,subject,prompt,commercial_objective,target_sector,language,
    content_domains,target_audience,preferred_formats,constraints,source_urls,
    post_count,form_data,status,user_id,workspace_id
  )
  SELECT
    LEFT(COALESCE(NULLIF(r.payload->>'subject',''),'Post planifié stratégie'),180),
    LEFT(COALESCE(NULLIF(r.payload->>'subject',''),'Post planifié stratégie'),240),
    COALESCE(
      NULLIF(r.payload->>'prompt',''),
      NULLIF(r.payload->>'theme',''),
      'Créer un post prêt à publier à partir de cette action de stratégie.'
    ),
    COALESCE(
      NULLIF(r.payload->>'commercial_objective',''),
      NULLIF(r.payload->>'objective_label',''),
      r.strategy_objective,
      'croissance du compte'
    ),
    COALESCE(NULLIF(r.payload#>>'{action,category}',''),NULLIF(r.payload->>'target_sector',''),''),
    COALESCE(NULLIF(r.payload->>'language',''),'français'),
    CASE
      WHEN jsonb_typeof(r.payload->'content_domains') = 'array' THEN r.payload->'content_domains'
      ELSE jsonb_build_array('Stratégie','Croissance','Contenu social')
    END,
    CASE
      WHEN jsonb_typeof(r.payload->'target_audience') = 'array' THEN r.payload->'target_audience'
      ELSE jsonb_build_array('audience du compte')
    END,
    CASE
      WHEN jsonb_typeof(r.payload->'preferred_formats') = 'array' THEN r.payload->'preferred_formats'
      WHEN lower(COALESCE(r.payload->>'format_kind','')) = 'reel' THEN jsonb_build_array('Instagram · Reel')
      WHEN lower(COALESCE(r.payload->>'format_kind','')) IN ('carousel','carrousel') THEN jsonb_build_array('Instagram · Post')
      ELSE jsonb_build_array('Instagram · Post')
    END,
    COALESCE(
      NULLIF(r.payload->>'constraints',''),
      'Produire un vrai post directement publiable. Ne jamais recopier le prompt, le titre du sujet, les métriques brutes ou les instructions internes dans le texte final.'
    ),
    CASE WHEN jsonb_typeof(r.payload->'source_urls') = 'array' THEN r.payload->'source_urls' ELSE '[]'::jsonb END,
    1,
    jsonb_build_object(
      'source','growth_strategy_calendar_clean_worker',
      'calendar_id',r.id::text,
      'strategy_id',r.strategy_id::text,
      'planned_for',r.planned_for::text,
      'payload',r.payload,
      'worker_version','UNIFIED_V20'
    ),
    'generating',
    r.resolved_user_id,
    r.resolved_workspace_id
  FROM resolved r
  WHERE r.resolved_workspace_id IS NOT NULL
    AND r.resolved_user_id IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM existing_request)
  RETURNING *
), request_row AS MATERIALIZED (
  SELECT e.* FROM existing_marked e
  UNION ALL
  SELECT c.* FROM created_request c
), claimed AS (
  UPDATE public.app_growth_strategy_action_calendar c
  SET request_id = r.id,
      workspace_id = COALESCE(c.workspace_id,r.workspace_id),
      created_by = COALESCE(c.created_by,r.user_id),
      status = 'processing',
      triggered_at = COALESCE(c.triggered_at,now()),
      updated_at = now(),
      error_message = NULL,
      payload = (COALESCE(c.payload,'{}'::jsonb)
        - 'clean_worker_last_error'
        - 'clean_worker_last_error_node')
        || jsonb_build_object(
          'clean_worker_attempt_count',
            CASE
              WHEN lower(COALESCE(c.status,'scheduled')) = 'scheduled' THEN 1
              WHEN COALESCE(c.payload->>'clean_worker_attempt_count','') ~ '^[0-9]+$'
              THEN (c.payload->>'clean_worker_attempt_count')::int + 1
              ELSE 1
            END,
          'clean_worker_lock_until',(now()+interval '15 minutes')::text,
          'clean_worker_last_attempt_at',now()::text,
          'generation_stage','openrouter_running',
          'generation_provider','openrouter',
          'worker_version','UNIFIED_V20'
        )
  FROM request_row r
  WHERE c.id = (SELECT id FROM resolved LIMIT 1)
  RETURNING c.id, c.request_id, c.payload
), invalid_marked AS (
  UPDATE public.app_growth_strategy_action_calendar c
  SET status = 'failed',
      error_message = CASE
        WHEN r.resolved_workspace_id IS NULL THEN 'workspace_id introuvable pour la tâche planifiée.'
        WHEN r.resolved_user_id IS NULL THEN 'Utilisateur actif introuvable pour la tâche planifiée.'
        ELSE 'La demande de post n’a pas pu être créée.'
      END,
      updated_at = now(),
      payload = COALESCE(c.payload,'{}'::jsonb) || jsonb_build_object(
        'generation_stage','claim_context_invalid',
        'worker_version','UNIFIED_V20',
        'generation_stage_updated_at',now()::text
      )
  FROM resolved r
  WHERE c.id = r.id
    AND NOT EXISTS (SELECT 1 FROM request_row)
  RETURNING c.id, c.error_message
)
SELECT
  CASE WHEN cr.id IS NOT NULL THEN true ELSE false END AS pipeline_ready,
  COALESCE(cr.id::text,'') AS request_id,
  COALESCE(cr.id::text,'') AS db_request_id,
  COALESCE(cr.workspace_id::text,r.resolved_workspace_id::text,'') AS workspace_id,
  COALESCE(cr.user_id::text,r.resolved_user_id::text,'') AS user_id,
  COALESCE(cr.user_id::text,r.resolved_user_id::text,'') AS created_by,
  COALESCE(r.id::text,'') AS calendar_id,
  COALESCE(r.strategy_id::text,'') AS strategy_id,
  COALESCE(cr.subject,NULLIF(r.payload->>'subject',''),'Post planifié stratégie') AS subject,
  COALESCE(cr.prompt,NULLIF(r.payload->>'prompt',''),NULLIF(r.payload->>'theme',''),'Créer un post prêt à publier.') AS prompt,
  COALESCE(cr.prompt,NULLIF(r.payload->>'prompt',''),NULLIF(r.payload->>'theme',''),'Créer un post prêt à publier.') AS theme,
  COALESCE(cr.commercial_objective,NULLIF(r.payload->>'commercial_objective',''),r.strategy_objective,'croissance du compte') AS commercial_objective,
  COALESCE(cr.target_sector,NULLIF(r.payload->>'target_sector',''),'') AS target_sector,
  COALESCE(cr.language,NULLIF(r.payload->>'language',''),'français') AS language,
  COALESCE(cr.content_domains,'[]'::jsonb) AS content_domains,
  COALESCE(cr.target_audience,'[]'::jsonb) AS target_audience,
  COALESCE(cr.preferred_formats,'[]'::jsonb) AS preferred_formats,
  COALESCE(cr.constraints,'') AS constraints,
  COALESCE(cr.source_urls,'[]'::jsonb) AS source_urls,
  1 AS post_count,
  COALESCE(r.payload,'{}'::jsonb) AS calendar_payload,
  r.strategy_title,
  r.strategy_objective,
  COALESCE(u.email,'') AS email,
  COALESCE(u.first_name,'') AS first_name,
  CASE
    WHEN cr.id IS NOT NULL THEN ''
    WHEN r.resolved_workspace_id IS NULL THEN 'workspace_id introuvable pour la tâche planifiée.'
    WHEN r.resolved_user_id IS NULL THEN 'Utilisateur actif introuvable pour la tâche planifiée.'
    ELSE COALESCE((SELECT error_message FROM invalid_marked LIMIT 1),'La demande n’a pas pu être créée.')
  END AS claim_error,
  CASE
    WHEN COALESCE((SELECT payload->>'clean_worker_attempt_count' FROM claimed LIMIT 1),'') ~ '^[0-9]+$'
    THEN ((SELECT payload->>'clean_worker_attempt_count' FROM claimed LIMIT 1))::int
    ELSE 0
  END AS attempt_count
FROM resolved r
LEFT JOIN request_row cr ON true
LEFT JOIN public.app_users u ON u.id = COALESCE(cr.user_id,r.resolved_user_id);
