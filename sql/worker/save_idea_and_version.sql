/* UNIFIED_CALENDAR_WORKER_SAVE_V1 */
WITH input AS (
  SELECT
    CASE WHEN $1::text ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN $1::uuid ELSE NULL END AS request_id,
    CASE WHEN $2::text ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN $2::uuid ELSE NULL END AS workspace_id,
    CASE WHEN $3::text ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN $3::uuid ELSE NULL END AS user_id,
    CASE WHEN $4::text ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN $4::uuid ELSE NULL END AS calendar_id,
    CASE WHEN jsonb_typeof(COALESCE(NULLIF($5::text,'')::jsonb,'{}'::jsonb)) = 'object'
      THEN COALESCE(NULLIF($5::text,'')::jsonb,'{}'::jsonb)
      ELSE '{}'::jsonb END AS idea,
    LEFT(COALESCE($6::text,''),12000) AS ai_raw
), ctx AS MATERIALIZED (
  SELECT
    pr.id AS request_id,
    pr.workspace_id,
    COALESCE(pr.user_id,i.user_id) AS user_id,
    c.id AS calendar_id,
    i.idea,
    i.ai_raw
  FROM input i
  JOIN public.post_requests pr
    ON pr.id = i.request_id
   AND pr.deleted_at IS NULL
  JOIN public.app_growth_strategy_action_calendar c
    ON c.id = i.calendar_id
   AND c.request_id = pr.id
   AND lower(COALESCE(c.status,'')) NOT IN ('obsolete','skipped','cancelled','canceled','archived')
  WHERE i.request_id IS NOT NULL
    AND i.calendar_id IS NOT NULL
    AND (i.workspace_id IS NULL OR pr.workspace_id = i.workspace_id)
    AND NULLIF(btrim(COALESCE(i.idea#>>'{ready_post,text}','')),'') IS NOT NULL
  LIMIT 1
  FOR UPDATE OF pr,c
), existing_ready AS MATERIALIZED (
  SELECT pi.id AS idea_id, pv.id AS version_id
  FROM ctx
  JOIN public.post_ideas pi
    ON pi.request_id = ctx.request_id
   AND pi.workspace_id = ctx.workspace_id
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
  WHERE lower(COALESCE(pi.raw_idea->>'calendar_placeholder','false')) NOT IN ('true','t','1','yes','on')
    AND lower(COALESCE(pi.raw_idea->>'calendar_atomic_fallback','false')) NOT IN ('true','t','1','yes','on')
  ORDER BY (pi.current_version_id = pv.id) DESC, pv.is_current DESC, pv.version_number DESC, pv.id DESC
  LIMIT 1
), existing_empty AS MATERIALIZED (
  SELECT pi.id AS idea_id
  FROM ctx
  JOIN public.post_ideas pi
    ON pi.request_id = ctx.request_id
   AND pi.workspace_id = ctx.workspace_id
   AND pi.deleted_at IS NULL
  WHERE lower(COALESCE(pi.raw_idea->>'calendar_placeholder','false')) NOT IN ('true','t','1','yes','on')
    AND lower(COALESCE(pi.raw_idea->>'calendar_atomic_fallback','false')) NOT IN ('true','t','1','yes','on')
    AND NOT EXISTS (
      SELECT 1 FROM public.post_versions pv
      WHERE pv.idea_id = pi.id
        AND NULLIF(btrim(COALESCE(pv.post_text,'')),'') IS NOT NULL
    )
  ORDER BY pi.number ASC, pi.created_at ASC
  LIMIT 1
  FOR UPDATE OF pi
), updated_empty AS (
  UPDATE public.post_ideas pi
  SET status = 'pending_review',
      title = LEFT(COALESCE(NULLIF(ctx.idea->>'title',''),NULLIF(ctx.idea#>>'{ready_post,title}',''),'Idée de post'),180),
      hook = LEFT(COALESCE(NULLIF(ctx.idea->>'hook',''),NULLIF(ctx.idea->>'title',''),'Accroche'),280),
      summary = LEFT(COALESCE(NULLIF(ctx.idea->>'summary',''),NULLIF(ctx.idea#>>'{ready_post,text}','')),1200),
      recommended_format = LEFT(COALESCE(NULLIF(ctx.idea->>'recommended_format',''),'Post'),100),
      target_sector = LEFT(COALESCE(ctx.idea->>'target_sector',''),180),
      target_audience = LEFT(COALESCE(ctx.idea->>'target_audience',''),260),
      scores = jsonb_build_object(
        'virality_score',COALESCE(NULLIF(ctx.idea->>'virality_score','')::numeric,0),
        'commercial_potential_score',COALESCE(NULLIF(ctx.idea->>'commercial_potential_score','')::numeric,0),
        'implementation_difficulty_score',COALESCE(NULLIF(ctx.idea->>'implementation_difficulty_score','')::numeric,0),
        'sme_interest_score',COALESCE(NULLIF(ctx.idea->>'sme_interest_score','')::numeric,0),
        'enterprise_interest_score',COALESCE(NULLIF(ctx.idea->>'enterprise_interest_score','')::numeric,0),
        'lead_generation_score',COALESCE(NULLIF(ctx.idea->>'lead_generation_score','')::numeric,0)
      ),
      seo_keywords = CASE WHEN jsonb_typeof(ctx.idea->'seo_keywords') = 'array' THEN ctx.idea->'seo_keywords' ELSE '[]'::jsonb END,
      raw_idea = ctx.idea || jsonb_build_object(
        'generation_source','calendar_clean_openrouter_v1',
        'ai_raw_response',ctx.ai_raw,
        'saved_at',now()::text
      ),
      updated_at = now()
  FROM ctx, existing_empty e
  WHERE pi.id = e.idea_id
    AND NOT EXISTS (SELECT 1 FROM existing_ready)
  RETURNING pi.id AS idea_id
), inserted_idea AS (
  INSERT INTO public.post_ideas (
    request_id,user_id,workspace_id,number,status,title,hook,summary,recommended_format,
    target_sector,target_audience,scores,seo_keywords,raw_idea
  )
  SELECT
    ctx.request_id,
    ctx.user_id,
    ctx.workspace_id,
    COALESCE((SELECT MAX(pi.number)+1 FROM public.post_ideas pi WHERE pi.request_id = ctx.request_id),1),
    'pending_review',
    LEFT(COALESCE(NULLIF(ctx.idea->>'title',''),NULLIF(ctx.idea#>>'{ready_post,title}',''),'Idée de post'),180),
    LEFT(COALESCE(NULLIF(ctx.idea->>'hook',''),NULLIF(ctx.idea->>'title',''),'Accroche'),280),
    LEFT(COALESCE(NULLIF(ctx.idea->>'summary',''),NULLIF(ctx.idea#>>'{ready_post,text}','')),1200),
    LEFT(COALESCE(NULLIF(ctx.idea->>'recommended_format',''),'Post'),100),
    LEFT(COALESCE(ctx.idea->>'target_sector',''),180),
    LEFT(COALESCE(ctx.idea->>'target_audience',''),260),
    jsonb_build_object(
      'virality_score',COALESCE(NULLIF(ctx.idea->>'virality_score','')::numeric,0),
      'commercial_potential_score',COALESCE(NULLIF(ctx.idea->>'commercial_potential_score','')::numeric,0),
      'implementation_difficulty_score',COALESCE(NULLIF(ctx.idea->>'implementation_difficulty_score','')::numeric,0),
      'sme_interest_score',COALESCE(NULLIF(ctx.idea->>'sme_interest_score','')::numeric,0),
      'enterprise_interest_score',COALESCE(NULLIF(ctx.idea->>'enterprise_interest_score','')::numeric,0),
      'lead_generation_score',COALESCE(NULLIF(ctx.idea->>'lead_generation_score','')::numeric,0)
    ),
    CASE WHEN jsonb_typeof(ctx.idea->'seo_keywords') = 'array' THEN ctx.idea->'seo_keywords' ELSE '[]'::jsonb END,
    ctx.idea || jsonb_build_object(
      'generation_source','calendar_clean_openrouter_v1',
      'ai_raw_response',ctx.ai_raw,
      'saved_at',now()::text
    )
  FROM ctx
  WHERE NOT EXISTS (SELECT 1 FROM existing_ready)
    AND NOT EXISTS (SELECT 1 FROM existing_empty)
  RETURNING id AS idea_id
), idea_target AS MATERIALIZED (
  SELECT idea_id FROM updated_empty
  UNION ALL
  SELECT idea_id FROM inserted_idea
), inserted_version AS (
  INSERT INTO public.post_versions (
    idea_id,workspace_id,version_number,source,title,post_text,hashtags,cta,is_current,raw_version
  )
  SELECT
    t.idea_id,
    ctx.workspace_id,
    COALESCE((SELECT MAX(v.version_number)+1 FROM public.post_versions v WHERE v.idea_id = t.idea_id),1),
    'calendar_clean_openrouter_v1',
    LEFT(COALESCE(NULLIF(ctx.idea#>>'{ready_post,title}',''),NULLIF(ctx.idea->>'title',''),'Post prêt à publier'),180),
    ctx.idea#>>'{ready_post,text}',
    CASE
      WHEN jsonb_typeof(ctx.idea#>'{ready_post,tags}') = 'array' THEN ctx.idea#>'{ready_post,tags}'
      WHEN jsonb_typeof(ctx.idea->'hashtags') = 'array' THEN ctx.idea->'hashtags'
      ELSE '[]'::jsonb
    END,
    LEFT(COALESCE(NULLIF(ctx.idea#>>'{ready_post,simple_action}',''),NULLIF(ctx.idea->>'call_to_action',''),''),300),
    true,
    ctx.idea->'ready_post'
  FROM idea_target t, ctx
  RETURNING id AS version_id, idea_id
), ready AS MATERIALIZED (
  SELECT idea_id, version_id FROM existing_ready
  UNION ALL
  SELECT idea_id, version_id FROM inserted_version
)
SELECT
  COALESCE((SELECT idea_id::text FROM ready LIMIT 1),'') AS idea_id,
  COALESCE((SELECT version_id::text FROM ready LIMIT 1),'') AS version_id,
  COALESCE((SELECT request_id::text FROM ctx LIMIT 1),'') AS request_id,
  COALESCE((SELECT workspace_id::text FROM ctx LIMIT 1),'') AS workspace_id,
  COALESCE((SELECT user_id::text FROM ctx LIMIT 1),'') AS user_id,
  COALESCE((SELECT calendar_id::text FROM ctx LIMIT 1),'') AS calendar_id,
  CASE WHEN EXISTS (SELECT 1 FROM ready) THEN 1 ELSE 0 END AS saved_count,
  CASE
    WHEN NOT EXISTS (SELECT 1 FROM ctx) THEN 'context_not_found'
    WHEN EXISTS (SELECT 1 FROM existing_ready) THEN 'already_saved'
    WHEN EXISTS (SELECT 1 FROM inserted_version) THEN 'saved'
    ELSE 'save_incomplete'
  END AS save_status;
