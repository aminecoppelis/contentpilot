/* VALIDATION_EMAIL_IMMEDIATE_SEED_V1
   Crée/réactive une ligne de notification pour chaque membre actif du workspace. */
WITH input AS (
  SELECT CASE
    WHEN COALESCE($1::text,'') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    THEN $1::uuid ELSE NULL END AS idea_id
)
INSERT INTO public.app_post_validation_email_reminders (
  idea_id,request_id,workspace_id,user_id,recipient_email,recipient_name,
  first_detected_at,next_send_at,sent_count,lease_until,lease_token,resolved_at,updated_at
)
SELECT DISTINCT
  pi.id, pi.request_id, pi.workspace_id, u.id, lower(BTRIM(u.email)),
  COALESCE(NULLIF(BTRIM(u.first_name),''),NULLIF(BTRIM(split_part(COALESCE(u.full_name,''),' ',1)),''),NULLIF(BTRIM(u.email),'')),
  now(), now(), 0, NULL, NULL, NULL, now()
FROM input i
JOIN public.post_ideas pi ON pi.id=i.idea_id AND pi.deleted_at IS NULL
JOIN public.post_requests pr ON pr.id=pi.request_id AND pr.deleted_at IS NULL
JOIN public.workspace_members wm ON wm.workspace_id=pi.workspace_id AND wm.status='active'
JOIN public.app_users u ON u.id=wm.user_id AND u.is_active=true AND u.deleted_at IS NULL
WHERE i.idea_id IS NOT NULL
  AND lower(COALESCE(pi.status,''))='ready_for_review'
  AND lower(COALESCE(pr.status,''))='ready_for_review'
  AND COALESCE(NULLIF(BTRIM(u.email),''),'')<>''
  AND EXISTS (
    SELECT 1 FROM public.post_versions pv
    WHERE pv.idea_id=pi.id AND COALESCE(NULLIF(BTRIM(pv.post_text),''),'')<>''
  )
ON CONFLICT (idea_id,user_id) DO UPDATE SET
  request_id=EXCLUDED.request_id,
  workspace_id=EXCLUDED.workspace_id,
  recipient_email=EXCLUDED.recipient_email,
  recipient_name=EXCLUDED.recipient_name,
  sent_count=CASE WHEN public.app_post_validation_email_reminders.resolved_at IS NOT NULL THEN 0 ELSE public.app_post_validation_email_reminders.sent_count END,
  last_sent_at=CASE WHEN public.app_post_validation_email_reminders.resolved_at IS NOT NULL THEN NULL ELSE public.app_post_validation_email_reminders.last_sent_at END,
  next_send_at=CASE WHEN public.app_post_validation_email_reminders.resolved_at IS NOT NULL THEN now() ELSE public.app_post_validation_email_reminders.next_send_at END,
  lease_until=CASE WHEN public.app_post_validation_email_reminders.resolved_at IS NOT NULL THEN NULL ELSE public.app_post_validation_email_reminders.lease_until END,
  lease_token=CASE WHEN public.app_post_validation_email_reminders.resolved_at IS NOT NULL THEN NULL ELSE public.app_post_validation_email_reminders.lease_token END,
  resolved_at=NULL,
  updated_at=now();
