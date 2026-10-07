-- Source de vérité: nœud n8n « BDD - Appliquer action stratégie » V90.
-- Statement fonctionnel copié depuis le workflow fourni; bootstrap DDL géré par migrations/.

WITH raw AS (
  SELECT
    COALESCE($1::text,'') AS raw_workspace_id,
    COALESCE($2::text,'') AS raw_strategy_id,
    COALESCE($3::text,'') AS raw_action_id,
    COALESCE($4::text,'') AS raw_action,
    lower(COALESCE($5::text,'')) AS raw_status,
    lower(COALESCE($6::text,'')) AS raw_valid,
    COALESCE($7::text,'') AS raw_prepare_error,
    COALESCE(NULLIF($8::text,''),'[]') AS raw_action_ids,
    COALESCE($9::text,'') AS raw_user_id,
    COALESCE($10::text,'') AS raw_strategy_title,
    COALESCE($11::text,'') AS raw_strategy_objective_label,
    COALESCE($12::text,'') AS raw_strategy_executive_summary,
    COALESCE($13::text,'') AS raw_strategy_primary_target,
    COALESCE($14::text,'') AS raw_strategy_notes,
    COALESCE($15::text,'') AS raw_calendar_id,
    COALESCE($16::text,'') AS raw_planned_for
), p AS (
  SELECT
    CASE WHEN raw_workspace_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN raw_workspace_id::uuid ELSE NULL END AS workspace_id,
    CASE WHEN raw_strategy_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN raw_strategy_id::uuid ELSE NULL END AS strategy_id,
    CASE WHEN raw_action_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN raw_action_id::uuid ELSE NULL END AS action_id,
    CASE WHEN raw_user_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN raw_user_id::uuid ELSE NULL END AS user_id,
    CASE WHEN raw_calendar_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN raw_calendar_id::uuid ELSE NULL END AS calendar_id,
    CASE
      WHEN NULLIF(raw_planned_for,'') IS NOT NULL
       AND raw_planned_for ~* '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}'
      THEN raw_planned_for::timestamptz
      WHEN NULLIF(raw_planned_for,'') IS NOT NULL
       AND raw_planned_for ~* '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}'
      THEN raw_planned_for::timestamptz
      ELSE NULL
    END AS calendar_planned_for,
    raw_action AS action,
    CASE
      WHEN raw_status='doing' THEN 'in_progress'
      WHEN raw_status='cancelled' THEN 'skipped'
      WHEN raw_status IN ('pending','in_progress','done','skipped','draft','active','paused','completed') THEN raw_status
      ELSE 'pending'
    END AS status,
    raw_valid IN ('true','t','1','yes','on') AS valid,
    raw_prepare_error AS prepare_error,
    COALESCE(raw_action_ids,'[]')::jsonb AS action_ids_json,
    LEFT(BTRIM(raw_strategy_title),180) AS update_title,
    LEFT(BTRIM(raw_strategy_objective_label),260) AS update_objective_label,
    LEFT(BTRIM(raw_strategy_executive_summary),1200) AS update_executive_summary,
    LEFT(BTRIM(raw_strategy_primary_target),500) AS update_primary_target,
    LEFT(BTRIM(raw_strategy_notes),1200) AS update_notes
  FROM raw
), selected_action_ids AS (
  SELECT DISTINCT action_id
  FROM (
    SELECT p.action_id
    FROM p
    WHERE p.action IN ('set_action_status','generate_action_posts','schedule_action_posts')
      AND p.action_id IS NOT NULL

    UNION ALL

    SELECT value::uuid AS action_id
    FROM p
    CROSS JOIN LATERAL jsonb_array_elements_text(
      CASE WHEN jsonb_typeof(p.action_ids_json)='array' THEN p.action_ids_json ELSE '[]'::jsonb END
    ) AS x(value)
    WHERE p.action IN ('bulk_set_action_status','bulk_generate_action_posts','bulk_schedule_action_posts')
      AND value ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
  ) ids
), owned_strategy AS (
  SELECT s.*
  FROM public.app_growth_strategies s
  JOIN p ON p.strategy_id IS NOT NULL AND s.id = p.strategy_id
  WHERE
    p.valid = true
    AND (
      p.workspace_id IS NULL
      OR s.workspace_id IS NULL
      OR s.workspace_id = p.workspace_id
    )
    AND COALESCE(s.status,'') <> 'archived'
  LIMIT 1
), selected_actions AS (
  SELECT
    a.id,
    a.title,
    COALESCE(a.description,'') AS description,
    COALESCE(a.category,'growth') AS category,
    COALESCE(a.priority,'medium') AS priority,
    COALESCE(a.kpi,'{}'::jsonb) AS kpi,
    COALESCE(a.media_prefill,'{}'::jsonb) AS media_prefill,
    COALESCE(
      NULLIF(COALESCE(a.kpi,'{}'::jsonb)#>>'{calendar_plan,schedule_kind}',''),
      CASE
        WHEN lower(COALESCE(a.category,'')) IN ('profil','profile')
          OR lower(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable') ~ '(cta visible sur le profil|bio|lien du profil|optimisation profil)'
          OR lower(COALESCE(a.kpi,'{}'::jsonb)->>'content_format') ~ '(bio|lien du profil|contenu épinglé|contenu epingle)'
          THEN 'profile'
        WHEN lower(COALESCE(a.category,'')) IN ('mesure','measurement','analysis','analyse')
          OR lower(a.title || ' ' || COALESCE(a.description,'')) ~ '(faire un bilan|tableau décisionnel|tableau decisionnel|décision par pilier|decision par pilier|analyse kpi)'
          THEN 'measurement'
        WHEN lower(COALESCE(a.category,''))='engagement'
          OR lower(a.title || ' ' || COALESCE(a.description,'')) ~ '(routine d.interaction|commentaires ciblés|commentaires cibles|réponses aux questions|reponses aux questions)'
          THEN 'engagement'
        ELSE 'publishable_content'
      END
    ) AS schedule_kind,
    COALESCE(
      NULLIF(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable',''),
      NULLIF(substring(COALESCE(a.description,'') from '(?i)(?:livrable|deliverable|sortie|output)\s*:\s*([^|.\n]+)'),''),
      CASE
        WHEN lower(a.title || ' ' || COALESCE(a.description,'')) LIKE '%reel%' OR lower(a.title || ' ' || COALESCE(a.description,'')) LIKE '%réel%' OR lower(a.title || ' ' || COALESCE(a.description,'')) LIKE '%video%' OR lower(a.title || ' ' || COALESCE(a.description,'')) LIKE '%vidéo%' THEN '1 reel prêt à publier'
        WHEN lower(a.title || ' ' || COALESCE(a.description,'')) LIKE '%carrousel%' OR lower(a.title || ' ' || COALESCE(a.description,'')) LIKE '%carousel%' THEN '1 carrousel prêt à publier'
        WHEN lower(a.title || ' ' || COALESCE(a.description,'')) LIKE '%bio%' OR lower(a.title || ' ' || COALESCE(a.description,'')) LIKE '%profil%' THEN 'optimisation profil / bio'
        WHEN lower(a.title || ' ' || COALESCE(a.description,'')) LIKE '%kpi%' OR lower(a.title || ' ' || COALESCE(a.description,'')) LIKE '%analyse%' OR lower(a.title || ' ' || COALESCE(a.description,'')) LIKE '%mesur%' THEN 'analyse KPI et recommandation corrective'
        ELSE '1 post prêt à publier'
      END
    ) AS deliverable,
    COALESCE(
      NULLIF(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable_kind',''),
      CASE
        WHEN lower(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable') LIKE '%reel%' OR lower(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable') LIKE '%réel%' OR lower(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable') LIKE '%video%' OR lower(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable') LIKE '%vidéo%' THEN 'reel'
        WHEN lower(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable') LIKE '%carrousel%' OR lower(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable') LIKE '%carousel%' THEN 'carousel'
        WHEN lower(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable') LIKE '%séquence%' OR lower(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable') LIKE '%sequence%' THEN 'sequence'
        WHEN lower(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable') LIKE '%bio%' OR lower(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable') LIKE '%profil%' THEN 'profile_update'
        WHEN lower(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable') LIKE '%kpi%' OR lower(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable') LIKE '%analyse%' OR lower(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable') LIKE '%mesure%' THEN 'analysis'
        ELSE 'post'
      END
    ) AS deliverable_kind,
    COALESCE(
      NULLIF(COALESCE(a.kpi,'{}'::jsonb)->>'content_format',''),
      NULLIF(COALESCE(a.kpi,'{}'::jsonb)->>'format',''),
      NULLIF(substring(COALESCE(a.description,'') from '(?i)(?:format|forme|support)\s*:\s*([^|.\n]+)'),''),
      CASE
        WHEN lower(a.title || ' ' || COALESCE(a.description,'') || ' ' || COALESCE(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable','')) LIKE '%reel%' OR lower(a.title || ' ' || COALESCE(a.description,'') || ' ' || COALESCE(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable','')) LIKE '%réel%' OR lower(a.title || ' ' || COALESCE(a.description,'') || ' ' || COALESCE(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable','')) LIKE '%video%' OR lower(a.title || ' ' || COALESCE(a.description,'') || ' ' || COALESCE(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable','')) LIKE '%vidéo%' THEN 'reel court 30-45s'
        WHEN lower(a.title || ' ' || COALESCE(a.description,'') || ' ' || COALESCE(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable','')) LIKE '%carrousel%' OR lower(a.title || ' ' || COALESCE(a.description,'') || ' ' || COALESCE(COALESCE(a.kpi,'{}'::jsonb)->>'deliverable','')) LIKE '%carousel%' THEN 'carrousel 6 slides'
        WHEN lower(a.title || ' ' || COALESCE(a.description,'')) LIKE '%kpi%' OR lower(a.title || ' ' || COALESCE(a.description,'')) LIKE '%analyse%' OR lower(a.title || ' ' || COALESCE(a.description,'')) LIKE '%mesur%' THEN 'rapport synthèse + recommandations'
        WHEN lower(a.title || ' ' || COALESCE(a.description,'')) LIKE '%bio%' OR lower(a.title || ' ' || COALESCE(a.description,'')) LIKE '%profil%' OR lower(a.title || ' ' || COALESCE(a.description,'')) LIKE '%audit%' THEN 'checklist opérationnelle'
        ELSE 'post texte court'
      END
    ) AS content_format,
    COALESCE(
      NULLIF(COALESCE(a.kpi,'{}'::jsonb)->>'format_kind',''),
      CASE
        WHEN lower(COALESCE(a.kpi,'{}'::jsonb)->>'content_format') LIKE '%reel%' OR lower(COALESCE(a.kpi,'{}'::jsonb)->>'content_format') LIKE '%réel%' OR lower(COALESCE(a.kpi,'{}'::jsonb)->>'content_format') LIKE '%video%' OR lower(COALESCE(a.kpi,'{}'::jsonb)->>'content_format') LIKE '%vidéo%' THEN 'reel'
        WHEN lower(COALESCE(a.kpi,'{}'::jsonb)->>'content_format') LIKE '%carrousel%' OR lower(COALESCE(a.kpi,'{}'::jsonb)->>'content_format') LIKE '%carousel%' OR lower(COALESCE(a.kpi,'{}'::jsonb)->>'content_format') LIKE '%slides%' THEN 'carousel'
        WHEN lower(COALESCE(a.kpi,'{}'::jsonb)->>'content_format') LIKE '%séquence%' OR lower(COALESCE(a.kpi,'{}'::jsonb)->>'content_format') LIKE '%sequence%' THEN 'sequence'
        WHEN lower(COALESCE(a.kpi,'{}'::jsonb)->>'content_format') LIKE '%checklist%' OR lower(COALESCE(a.kpi,'{}'::jsonb)->>'content_format') LIKE '%audit%' THEN 'checklist'
        WHEN lower(COALESCE(a.kpi,'{}'::jsonb)->>'content_format') LIKE '%rapport%' OR lower(COALESCE(a.kpi,'{}'::jsonb)->>'content_format') LIKE '%analyse%' OR lower(COALESCE(a.kpi,'{}'::jsonb)->>'content_format') LIKE '%kpi%' THEN 'report'
        ELSE 'text_post'
      END
    ) AS format_kind,
    COALESCE(a.status,'pending') AS current_status,
    COALESCE(a.due_day,1) AS due_day,
    ROW_NUMBER() OVER (
      ORDER BY
        CASE
          WHEN COALESCE(a.kpi,'{}'::jsonb)#>>'{calendar_plan,spacing_group}'='quick_win' THEN 1
          WHEN COALESCE(a.kpi,'{}'::jsonb)#>>'{calendar_plan,spacing_group}' IN ('proof','education') THEN 2
          WHEN COALESCE(a.kpi,'{}'::jsonb)#>>'{calendar_plan,spacing_group}'='conversion' THEN 3
          WHEN COALESCE(a.kpi,'{}'::jsonb)#>>'{calendar_plan,spacing_group}'='measurement' THEN 4
          WHEN lower(COALESCE(a.category,'')) IN ('profil','profile') THEN 1
          WHEN lower(COALESCE(a.category,'')) IN ('conversion','sales') THEN 3
          WHEN lower(COALESCE(a.category,'')) IN ('mesure','measurement','analysis','analyse') THEN 4
          WHEN lower(a.title || ' ' || COALESCE(a.description,'')) ~ '(bio|profil|cadrage|prépar|prepar|checklist|audit)' THEN 1
          WHEN lower(a.title || ' ' || COALESCE(a.description,'')) ~ '(conversion|cta|offre|lead|vente|démo|demo)' THEN 3
          WHEN lower(a.title || ' ' || COALESCE(a.description,'')) ~ '(mesur|kpi|analyse|report|optimis|bilan)' THEN 4
          WHEN lower(a.title || ' ' || COALESCE(a.description,'')) ~ '(preuve|cas client|témoign|temoign|avant.après|avant.apres|résultat|resultat)' THEN 2
          ELSE 2
        END,
        CASE COALESCE(a.priority,'medium') WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
        COALESCE(
          CASE WHEN (COALESCE(a.kpi,'{}'::jsonb)#>>'{calendar_plan,recommended_offset_days}') ~ '^[0-9]{1,3}$'
            THEN (COALESCE(a.kpi,'{}'::jsonb)#>>'{calendar_plan,recommended_offset_days}')::int ELSE NULL END,
          COALESCE(a.due_day,1)
        ),
        a.created_at
    ) AS rn
  FROM public.app_growth_strategy_actions a
  JOIN selected_action_ids ids ON ids.action_id = a.id
  JOIN owned_strategy s ON s.id = a.strategy_id
),
-- AI_AUTO_CALENDAR_SHORT_WINDOW_FIX_2026_07_29
-- AI_CALENDAR_HORIZON_DURATION_FIX_2026_07_29
-- AI_REALISTIC_PROGRAM_HORIZON_SQL_2026_07_29
/* AUDIENCE_OPTIMIZED_SCHEDULING_V35_2026_08_06 */
/* ACTION_TYPE_AWARE_SCHEDULING_V36_2026_08_06 */
ai_plan_requested AS (
  SELECT
    sa.*,
    GREATEST(7,LEAST(365,COALESCE((SELECT duration_days FROM owned_strategy LIMIT 1),90))) AS max_horizon_days,
    GREATEST(
      7,
      LEAST(
        GREATEST(7,LEAST(365,COALESCE((SELECT duration_days FROM owned_strategy LIMIT 1),90))),
        COALESCE(
          CASE
            WHEN ((SELECT strategy_data FROM owned_strategy LIMIT 1)#>>'{objective_timeline,estimated_days_to_target}') ~ '^[0-9]{1,3}$'
            THEN ((SELECT strategy_data FROM owned_strategy LIMIT 1)#>>'{objective_timeline,estimated_days_to_target}')::int
            ELSE NULL
          END,
          ROUND(GREATEST(7,LEAST(365,COALESCE((SELECT duration_days FROM owned_strategy LIMIT 1),90)))*0.70)::int
        )
      )
    ) AS realistic_horizon_days,
    COUNT(*) OVER ()::int AS total_actions,
    CASE
      WHEN (sa.kpi#>>'{calendar_plan,recommended_offset_days}') ~ '^[0-9]{1,3}$'
        THEN GREATEST(1,(sa.kpi#>>'{calendar_plan,recommended_offset_days}')::int)
      ELSE GREATEST(1,COALESCE(sa.due_day,1))
    END AS requested_offset_days,
    CASE
      WHEN sa.schedule_kind='profile' THEN 9
      WHEN sa.schedule_kind='measurement' THEN 10
      WHEN sa.schedule_kind='engagement' THEN 17
      WHEN (sa.kpi#>>'{calendar_plan,recommended_hour}') ~ '^[0-9]{1,2}$'
        THEN GREATEST(7,LEAST(21,(sa.kpi#>>'{calendar_plan,recommended_hour}')::int))
      WHEN sa.format_kind='reel' OR sa.deliverable_kind='reel' THEN 18
      WHEN sa.format_kind='carousel' OR sa.deliverable_kind='carousel' THEN 11
      WHEN lower(sa.title || ' ' || sa.description) ~ '(reel|réel|vidéo|video)' THEN 18
      WHEN lower(sa.title || ' ' || sa.description) ~ '(b2b|dirigeant|entreprise)' THEN 9
      ELSE 11
    END AS ai_hour,
    CASE
      WHEN COALESCE(sa.kpi#>>'{calendar_plan,spacing_group}','') IN ('quick_win','proof','education','conversion','measurement')
        THEN sa.kpi#>>'{calendar_plan,spacing_group}'
      WHEN lower(COALESCE(sa.category,'')) IN ('profil','profile')
        OR lower(sa.title || ' ' || sa.description) ~ '(bio|profil|cadrage|prépar|prepar|checklist|audit)'
        OR sa.deliverable_kind IN ('profile_update','planning')
        OR sa.format_kind='checklist'
        THEN 'quick_win'
      WHEN lower(COALESCE(sa.category,'')) IN ('conversion','sales')
        OR lower(sa.title || ' ' || sa.description) ~ '(conversion|cta|offre|lead|vente|démo|demo)'
        THEN 'conversion'
      WHEN lower(COALESCE(sa.category,'')) IN ('mesure','measurement','analysis','analyse')
        OR lower(sa.title || ' ' || sa.description) ~ '(mesur|kpi|analyse|report|optimis|bilan)'
        OR sa.deliverable_kind='analysis'
        OR sa.format_kind='report'
        THEN 'measurement'
      WHEN lower(sa.title || ' ' || sa.description) ~ '(preuve|cas client|témoign|temoign|avant.après|avant.apres|résultat|resultat)'
        THEN 'proof'
      ELSE 'education'
    END AS ai_group,
    COALESCE(
      NULLIF(sa.kpi#>>'{calendar_plan,reason}',''),
      'Créneau choisi selon la priorité, la phase marketing et l’horizon réaliste.'
    ) AS requested_reason
  FROM selected_actions sa
),
ai_plan_parameters AS (
  SELECT
    r.*,
    CASE
      WHEN r.total_actions<=1 THEN 1
      ELSE GREATEST(
        1,
        LEAST(
          7,
          FLOOR((r.realistic_horizon_days-1)::numeric/GREATEST(1,r.total_actions-1))::int
        )
      )
    END AS cadence_days,
    CASE r.ai_group
      WHEN 'quick_win' THEN 1
      WHEN 'proof' THEN GREATEST(2,ROUND(r.realistic_horizon_days*0.15)::int)
      WHEN 'education' THEN GREATEST(2,ROUND(r.realistic_horizon_days*0.25)::int)
      WHEN 'conversion' THEN GREATEST(5,ROUND(r.realistic_horizon_days*0.55)::int)
      WHEN 'measurement' THEN GREATEST(7,ROUND(r.realistic_horizon_days*0.80)::int)
      ELSE 1
    END AS phase_minimum_days
  FROM ai_plan_requested r
),
ai_plan_bounds AS (
  SELECT
    p.*,
    1+((p.rn-1)*p.cadence_days) AS distributed_offset_days,
    GREATEST(
      1+((p.rn-1)*p.cadence_days),
      p.realistic_horizon_days-((p.total_actions-p.rn)*p.cadence_days)
    ) AS latest_allowed_days
  FROM ai_plan_parameters p
),
ai_plan_candidates AS (
  SELECT
    b.*,
    LEAST(
      b.latest_allowed_days,
      GREATEST(
        b.requested_offset_days,
        b.distributed_offset_days,
        b.phase_minimum_days
      )
    )::int AS candidate_offset_days
  FROM ai_plan_bounds b
),
ai_plan_resolved AS (
  SELECT
    c.*,
    LEAST(
      c.realistic_horizon_days,
      (
        c.cadence_days*c.rn
        + MAX(c.candidate_offset_days-(c.cadence_days*c.rn))
          OVER (ORDER BY c.rn ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
      )
    )::int AS resolved_offset_days
  FROM ai_plan_candidates c
),
/* INTELLIGENT_CALENDAR_CTE_SYNTAX_FIX_V34_2026_08_06 */
ai_planned_actions AS (
  SELECT
    r.*,
    r.resolved_offset_days AS ai_offset_days,
    CASE
      WHEN r.resolved_offset_days<>r.requested_offset_days
        THEN LEFT(
          r.requested_reason ||
          ' Répartition ajustée automatiquement pour éviter plusieurs actions le même jour et respecter la séquence quick win → preuve → conversion → mesure.',
          500
        )
      ELSE LEFT(r.requested_reason,500)
    END AS ai_reason
  FROM ai_plan_resolved r
), updated_action AS (
  UPDATE public.app_growth_strategy_actions a
  SET status = p.status, updated_at = now()
  FROM p
  WHERE p.valid = true
    AND p.action = 'set_action_status'
    AND a.strategy_id = p.strategy_id
    AND a.id = p.action_id
  RETURNING a.id::text AS id, a.status::text AS status
), updated_bulk_actions AS (
  UPDATE public.app_growth_strategy_actions a
  SET status = p.status, updated_at = now()
  FROM p
  WHERE p.valid = true
    AND p.action = 'bulk_set_action_status'
    AND a.strategy_id = p.strategy_id
    AND EXISTS (SELECT 1 FROM selected_action_ids ids WHERE ids.action_id = a.id)
  RETURNING a.id::text AS id, a.status::text AS status
), strategy_context AS (
  SELECT
    s.id,
    s.workspace_id,
    COALESCE(p.user_id,s.created_by) AS user_id,
    COALESCE(NULLIF(s.title,''),'Stratégie Instagram') AS strategy_title,
    COALESCE(NULLIF(s.objective_label,''),'croissance du compte') AS objective_label,
    COALESCE(s.strategy_data,'{}'::jsonb) AS strategy_data,
    COALESCE(s.form_data,'{}'::jsonb) AS form_data,
    COALESCE(s.network_snapshot,'{}'::jsonb) AS network_snapshot,
    COALESCE(s.duration_days,90) AS duration_days
  FROM owned_strategy s
  JOIN p ON true
), /* SCHEDULE_PAYLOAD_ALIAS_FIX_V38_2026_08_06 */
schedule_payload_base AS (
  SELECT
    sc.*,
    sa.id AS action_id,
    sa.title AS action_title,
    sa.description AS action_description,
    sa.category,
    sa.priority,
    sa.schedule_kind,
    sa.kpi,
    COALESCE(sa.media_prefill,'{}'::jsonb) AS media_prefill,
    sa.deliverable,
    sa.deliverable_kind,
    sa.content_format,
    sa.format_kind,
    COALESCE(sc.strategy_data->'target_analysis','{}'::jsonb) AS target_analysis,
    sa.rn,
    COALESCE((SELECT calendar_planned_for FROM p), (
      GREATEST(
        date_trunc('day', now() + (sa.ai_offset_days * interval '1 day')),
        COALESCE(
          (
            SELECT date_trunc('day', MAX(existing.planned_for)) + interval '1 day'
            FROM public.app_growth_strategy_action_calendar existing
            WHERE existing.strategy_id=sc.id
              AND COALESCE(existing.status,'scheduled') IN
                  ('scheduled','generating','generated','approved','published','done','completed')
              AND COALESCE(existing.payload->>'kind','') <> 'adaptive_checkpoint'
              AND existing.action_id IS DISTINCT FROM sa.id
          ),
          date_trunc('day', now() + (sa.ai_offset_days * interval '1 day'))
        )
      )
      + (sa.ai_hour * interval '1 hour')
    )) AS planned_for,
    sa.ai_offset_days,
    sa.ai_hour,
    sa.ai_group,
    sa.ai_reason,
    sa.realistic_horizon_days,
    sa.max_horizon_days,
    CASE
      WHEN (SELECT calendar_planned_for FROM p) IS NOT NULL
      THEN (SELECT calendar_planned_for FROM p) + interval '1 hour'
      ELSE CASE
      WHEN sa.schedule_kind='publishable_content'
       AND (sa.kpi#>>'{calendar_plan,recommended_publish_offset_days}') ~ '^[0-9]{1,3}$'
       AND (sa.kpi#>>'{calendar_plan,recommended_publish_hour}') ~ '^[0-9]{1,2}$'
      THEN (
        date_trunc(
          'day',
          now() + (
            (sa.kpi#>>'{calendar_plan,recommended_publish_offset_days}')::int
            * interval '1 day'
          )
        )
        + (
          GREATEST(
            7,
            LEAST(
              21,
              (sa.kpi#>>'{calendar_plan,recommended_publish_hour}')::int
            )
          ) * interval '1 hour'
        )
      )
      ELSE NULL
      END
    END AS recommended_publish_for,
    COALESCE(
      CASE
        WHEN (sa.kpi#>>'{calendar_plan,generation_lead_days}') ~ '^[0-9]{1,2}$'
        THEN (sa.kpi#>>'{calendar_plan,generation_lead_days}')::int
        ELSE NULL
      END,
      0
    ) AS generation_lead_days,
    CASE
      WHEN lower(COALESCE(sa.kpi#>>'{calendar_plan,generation_required}','')) IN ('true','t','1','yes','on') THEN true
      WHEN lower(COALESCE(sa.kpi#>>'{calendar_plan,generation_required}','')) IN ('false','f','0','no','off') THEN false
      ELSE sa.schedule_kind='publishable_content'
    END AS generation_required
  FROM strategy_context sc
  JOIN ai_planned_actions sa ON true
),
schedule_payload AS (
  SELECT
    base.*,
    (
      'Créer 1 post prêt à publier à partir de cette action de stratégie Instagram.'
      || E'\n\n'
      || 'Objectif stratégique : ' || base.objective_label
      || E'\n\n'
      || 'Action à transformer en contenu :'
      || E'\n'
      || '- ' || base.action_title
      || CASE
          WHEN base.action_description<>'' THEN ' : ' || base.action_description
          ELSE ''
        END
      || E'\n'
      || 'Livrable attendu : '
      || COALESCE(NULLIF(base.deliverable,''),'1 post prêt à publier')
      || E'\n'
      || 'Format attendu : '
      || COALESCE(NULLIF(base.content_format,''),'post texte court')
      || E'\n'
      || 'Cible prioritaire : '
      || COALESCE(
          NULLIF(base.strategy_data#>>'{target_analysis,primary_target}',''),
          COALESCE(
            base.strategy_data#>>'{account_overview,target_audience}',
            'audience du compte'
          )
        )
      || E'\n'
      || 'Persona : '
      || COALESCE(
          NULLIF(base.strategy_data#>>'{target_analysis,persona}',''),
          'persona non disponible'
        )
      || E'\n\n'
      || 'Contrainte de planning IA : génération prévue automatiquement à J+'
      || base.ai_offset_days::text
      || ' vers '
      || base.ai_hour::text
      || 'h.'
      || CASE
          WHEN base.recommended_publish_for IS NOT NULL
          THEN
            ' Publication recommandée : '
            || to_char(
                base.recommended_publish_for AT TIME ZONE 'Europe/Paris',
                'DD/MM/YYYY HH24:MI'
              )
            || ' Europe/Paris.'
          ELSE ''
        END
      || ' Raison : '
      || base.ai_reason
      || E'\n\n'
      || 'Contraintes : produire un contenu concret, publiable, orienté gain de temps et preuve. '
      || 'Ne pas inventer de chiffres. Proposer une accroche, un CTA et un angle exploitable.'
    ) AS generation_prompt
  FROM schedule_payload_base base
), active_existing_calendar AS (
  SELECT
    c.id,
    c.strategy_id,
    c.planned_for,
    c.created_at,
    COALESCE(c.action_id::text, c.payload#>>'{action,id}', ids.value, '') AS action_id,
    COALESCE(c.status,'scheduled') AS status
  FROM public.app_growth_strategy_action_calendar c
  JOIN p ON p.valid = true AND c.strategy_id = p.strategy_id
  LEFT JOIN LATERAL (
    SELECT value
    FROM jsonb_array_elements_text(
      CASE WHEN jsonb_typeof(c.action_ids)='array' THEN c.action_ids ELSE '[]'::jsonb END
    ) AS x(value)
    LIMIT 1
  ) ids ON true
  WHERE COALESCE(c.status,'scheduled') IN ('scheduled','generating')
    AND COALESCE(c.action_id::text, c.payload#>>'{action,id}', ids.value, '') <> ''
), calendar_duplicate_cleanup AS (
  UPDATE public.app_growth_strategy_action_calendar c
  SET
    status = 'skipped',
    updated_at = now(),
    error_message = 'Doublon de planification ignoré automatiquement.'
  FROM (
    SELECT id
    FROM (
      SELECT
        id,
        ROW_NUMBER() OVER (
          PARTITION BY strategy_id, action_id
          ORDER BY planned_for ASC NULLS LAST, created_at ASC NULLS LAST, id::text ASC
        ) AS rn
      FROM active_existing_calendar
    ) ranked
    WHERE rn > 1
  ) d
  WHERE c.id = d.id
  RETURNING c.id
), already_planned_actions AS (
  SELECT DISTINCT sp.action_id
  FROM schedule_payload sp
  JOIN p ON p.action IN ('schedule_action_posts','bulk_schedule_action_posts','generate_action_posts','bulk_generate_action_posts')
  WHERE p.valid = true
    AND (SELECT COUNT(*) FROM calendar_duplicate_cleanup) >= 0
    AND EXISTS (
      SELECT 1
      FROM public.app_growth_strategy_action_calendar existing
      LEFT JOIN LATERAL (
        SELECT value
        FROM jsonb_array_elements_text(
          CASE WHEN jsonb_typeof(existing.action_ids)='array' THEN existing.action_ids ELSE '[]'::jsonb END
        ) AS x(value)
        WHERE value = sp.action_id::text
        LIMIT 1
      ) existing_ids ON true
      WHERE existing.strategy_id = sp.id
        AND COALESCE(existing.status,'scheduled') IN ('scheduled','generating','generated','done')
        AND COALESCE(existing.action_id::text, existing.payload#>>'{action,id}', existing_ids.value, '') = sp.action_id::text
    )
) /* NO_DUPLICATE_PLANNING_SQL_2026_07_30 */, -- SCHEDULE_SQL_ALIAS_FIX_2026_07_29
calendar_inserted AS (
  INSERT INTO public.app_growth_strategy_action_calendar (
    workspace_id,strategy_id,action_id,action_ids,planned_for,status,payload,created_by,created_at,updated_at
  )
  SELECT
    sp.workspace_id,
    sp.id,
    sp.action_id,
    jsonb_build_array(sp.action_id::text),
    sp.planned_for,
    'scheduled',
    jsonb_build_object(
      'generation_required',sp.generation_required,
      'requires_post_generation',sp.generation_required,
      'subject', LEFT(sp.action_title,240),
      'prompt', CASE WHEN sp.generation_required THEN sp.generation_prompt ELSE '' END,
      'theme', CASE WHEN sp.generation_required THEN sp.generation_prompt ELSE '' END,
      'post_count',
        CASE
          WHEN sp.deliverable ~* '(^|[^0-9])([2-8])\s*(posts|contenus|reels|réels|carrousels|carousels)' THEN substring(sp.deliverable from '([2-8])')::int
          ELSE 1
        END,
      'deliverable', sp.deliverable,
      'deliverable_kind', sp.deliverable_kind,
      'format', sp.content_format,
      'content_format', sp.content_format,
      'format_kind', sp.format_kind,
      'commercial_objective', sp.objective_label,
      'content_domains', jsonb_build_array('Stratégie Instagram','Croissance','Contenu preuve','Automatisation'),
      'target_audience', jsonb_build_array(
        COALESCE(NULLIF(sp.target_analysis->>'primary_target',''), NULLIF(sp.strategy_data#>>'{target_analysis,primary_target}',''), NULLIF(sp.strategy_data#>>'{account_overview,target_audience}',''), 'audience du compte'),
        COALESCE(NULLIF(sp.target_analysis->>'persona',''), NULLIF(sp.strategy_data#>>'{target_analysis,persona}',''), NULLIF(sp.strategy_data#>>'{account_overview,positioning}',''), 'prospects qualifiés'),
        COALESCE(NULLIF(sp.target_analysis->>'awareness_level',''), 'problem_aware')
      ),
      'preferred_formats',
        CASE
          WHEN sp.format_kind='reel' THEN jsonb_build_array('reel')
          WHEN sp.format_kind='carousel' THEN jsonb_build_array('image simple')
          WHEN sp.format_kind='sequence' THEN jsonb_build_array('post','reel','carrousel')
          WHEN sp.format_kind IN ('checklist','report','text_post') THEN jsonb_build_array('post')
          WHEN sp.deliverable_kind='reel' THEN jsonb_build_array('reel')
          WHEN sp.deliverable_kind='carousel' THEN jsonb_build_array('image simple')
          ELSE jsonb_build_array('post')
        END,
      'language', 'français',
      'strategy_id', sp.id::text,
      'strategy_title', sp.strategy_title,
      'objective_label', sp.objective_label,
      'media_prefill', sp.media_prefill,
      'recommended_publish_for', sp.recommended_publish_for,
      'generation_lead_days', sp.generation_lead_days,
      'ai_calendar', jsonb_build_object(
        'offset_days',sp.ai_offset_days,
        'hour',sp.ai_hour,
        'group',sp.ai_group,
        'schedule_kind',sp.schedule_kind,
        'generation_required',sp.generation_required,
        'requires_post_generation',sp.generation_required,
        'reason',sp.ai_reason,
        'deliverable',sp.deliverable,
        'deliverable_kind',sp.deliverable_kind,
        'format',sp.content_format,
        'format_kind',sp.format_kind,
        'planned_for',sp.planned_for,
        'generation_planned_for',sp.planned_for,
        'recommended_publish_for',sp.recommended_publish_for,
        'generation_lead_days',sp.generation_lead_days,
        'horizon_days',sp.realistic_horizon_days,
        'max_days',sp.max_horizon_days,
        'audience_optimized',COALESCE((sp.kpi#>>'{calendar_plan,audience_optimized}')::boolean,false),
        'audience_source',COALESCE(sp.kpi#>>'{calendar_plan,audience_source}','platform_fallback'),
        'audience_sample_size',COALESCE(NULLIF(sp.kpi#>>'{calendar_plan,audience_sample_size}','')::int,0),
        'audience_confidence',COALESCE(sp.kpi#>>'{calendar_plan,audience_confidence}','low'),
        'audience_timezone',COALESCE(sp.kpi#>>'{calendar_plan,audience_timezone}','Europe/Paris'),
        'recommended_weekday',COALESCE(NULLIF(sp.kpi#>>'{calendar_plan,recommended_weekday}','')::int,EXTRACT(ISODOW FROM sp.planned_for)::int)
      ),
      'action', jsonb_build_object(
        'id',sp.action_id::text,
        'title',sp.action_title,
        'description',sp.action_description,
        'category',sp.category,
        'priority',sp.priority,
        'schedule_kind',sp.schedule_kind,
        'generation_required',sp.generation_required,
        'requires_post_generation',sp.generation_required,
        'kpi',sp.kpi,
        'media_prefill',sp.media_prefill,
        'deliverable',sp.deliverable,
        'deliverable_kind',sp.deliverable_kind,
        'format',sp.content_format,
        'format_kind',sp.format_kind
      ),
      'target_analysis', sp.target_analysis,
      'strategy_data', sp.strategy_data,
      'network_snapshot', sp.network_snapshot
    ),
    sp.user_id,
    now(),
    now()
  FROM schedule_payload sp
  JOIN p ON p.action IN ('schedule_action_posts','bulk_schedule_action_posts','generate_action_posts','bulk_generate_action_posts')
  WHERE p.valid = true
    AND sp.user_id IS NOT NULL
    AND sp.workspace_id IS NOT NULL
    AND (SELECT COUNT(*) FROM calendar_duplicate_cleanup) >= 0
    AND NOT EXISTS (
      SELECT 1
      FROM already_planned_actions apa
      WHERE apa.action_id = sp.action_id
    )
  ON CONFLICT DO NOTHING
  RETURNING id AS calendar_id, strategy_id, workspace_id, action_ids, planned_for, payload
), schedule_bounds AS (
  SELECT
    sp.id AS strategy_id,
    sp.workspace_id,
    sp.user_id,
    MAX(sp.realistic_horizon_days)::int AS realistic_horizon_days,
    MAX(sp.max_horizon_days)::int AS max_horizon_days,
    MAX(sp.objective_label) AS objective_label,
    MAX(sp.strategy_title) AS strategy_title,
    (jsonb_agg(sp.strategy_data)->0) AS strategy_data,
    (jsonb_agg(sp.network_snapshot)->0) AS network_snapshot
  FROM schedule_payload sp
  GROUP BY sp.id, sp.workspace_id, sp.user_id
), adaptive_checkpoint_source AS (
  SELECT
    sb.*,
    cp.checkpoint_no,
    cp.ratio,
    cp.expected_ratio,
    GREATEST(2, LEAST(sb.realistic_horizon_days, ROUND(sb.realistic_horizon_days * cp.ratio)::int)) AS offset_days,
    CASE cp.checkpoint_no
      WHEN 1 THEN 'Changer l’angle de contenu et renforcer la preuve si la progression est en retard.'
      WHEN 2 THEN 'Tester un format plus engageant, clarifier le CTA et recycler le meilleur signal.'
      ELSE 'Lancer une action corrective finale : preuve forte, offre claire et CTA direct.'
    END AS if_behind,
    CASE cp.checkpoint_no
      WHEN 1 THEN 'Amplifier les angles qui commencent à créer des interactions.'
      WHEN 2 THEN 'Préparer la conversion et consolider les contenus qui fonctionnent.'
      ELSE 'Consolider le résultat et préparer le prochain cycle de croissance.'
    END AS if_on_track
  FROM schedule_bounds sb
  CROSS JOIN (VALUES
    (1,0.33::numeric,0.30::numeric),
    (2,0.66::numeric,0.65::numeric),
    (3,0.90::numeric,0.90::numeric)
  ) AS cp(checkpoint_no,ratio,expected_ratio)
), checkpoint_inserted AS (
  INSERT INTO public.app_growth_strategy_action_calendar (
    workspace_id,strategy_id,checkpoint_no,action_ids,planned_for,status,payload,created_by,created_at,updated_at
  )
  SELECT
    ac.workspace_id,
    ac.strategy_id,
    ac.checkpoint_no,
    '[]'::jsonb,
    date_trunc('day', now() + (ac.offset_days * interval '1 day')) + interval '10 hours',
    'scheduled',
    jsonb_build_object(
      'kind','adaptive_checkpoint',
      'generation_required',true,
      'requires_post_generation',true,
      'subject','Contrôle objectif · stratégie marketing',
      'prompt',
        'Tu es un expert digital marketing. Point de contrôle automatique d’un programme de croissance.' || E'\n\n' ||
        'Objectif : ' || ac.objective_label || E'\n' ||
        'Horizon réaliste : ' || ac.realistic_horizon_days::text || ' jours.' || E'\n' ||
        'Checkpoint : jour ' || ac.offset_days::text || ', progression attendue ' || ROUND(ac.expected_ratio*100)::text || '%.' || E'\n\n' ||
        'Mission : si l’objectif n’est pas assez avancé avec les signaux disponibles, générer des contenus correctifs et un angle plus fort. ' ||
        'Si la trajectoire semble correcte, générer des contenus d’amplification sans augmenter le volume inutilement.' || E'\n\n' ||
        'Action corrective si retard : ' || ac.if_behind || E'\n' ||
        'Action si trajectoire correcte : ' || ac.if_on_track || E'\n\n' ||
        'Produire 1 post prêt à publier, concret, avec accroche, preuve, CTA et mesure.',
      'theme',
        'Point de contrôle adaptatif : ' || ac.objective_label,
      'post_count',1,
      'commercial_objective',ac.objective_label,
      'content_domains',jsonb_build_array('Contrôle objectif','Optimisation marketing','Correction de trajectoire','Croissance'),
      'target_audience',jsonb_build_array(
        COALESCE(NULLIF(ac.strategy_data#>>'{target_analysis,primary_target}',''), NULLIF(ac.strategy_data#>>'{account_overview,target_audience}',''), 'audience du compte'),
        COALESCE(NULLIF(ac.strategy_data#>>'{target_analysis,persona}',''), NULLIF(ac.strategy_data#>>'{account_overview,positioning}',''), 'prospects qualifiés'),
        COALESCE(NULLIF(ac.strategy_data#>>'{target_analysis,awareness_level}',''), 'problem_aware')
      ),
      'preferred_formats',jsonb_build_array('post','reel','carrousel'),
      'language','français',
      'strategy_id',ac.strategy_id::text,
      'strategy_title',ac.strategy_title,
      'objective_label',ac.objective_label,
      'adaptive_checkpoint',jsonb_build_object(
        'checkpoint_no',ac.checkpoint_no,
        'offset_days',ac.offset_days,
        'expected_progress_ratio',ac.expected_ratio,
        'if_behind',ac.if_behind,
        'if_on_track',ac.if_on_track,
        'realistic_horizon_days',ac.realistic_horizon_days,
        'max_horizon_days',ac.max_horizon_days
      ),
      'strategy_data',ac.strategy_data,
      'network_snapshot',ac.network_snapshot
    ),
    ac.user_id,
    now(),
    now()
  FROM adaptive_checkpoint_source ac
  JOIN p ON p.action IN ('schedule_action_posts','bulk_schedule_action_posts','generate_action_posts','bulk_generate_action_posts')
  WHERE p.valid = true
    AND ac.user_id IS NOT NULL
    AND ac.workspace_id IS NOT NULL
    AND NOT EXISTS (
      SELECT 1
      FROM public.app_growth_strategy_action_calendar existing
      WHERE existing.strategy_id = ac.strategy_id
        AND existing.status IN ('scheduled','generating')
        AND existing.payload->>'kind' = 'adaptive_checkpoint'
        AND existing.payload#>>'{adaptive_checkpoint,checkpoint_no}' = ac.checkpoint_no::text
    )
  ON CONFLICT DO NOTHING
  RETURNING id AS calendar_id, strategy_id, workspace_id, action_ids, planned_for, payload
), scheduled_actions AS (
  UPDATE public.app_growth_strategy_actions a
  SET
    status = 'in_progress',
    kpi = jsonb_set(
      COALESCE(a.kpi,'{}'::jsonb),
      '{calendar}',
      jsonb_build_object(
        'status','scheduled',
        'mode','ai_auto',
        'planned_for',ci.planned_for,
        'generation_planned_for',ci.planned_for,
        'recommended_publish_for',ci.payload#>>'{ai_calendar,recommended_publish_for}',
        'generation_lead_days',COALESCE(
          CASE
            WHEN (ci.payload#>>'{ai_calendar,generation_lead_days}') ~ '^[0-9]{1,2}$'
            THEN (ci.payload#>>'{ai_calendar,generation_lead_days}')::int
            ELSE NULL
          END,
          0
        ),
        'calendar_id',ci.calendar_id::text,
        'schedule_kind',ci.payload#>>'{ai_calendar,schedule_kind}',
        'generation_required',
          lower(COALESCE(ci.payload->>'generation_required','false')) IN ('true','t','1','yes','on'),
        'requires_post_generation',
          lower(COALESCE(ci.payload->>'generation_required','false')) IN ('true','t','1','yes','on'),
        'reason',ci.payload#>>'{ai_calendar,reason}',
        'group',ci.payload#>>'{ai_calendar,group}'
      ),
      true
    ),
    updated_at = now()
  FROM calendar_inserted ci
  WHERE a.strategy_id = ci.strategy_id
    AND EXISTS (
      SELECT 1
      FROM jsonb_array_elements_text(ci.action_ids) AS ids(value)
      WHERE ids.value = a.id::text
    )
  RETURNING a.id::text AS id, a.status::text AS status
), updated_strategy AS (
  UPDATE public.app_growth_strategies s
  SET status = p.status, updated_at = now()
  FROM p
  WHERE p.valid = true
    AND p.action = 'set_strategy_status'
    AND p.status IN ('draft','active','paused','completed')
    AND s.id = p.strategy_id
    AND EXISTS (SELECT 1 FROM owned_strategy os WHERE os.id = s.id)
  RETURNING s.id::text AS id, s.status::text AS status
), archived_strategy AS (
  UPDATE public.app_growth_strategies s
  SET status = 'archived', updated_at = now()
  FROM p
  WHERE p.valid = true
    AND p.action = 'archive'
    AND s.id = p.strategy_id
    AND EXISTS (SELECT 1 FROM owned_strategy os WHERE os.id = s.id)
  RETURNING s.id::text AS id, s.status::text AS status
), obsolete_calendar_on_update AS (
  UPDATE public.app_growth_strategy_action_calendar c
  SET
    status = 'skipped',
    updated_at = now(),
    error_message = 'Planification obsolète après modification de la stratégie.'
  FROM p
  WHERE p.valid = true
    AND p.action = 'update_strategy'
    AND c.strategy_id = p.strategy_id
    AND COALESCE(c.status,'scheduled') = 'scheduled'
    AND c.planned_for > now()
    AND EXISTS (SELECT 1 FROM owned_strategy os WHERE os.id = p.strategy_id)
  RETURNING
    c.id,
    c.strategy_id,
    c.action_ids,
    c.payload
), obsolete_actions_on_update AS (
  UPDATE public.app_growth_strategy_actions a
  SET
    status = CASE WHEN COALESCE(a.status,'pending') = 'in_progress' THEN 'pending' ELSE COALESCE(a.status,'pending') END,
    kpi = jsonb_set(
      COALESCE(a.kpi,'{}'::jsonb),
      '{calendar}',
      COALESCE(a.kpi->'calendar','{}'::jsonb)
        || jsonb_build_object(
          'status','obsolete',
          'reason','Planification remplacée après modification de la stratégie.'
        ),
      true
    ),
    updated_at = now()
  FROM obsolete_calendar_on_update oc
  LEFT JOIN LATERAL (
    SELECT value
    FROM jsonb_array_elements_text(
      CASE WHEN jsonb_typeof(oc.action_ids)='array' THEN oc.action_ids ELSE '[]'::jsonb END
    ) AS x(value)
    LIMIT 1
  ) ids ON true
  WHERE a.strategy_id = oc.strategy_id
    AND a.id::text = COALESCE(oc.payload#>>'{action,id}', ids.value, '')
  RETURNING a.id
), updated_strategy_content AS (
  -- CALENDAR_CLEAN_BRANCH_MONOLITH_SQL_SYNTAX_FIX_2026_08_03
  UPDATE public.app_growth_strategies s
  SET
    title = COALESCE(NULLIF(p.update_title,''), s.title),
    objective_label = COALESCE(NULLIF(p.update_objective_label,''), s.objective_label),
    form_data = COALESCE(s.form_data,'{}'::jsonb)
      || jsonb_build_object(
        'title', COALESCE(NULLIF(p.update_title,''), s.title),
        'objective_label', COALESCE(NULLIF(p.update_objective_label,''), s.objective_label),
        'target_audience', COALESCE(NULLIF(p.update_primary_target,''), COALESCE(s.form_data->>'target_audience','')),
        'manual_notes', COALESCE(NULLIF(p.update_notes,''), COALESCE(s.form_data->>'manual_notes',''))
      ),
    strategy_data = COALESCE(s.strategy_data,'{}'::jsonb)
      || jsonb_build_object(
        'executive_summary', COALESCE(NULLIF(p.update_executive_summary,''), COALESCE(s.strategy_data->>'executive_summary','')),
        'manual_notes', COALESCE(NULLIF(p.update_notes,''), COALESCE(s.strategy_data->>'manual_notes','')),
        'target_analysis',
          COALESCE(s.strategy_data->'target_analysis','{}'::jsonb)
          || jsonb_build_object(
            'primary_target', COALESCE(NULLIF(p.update_primary_target,''), COALESCE(s.strategy_data#>>'{target_analysis,primary_target}',''))
          )
      ),
    updated_at = now()
  FROM p
  WHERE p.valid = true
    AND p.action = 'update_strategy'
    AND s.id = p.strategy_id
    AND EXISTS (SELECT 1 FROM owned_strategy os WHERE os.id = s.id)
  RETURNING s.id::text AS id, s.status::text AS status, s.title::text AS title
), /* HARD_DELETE_STRATEGY_RELATIONS_V66_2026_08_07 */
strategy_calendar_links AS MATERIALIZED (
  SELECT
    c.id AS calendar_id,
    c.request_id
  FROM public.app_growth_strategy_action_calendar c
  CROSS JOIN p
  WHERE p.valid = true
    AND p.action = 'delete_strategy'
    AND c.strategy_id = p.strategy_id
    AND EXISTS (SELECT 1 FROM owned_strategy os WHERE os.id = p.strategy_id)
),
strategy_request_links AS MATERIALIZED (
  SELECT DISTINCT scl.request_id
  FROM strategy_calendar_links scl
  WHERE scl.request_id IS NOT NULL
),
deleted_empty_strategy_requests AS (
  UPDATE public.post_requests pr
  SET
    deleted_at = COALESCE(pr.deleted_at,now()),
    last_error = CASE
      WHEN COALESCE(pr.last_error,'') <> '' THEN pr.last_error
      ELSE 'Demande supprimée avec la stratégie avant création de contenu.'
    END,
    form_data = (
      COALESCE(pr.form_data,'{}'::jsonb)
      - 'calendar_id'
      - 'strategy_id'
      - 'payload'
    ) || jsonb_build_object(
      'strategy_deleted',true,
      'strategy_deleted_at',now()::text,
      'strategy_cleanup','empty_request_removed'
    )
  FROM strategy_request_links srl
  WHERE pr.id = srl.request_id
    AND pr.deleted_at IS NULL
    AND NOT EXISTS (
      SELECT 1
      FROM public.post_ideas pi
      WHERE pi.request_id = pr.id
        AND pi.deleted_at IS NULL
    )
  RETURNING pr.id
),
detached_generated_strategy_requests AS (
  UPDATE public.post_requests pr
  SET
    form_data = (
      COALESCE(pr.form_data,'{}'::jsonb)
      - 'calendar_id'
      - 'strategy_id'
      - 'payload'
    ) || jsonb_build_object(
      'strategy_deleted',true,
      'strategy_deleted_at',now()::text,
      'strategy_cleanup','generated_content_preserved'
    )
  FROM strategy_request_links srl
  WHERE pr.id = srl.request_id
    AND pr.deleted_at IS NULL
    AND EXISTS (
      SELECT 1
      FROM public.post_ideas pi
      WHERE pi.request_id = pr.id
        AND pi.deleted_at IS NULL
    )
  RETURNING pr.id
),
deleted_strategy_calendar AS (
  DELETE FROM public.app_growth_strategy_action_calendar c
  USING p
  WHERE p.valid = true
    AND p.action = 'delete_strategy'
    AND c.strategy_id = p.strategy_id
    AND EXISTS (SELECT 1 FROM owned_strategy os WHERE os.id = p.strategy_id)
  RETURNING c.id
),
deleted_strategy_actions AS (
  DELETE FROM public.app_growth_strategy_actions a
  USING p
  WHERE p.valid = true
    AND p.action = 'delete_strategy'
    AND a.strategy_id = p.strategy_id
    AND EXISTS (SELECT 1 FROM owned_strategy os WHERE os.id = p.strategy_id)
  RETURNING a.id
),
deleted_strategy_versions AS (
  DELETE FROM public.app_growth_strategy_versions v
  USING p
  WHERE p.valid = true
    AND p.action = 'delete_strategy'
    AND v.strategy_id = p.strategy_id
    AND EXISTS (SELECT 1 FROM owned_strategy os WHERE os.id = p.strategy_id)
  RETURNING v.id
),
deleted_strategy AS (
  DELETE FROM public.app_growth_strategies s
  USING p
  WHERE p.valid = true
    AND p.action = 'delete_strategy'
    AND s.id = p.strategy_id
    AND EXISTS (SELECT 1 FROM owned_strategy os WHERE os.id = s.id)
  RETURNING s.id::text AS id, 'deleted'::text AS status
), calendar_task_updated AS (
  -- CALENDAR_TASK_UPDATE_CTE_PLACEMENT_FIX_2026_08_03
  -- CALENDAR_TASK_EDIT_DATETIME_SQL_2026_08_03
  -- CALENDAR_TASK_EDIT_SAVE_SQL_FIX_2026_08_03
  UPDATE public.app_growth_strategy_action_calendar c
  SET
    planned_for = p.calendar_planned_for,
    status = 'scheduled',
    request_id = NULL,
    triggered_at = NULL,
    error_message = NULL,
    payload = jsonb_set(
      jsonb_set(
        COALESCE(c.payload,'{}'::jsonb) || jsonb_build_object(
          'planned_for', p.calendar_planned_for::text,
          'manual_rescheduled', true,
          'rescheduled_at', now()::text
        ),
        '{ai_calendar,planned_for}',
        to_jsonb(p.calendar_planned_for::text),
        true
      ),
      '{planned_for}',
      to_jsonb(p.calendar_planned_for::text),
      true
    ),
    updated_at = now()
  FROM p
  WHERE p.valid = true
    AND p.action = 'update_calendar_task'
    AND p.calendar_id IS NOT NULL
    AND p.calendar_planned_for IS NOT NULL
    AND c.id = p.calendar_id
    AND c.strategy_id = p.strategy_id
    AND (
      p.workspace_id IS NULL
      OR c.workspace_id IS NULL
      OR c.workspace_id = p.workspace_id
    )
    AND EXISTS (SELECT 1 FROM owned_strategy os WHERE os.id = c.strategy_id)
    AND COALESCE(c.status,'scheduled') IN ('scheduled','failed','generating')
    AND NULLIF(COALESCE(c.request_id::text,''),'') IS NULL
  RETURNING c.id, c.planned_for, c.status
), /* CLEAR_PENDING_CALENDAR_TASKS_V39_2026_08_06 */
cleared_calendar_tasks AS (
  UPDATE public.app_growth_strategy_action_calendar c
  SET
    status = 'skipped',
    updated_at = now(),
    error_message = 'Planification effacée par l’utilisateur avant génération.'
  FROM p
  WHERE p.valid = true
    AND p.action = 'clear_pending_calendar_tasks'
    AND c.strategy_id = p.strategy_id
    AND (
      p.workspace_id IS NULL
      OR c.workspace_id IS NULL
      OR c.workspace_id = p.workspace_id
    )
    AND EXISTS (
      SELECT 1
      FROM owned_strategy os
      WHERE os.id = c.strategy_id
    )
    AND (
      (
        COALESCE(c.status,'scheduled') = 'scheduled'
        AND NULLIF(COALESCE(c.request_id::text,''),'') IS NULL
        AND c.triggered_at IS NULL
      )
      OR COALESCE(c.status,'scheduled') = 'failed'
    )
  RETURNING
    c.id,
    c.strategy_id,
    c.action_ids,
    c.payload
),
cleared_action_ids AS (
  SELECT DISTINCT action_id
  FROM (
    SELECT NULLIF(task.payload#>>'{action,id}','') AS action_id
    FROM cleared_calendar_tasks task

    UNION ALL

    SELECT value AS action_id
    FROM cleared_calendar_tasks task
    CROSS JOIN LATERAL jsonb_array_elements_text(
      CASE
        WHEN jsonb_typeof(task.action_ids) = 'array' THEN task.action_ids
        ELSE '[]'::jsonb
      END
    ) ids(value)
  ) source
  WHERE action_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
),
/* CLEAR_PENDING_POSTGRES_TARGET_ALIAS_FIX_V42_2026_08_06 */
cleared_actions AS (
  UPDATE public.app_growth_strategy_actions a
  SET
    status = CASE
      WHEN COALESCE(a.status,'pending') = 'in_progress' THEN 'pending'
      ELSE COALESCE(a.status,'pending')
    END,
    kpi = jsonb_set(
      COALESCE(a.kpi,'{}'::jsonb),
      '{calendar}',
      (
        COALESCE(a.kpi->'calendar','{}'::jsonb)
        - 'planned_for'
        - 'generation_planned_for'
        - 'recommended_publish_for'
        - 'calendar_id'
        - 'request_id'
      )
      || jsonb_build_object(
        'status','cleared',
        'reason','Planification effacée avant génération.',
        'cleared_at',now()::text
      ),
      true
    ),
    updated_at = now()
  FROM cleared_action_ids ids
  CROSS JOIN p
  WHERE p.valid = true
    AND p.action = 'clear_pending_calendar_tasks'
    AND p.strategy_id = a.strategy_id
    AND a.id::text = ids.action_id
  RETURNING a.id
) /* EDIT_DELETE_STRATEGY_SQL_2026_07_30 */, counters AS (
  SELECT
    (SELECT COUNT(*)::int FROM selected_action_ids) AS selected_count,
    (SELECT COUNT(*)::int FROM updated_bulk_actions) AS bulk_updated_count,
    ((SELECT COUNT(*)::int FROM calendar_inserted) + (SELECT COUNT(*)::int FROM checkpoint_inserted)) AS calendar_count,
    (SELECT COUNT(*)::int FROM checkpoint_inserted) AS checkpoint_count,
    (SELECT COUNT(*)::int FROM already_planned_actions) AS already_planned_count,
    (SELECT COUNT(*)::int FROM calendar_duplicate_cleanup) AS duplicate_skipped_count,
    (SELECT COUNT(*)::int FROM obsolete_calendar_on_update) AS obsolete_skipped_count,
    (SELECT COUNT(*)::int FROM calendar_task_updated) AS calendar_task_updated_count,
    (SELECT COUNT(*)::int FROM cleared_calendar_tasks) AS cleared_calendar_count,
    (SELECT COUNT(*)::int FROM cleared_actions) AS cleared_action_count,
    (SELECT COUNT(*)::int FROM deleted_strategy_calendar) AS deleted_strategy_calendar_count,
    (SELECT COUNT(*)::int FROM deleted_strategy_actions) AS deleted_strategy_action_count,
    (SELECT COUNT(*)::int FROM deleted_strategy_versions) AS deleted_strategy_version_count,
    (SELECT COUNT(*)::int FROM deleted_empty_strategy_requests) AS deleted_strategy_empty_request_count,
    (SELECT COUNT(*)::int FROM detached_generated_strategy_requests) AS preserved_strategy_request_count,
    (SELECT MIN(planned_for) FROM (SELECT planned_for FROM calendar_inserted UNION ALL SELECT planned_for FROM checkpoint_inserted) all_planned) AS first_planned_for,
    (SELECT MAX(planned_for) FROM (SELECT planned_for FROM calendar_inserted UNION ALL SELECT planned_for FROM checkpoint_inserted) all_planned) AS last_planned_for
), result AS (
  SELECT
    p.action,
    p.strategy_id::text AS strategy_id,
    p.action_id::text AS action_id,
    CASE
      WHEN p.valid = false THEN false
      WHEN p.action = 'set_action_status' THEN EXISTS(SELECT 1 FROM updated_action)
      WHEN p.action = 'bulk_set_action_status' THEN (SELECT bulk_updated_count FROM counters) > 0
      WHEN p.action IN ('schedule_action_posts','bulk_schedule_action_posts','generate_action_posts','bulk_generate_action_posts') THEN ((SELECT calendar_count FROM counters) > 0 OR (SELECT already_planned_count FROM counters) > 0)
      WHEN p.action = 'set_strategy_status' THEN EXISTS(SELECT 1 FROM updated_strategy)
      WHEN p.action = 'update_strategy' THEN EXISTS(SELECT 1 FROM updated_strategy_content)
      WHEN p.action = 'update_calendar_task' THEN EXISTS(SELECT 1 FROM calendar_task_updated)
      WHEN p.action = 'clear_pending_calendar_tasks' THEN (SELECT cleared_calendar_count FROM counters) > 0
      WHEN p.action = 'delete_strategy' THEN EXISTS(SELECT 1 FROM deleted_strategy)
      WHEN p.action = 'archive' THEN EXISTS(SELECT 1 FROM archived_strategy)
      ELSE false
    END AS success,
    COALESCE(
      (SELECT status FROM updated_action LIMIT 1),
      (SELECT status FROM updated_bulk_actions LIMIT 1),
      (SELECT status FROM scheduled_actions LIMIT 1),
      (SELECT status FROM updated_strategy LIMIT 1),
      (SELECT status FROM updated_strategy_content LIMIT 1),
      (SELECT status FROM calendar_task_updated LIMIT 1),
      (SELECT 'cleared' FROM cleared_calendar_tasks LIMIT 1),
      (SELECT status FROM deleted_strategy LIMIT 1),
      (SELECT status FROM archived_strategy LIMIT 1),
      ''
    ) AS status,
    COALESCE((SELECT selected_count FROM counters),0)::int AS selected_count,
    COALESCE((SELECT bulk_updated_count FROM counters),0)::int AS updated_count,
    COALESCE((SELECT calendar_count FROM counters),0)::int AS calendar_count,
    COALESCE((SELECT checkpoint_count FROM counters),0)::int AS checkpoint_count,
    COALESCE((SELECT already_planned_count FROM counters),0)::int AS already_planned_count,
    COALESCE((SELECT duplicate_skipped_count FROM counters),0)::int AS duplicate_skipped_count,
    COALESCE((SELECT obsolete_skipped_count FROM counters),0)::int AS obsolete_skipped_count,
    COALESCE((SELECT calendar_task_updated_count FROM counters),0)::int AS calendar_task_updated_count,
    COALESCE((SELECT cleared_calendar_count FROM counters),0)::int AS cleared_calendar_count,
    COALESCE((SELECT cleared_action_count FROM counters),0)::int AS cleared_action_count,
    COALESCE((SELECT deleted_strategy_calendar_count FROM counters),0)::int AS deleted_strategy_calendar_count,
    COALESCE((SELECT deleted_strategy_action_count FROM counters),0)::int AS deleted_strategy_action_count,
    COALESCE((SELECT deleted_strategy_version_count FROM counters),0)::int AS deleted_strategy_version_count,
    COALESCE((SELECT deleted_strategy_empty_request_count FROM counters),0)::int AS deleted_strategy_empty_request_count,
    COALESCE((SELECT preserved_strategy_request_count FROM counters),0)::int AS preserved_strategy_request_count,
    COALESCE((SELECT planned_for::text FROM calendar_task_updated LIMIT 1), COALESCE((SELECT first_planned_for::text FROM counters),'')) AS first_planned_for,
    jsonb_build_object('action', p.action, 'calendar_id', COALESCE(p.calendar_id::text,''), 'planned_for', COALESCE(p.calendar_planned_for::text,'')) AS calendar_task_update_debug,
    COALESCE((SELECT last_planned_for::text FROM counters),'') AS last_planned_for,
    CASE
      WHEN p.valid = false THEN COALESCE(NULLIF(p.prepare_error,''),'Requête action invalide.')
      WHEN NOT EXISTS(SELECT 1 FROM owned_strategy) THEN 'Stratégie introuvable ou non autorisée.'
      WHEN p.action = 'set_action_status' AND NOT EXISTS(SELECT 1 FROM updated_action) THEN 'Action introuvable pour cette stratégie.'
      WHEN p.action = 'bulk_set_action_status' AND (SELECT selected_count FROM counters)=0 THEN 'Aucune action sélectionnée.'
      WHEN p.action = 'bulk_set_action_status' AND (SELECT bulk_updated_count FROM counters)=0 THEN 'Aucune action sélectionnée n’est reliée à cette stratégie.'
      WHEN p.action IN ('schedule_action_posts','bulk_schedule_action_posts','generate_action_posts','bulk_generate_action_posts') AND (SELECT selected_count FROM counters)=0 THEN 'Aucune action sélectionnée.'
      WHEN p.action IN ('schedule_action_posts','bulk_schedule_action_posts','generate_action_posts','bulk_generate_action_posts')
        AND (SELECT calendar_count FROM counters)=0
        AND (SELECT already_planned_count FROM counters)>0
        THEN 'Action déjà planifiée. Aucun doublon créé.'
      WHEN p.action IN ('schedule_action_posts','bulk_schedule_action_posts','generate_action_posts','bulk_generate_action_posts') AND (SELECT calendar_count FROM counters)=0 THEN 'Aucune génération n’a pu être planifiée.'
      WHEN p.action = 'set_strategy_status' AND NOT EXISTS(SELECT 1 FROM updated_strategy) THEN 'Statut de stratégie non mis à jour.'
      WHEN p.action = 'update_strategy' AND NOT EXISTS(SELECT 1 FROM updated_strategy_content) THEN 'Modification non effectuée.'
      WHEN p.action = 'update_calendar_task' AND p.calendar_planned_for IS NULL THEN 'Date ou heure de tâche invalide.'
      WHEN p.action = 'update_calendar_task' AND NOT EXISTS(SELECT 1 FROM calendar_task_updated) THEN 'Tâche calendrier introuvable, déjà générée ou non modifiable.'
      WHEN p.action = 'clear_pending_calendar_tasks' AND (SELECT cleared_calendar_count FROM counters)=0 THEN 'Aucune tâche planifiée non générée à effacer.'
      WHEN p.action = 'delete_strategy' AND NOT EXISTS(SELECT 1 FROM deleted_strategy) THEN 'Suppression non effectuée.'
      WHEN p.action = 'archive' AND NOT EXISTS(SELECT 1 FROM archived_strategy) THEN 'Archivage non effectué.'
      WHEN p.action = 'set_action_status' THEN 'Action mise à jour.'
      WHEN p.action = 'bulk_set_action_status' THEN (SELECT bulk_updated_count FROM counters)::text || ' action(s) mise(s) à jour.'
      WHEN p.action IN ('schedule_action_posts','bulk_schedule_action_posts','generate_action_posts','bulk_generate_action_posts') THEN
        CASE
          WHEN (SELECT already_planned_count FROM counters)>0 AND (SELECT calendar_count FROM counters)>0
            THEN (SELECT calendar_count FROM counters)::text || ' nouvelle(s) génération(s) planifiée(s). ' || (SELECT already_planned_count FROM counters)::text || ' action(s) déjà planifiée(s) ignorée(s).'
          WHEN (SELECT already_planned_count FROM counters)>0 AND (SELECT calendar_count FROM counters)=0
            THEN 'Action déjà planifiée. Aucun doublon créé.'
          ELSE (SELECT calendar_count FROM counters)::text || ' génération(s) et point(s) de contrôle adaptatif planifié(s) automatiquement par l’IA.'
        END
      WHEN p.action = 'set_strategy_status' THEN 'Statut de stratégie mis à jour.'
      WHEN p.action = 'update_strategy' THEN 'Stratégie modifiée.'
      WHEN p.action = 'update_calendar_task' THEN 'Tâche calendrier replanifiée.'
      WHEN p.action = 'clear_pending_calendar_tasks' THEN
        (SELECT cleared_calendar_count FROM counters)::text
        || ' tâche(s) planifiée(s) non générée(s) effacée(s).'
      WHEN p.action = 'delete_strategy' THEN
        'Stratégie et relations liées supprimées : '
        || (SELECT deleted_strategy_action_count FROM counters)::text || ' action(s), '
        || (SELECT deleted_strategy_calendar_count FROM counters)::text || ' tâche(s) calendrier, '
        || (SELECT deleted_strategy_version_count FROM counters)::text || ' version(s). '
        || (SELECT preserved_strategy_request_count FROM counters)::text || ' sujet(s) déjà créé(s) conservé(s).'
      WHEN p.action = 'archive' THEN 'Stratégie archivée.'
      ELSE 'Action non prise en charge.'
    END AS message
  FROM p
)
SELECT *
FROM result;
