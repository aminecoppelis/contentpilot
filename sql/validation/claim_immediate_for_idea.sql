/* VALIDATION_EMAIL_IMMEDIATE_AFTER_GENERATION_V1
   Réclame l'envoi initial après seed_immediate_for_idea.sql.
   Un email = 1 idée ready_for_review + 1 membre actif du workspace.
   Après confirmation, confirm_sent.sql programme le prochain rappel à +2h. */
WITH input AS (
  SELECT CASE
    WHEN COALESCE($1::text,'') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    THEN $1::uuid ELSE NULL END AS idea_id
), claimable AS MATERIALIZED (
  SELECT r.idea_id,r.user_id
  FROM public.app_post_validation_email_reminders r
  CROSS JOIN input i
  WHERE i.idea_id IS NOT NULL
    AND r.idea_id=i.idea_id
    AND r.resolved_at IS NULL
    AND COALESCE(r.sent_count,0)=0
    AND r.next_send_at<=now()
    AND (r.lease_until IS NULL OR r.lease_until<now())
    AND EXISTS (
      SELECT 1
      FROM public.post_ideas pi
      JOIN public.post_requests pr ON pr.id=pi.request_id AND pr.deleted_at IS NULL
      JOIN public.workspace_members wm ON wm.workspace_id=pi.workspace_id AND wm.user_id=r.user_id AND wm.status='active'
      JOIN public.app_users u ON u.id=wm.user_id AND u.is_active=true AND u.deleted_at IS NULL
      WHERE pi.id=r.idea_id
        AND pi.deleted_at IS NULL
        AND lower(COALESCE(pi.status,''))='ready_for_review'
        AND lower(COALESCE(pr.status,''))='ready_for_review'
        AND COALESCE(NULLIF(BTRIM(u.email),''),'')<>''
        AND EXISTS (
          SELECT 1 FROM public.post_versions pv
          WHERE pv.idea_id=pi.id AND COALESCE(NULLIF(BTRIM(pv.post_text),''),'')<>''
        )
    )
  ORDER BY r.first_detected_at,r.user_id
  FOR UPDATE OF r SKIP LOCKED
), claimed AS (
  UPDATE public.app_post_validation_email_reminders r
  SET lease_until=now()+interval '20 minutes',
      lease_token=md5(r.idea_id::text||':'||r.user_id::text||':'||clock_timestamp()::text||':'||random()::text),
      updated_at=now()
  FROM claimable c
  WHERE r.idea_id=c.idea_id AND r.user_id=c.user_id
  RETURNING r.*
)
SELECT
  c.idea_id::text AS idea_id,
  COALESCE(c.request_id::text,'') AS request_id,
  c.workspace_id::text AS workspace_id,
  c.user_id::text AS user_id,
  c.recipient_email AS email,
  COALESCE(NULLIF(c.recipient_name,''),'') AS first_name,
  COALESCE(NULLIF(w.name,''),'Workspace') AS workspace_name,
  COALESCE(NULLIF(pi.title,''),NULLIF(pr.subject,''),NULLIF(pr.title,''),'Post à valider') AS idea_title,
  COALESCE(NULLIF(pr.subject,''),NULLIF(pr.title,''),NULLIF(pi.title,''),'Sujet généré') AS request_subject,
  LEFT(COALESCE(NULLIF(BTRIM(pv.post_text),''),''),800) AS post_excerpt,
  1::int AS reminder_number,
  c.lease_token,
  ('https://socialnetwork.coppelis.com/app/posts/view?request_id='||pr.id::text||'&idea_id='||pi.id::text) AS validation_url
FROM claimed c
JOIN public.post_ideas pi ON pi.id=c.idea_id AND pi.deleted_at IS NULL
JOIN public.post_requests pr ON pr.id=pi.request_id AND pr.deleted_at IS NULL
LEFT JOIN public.workspaces w ON w.id=c.workspace_id
LEFT JOIN LATERAL (
  SELECT pv2.post_text
  FROM public.post_versions pv2
  WHERE pv2.idea_id=pi.id AND COALESCE(NULLIF(BTRIM(pv2.post_text),''),'')<>''
  ORDER BY COALESCE(pv2.is_current,false) DESC,pv2.version_number DESC
  LIMIT 1
) pv ON true
WHERE lower(COALESCE(pi.status,''))='ready_for_review'
  AND lower(COALESCE(pr.status,''))='ready_for_review'
ORDER BY c.user_id;
