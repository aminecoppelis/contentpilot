/* VALIDATION_EMAIL_REMINDERS_V68_2026_08_07 — port verbatim.
   Cron: */15 * * * *. Intervalle entre rappels réussis: 2 heures.
   Un rappel = 1 idée + 1 membre actif du workspace. */
/* VALIDATION_EMAIL_REMINDERS_V68_2026_08_07
   Scanner: */15 * * * *
   Intervalle entre emails réussis: 2 heures
   Un rappel = 1 idée + 1 membre actif du workspace.
*/
CREATE TABLE IF NOT EXISTS public.app_post_validation_email_reminders (
  idea_id uuid NOT NULL,
  request_id uuid,
  workspace_id uuid NOT NULL,
  user_id uuid NOT NULL,
  recipient_email text NOT NULL,
  recipient_name text,
  first_detected_at timestamptz NOT NULL DEFAULT now(),
  last_sent_at timestamptz,
  next_send_at timestamptz NOT NULL DEFAULT now(),
  sent_count integer NOT NULL DEFAULT 0,
  lease_until timestamptz,
  lease_token text,
  resolved_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (idea_id,user_id)
);

ALTER TABLE public.app_post_validation_email_reminders
  ADD COLUMN IF NOT EXISTS request_id uuid;
ALTER TABLE public.app_post_validation_email_reminders
  ADD COLUMN IF NOT EXISTS workspace_id uuid;
ALTER TABLE public.app_post_validation_email_reminders
  ADD COLUMN IF NOT EXISTS recipient_email text;
ALTER TABLE public.app_post_validation_email_reminders
  ADD COLUMN IF NOT EXISTS recipient_name text;
ALTER TABLE public.app_post_validation_email_reminders
  ADD COLUMN IF NOT EXISTS first_detected_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE public.app_post_validation_email_reminders
  ADD COLUMN IF NOT EXISTS last_sent_at timestamptz;
ALTER TABLE public.app_post_validation_email_reminders
  ADD COLUMN IF NOT EXISTS next_send_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE public.app_post_validation_email_reminders
  ADD COLUMN IF NOT EXISTS sent_count integer NOT NULL DEFAULT 0;
ALTER TABLE public.app_post_validation_email_reminders
  ADD COLUMN IF NOT EXISTS lease_until timestamptz;
ALTER TABLE public.app_post_validation_email_reminders
  ADD COLUMN IF NOT EXISTS lease_token text;
ALTER TABLE public.app_post_validation_email_reminders
  ADD COLUMN IF NOT EXISTS resolved_at timestamptz;
ALTER TABLE public.app_post_validation_email_reminders
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS app_post_validation_email_reminders_due_idx
  ON public.app_post_validation_email_reminders(next_send_at)
  WHERE resolved_at IS NULL;

CREATE INDEX IF NOT EXISTS app_post_validation_email_reminders_workspace_idx
  ON public.app_post_validation_email_reminders(workspace_id,resolved_at);

-- Arrêter les rappels dès que l'idée n'est plus à valider,
-- a été supprimée, le contenu n'existe plus ou le membre n'est plus actif.
UPDATE public.app_post_validation_email_reminders r
SET resolved_at=COALESCE(r.resolved_at,now()),
    lease_until=NULL,
    lease_token=NULL,
    updated_at=now()
WHERE r.resolved_at IS NULL
  AND (
    NOT EXISTS (
      SELECT 1
      FROM public.post_ideas pi
      JOIN public.post_requests pr
        ON pr.id=pi.request_id
       AND pr.deleted_at IS NULL
      WHERE pi.id=r.idea_id
        AND pi.deleted_at IS NULL
        AND lower(COALESCE(pi.status,'')) IN ('pending_review','ready_for_review')
        AND lower(COALESCE(pr.form_data->>'strategy_deleted','false')) NOT IN ('true','t','1','yes','on')
        AND EXISTS (
          SELECT 1
          FROM public.post_versions pv
          WHERE pv.idea_id=pi.id
            AND COALESCE(NULLIF(BTRIM(pv.post_text),''),'')<>''
        )
    )
    OR NOT EXISTS (
      SELECT 1
      FROM public.workspace_members wm
      JOIN public.app_users u
        ON u.id=wm.user_id
       AND u.is_active=true
       AND u.deleted_at IS NULL
       AND COALESCE(NULLIF(BTRIM(u.email),''),'')<>''
      WHERE wm.workspace_id=r.workspace_id
        AND wm.user_id=r.user_id
        AND wm.status='active'
    )
  );

-- Créer une ligne de rappel pour chaque membre actif du workspace.
INSERT INTO public.app_post_validation_email_reminders (
  idea_id,request_id,workspace_id,user_id,
  recipient_email,recipient_name,
  first_detected_at,next_send_at,sent_count,
  lease_until,lease_token,resolved_at,updated_at
)
SELECT DISTINCT
  pi.id,
  pi.request_id,
  pi.workspace_id,
  u.id,
  lower(BTRIM(u.email)),
  COALESCE(NULLIF(BTRIM(u.first_name),''),NULLIF(BTRIM(split_part(COALESCE(u.full_name,''),' ',1)),''),
           NULLIF(BTRIM(u.email),'')),
  now(),
  now(),
  0,
  NULL,
  NULL,
  NULL,
  now()
FROM public.post_ideas pi
JOIN public.post_requests pr
  ON pr.id=pi.request_id
 AND pr.deleted_at IS NULL
JOIN public.workspace_members wm
  ON wm.workspace_id=pi.workspace_id
 AND wm.status='active'
JOIN public.app_users u
  ON u.id=wm.user_id
 AND u.is_active=true
 AND u.deleted_at IS NULL
WHERE pi.deleted_at IS NULL
  AND lower(COALESCE(pi.status,'')) IN ('pending_review','ready_for_review')
  AND lower(COALESCE(pr.form_data->>'strategy_deleted','false')) NOT IN ('true','t','1','yes','on')
  AND COALESCE(NULLIF(BTRIM(u.email),''),'')<>''
  AND EXISTS (
    SELECT 1
    FROM public.post_versions pv
    WHERE pv.idea_id=pi.id
      AND COALESCE(NULLIF(BTRIM(pv.post_text),''),'')<>''
  )
ON CONFLICT (idea_id,user_id) DO UPDATE
SET
  request_id=EXCLUDED.request_id,
  workspace_id=EXCLUDED.workspace_id,
  recipient_email=EXCLUDED.recipient_email,
  recipient_name=EXCLUDED.recipient_name,
  sent_count=CASE
    WHEN public.app_post_validation_email_reminders.resolved_at IS NOT NULL THEN 0
    ELSE public.app_post_validation_email_reminders.sent_count
  END,
  last_sent_at=CASE
    WHEN public.app_post_validation_email_reminders.resolved_at IS NOT NULL THEN NULL
    ELSE public.app_post_validation_email_reminders.last_sent_at
  END,
  next_send_at=CASE
    WHEN public.app_post_validation_email_reminders.resolved_at IS NOT NULL THEN now()
    ELSE public.app_post_validation_email_reminders.next_send_at
  END,
  lease_until=CASE
    WHEN public.app_post_validation_email_reminders.resolved_at IS NOT NULL THEN NULL
    ELSE public.app_post_validation_email_reminders.lease_until
  END,
  lease_token=CASE
    WHEN public.app_post_validation_email_reminders.resolved_at IS NOT NULL THEN NULL
    ELSE public.app_post_validation_email_reminders.lease_token
  END,
  resolved_at=NULL,
  updated_at=now();

WITH claimable AS MATERIALIZED (
  SELECT r.idea_id,r.user_id
  FROM public.app_post_validation_email_reminders r
  WHERE r.resolved_at IS NULL
    AND r.next_send_at<=now()
    AND (r.lease_until IS NULL OR r.lease_until<now())
    AND EXISTS (
      SELECT 1
      FROM public.post_ideas pi
      JOIN public.post_requests pr
        ON pr.id=pi.request_id
       AND pr.deleted_at IS NULL
      JOIN public.workspace_members wm
        ON wm.workspace_id=pi.workspace_id
       AND wm.user_id=r.user_id
       AND wm.status='active'
      JOIN public.app_users u
        ON u.id=wm.user_id
       AND u.is_active=true
       AND u.deleted_at IS NULL
      WHERE pi.id=r.idea_id
        AND pi.deleted_at IS NULL
        AND lower(COALESCE(pi.status,'')) IN ('pending_review','ready_for_review')
        AND lower(COALESCE(pr.form_data->>'strategy_deleted','false')) NOT IN ('true','t','1','yes','on')
        AND COALESCE(NULLIF(BTRIM(u.email),''),'')<>''
        AND EXISTS (
          SELECT 1
          FROM public.post_versions pv
          WHERE pv.idea_id=pi.id
            AND COALESCE(NULLIF(BTRIM(pv.post_text),''),'')<>''
        )
    )
  ORDER BY r.next_send_at ASC,r.first_detected_at ASC,r.idea_id,r.user_id
  LIMIT 50
  FOR UPDATE OF r SKIP LOCKED
),
claimed AS (
  UPDATE public.app_post_validation_email_reminders r
  SET
    lease_until=now()+interval '20 minutes',
    lease_token=md5(
      r.idea_id::text||':'||r.user_id::text||':'||
      clock_timestamp()::text||':'||random()::text
    ),
    updated_at=now()
  FROM claimable c
  WHERE r.idea_id=c.idea_id
    AND r.user_id=c.user_id
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
  lower(COALESCE(pi.status,'')) AS idea_status,
  (c.sent_count+1)::int AS reminder_number,
  COALESCE(c.sent_count,0)::int AS previous_reminders_sent,
  COALESCE(c.last_sent_at::text,'') AS last_sent_at,
  c.first_detected_at::text AS first_detected_at,
  c.lease_token,
  '2 hours'::text AS reminder_interval,
  (
    'https://socialnetwork.coppelis.com/app/posts/view?request_id='
    ||pr.id::text
    ||'&idea_id='
    ||pi.id::text
  ) AS validation_url
FROM claimed c
JOIN public.post_ideas pi
  ON pi.id=c.idea_id
 AND pi.deleted_at IS NULL
JOIN public.post_requests pr
  ON pr.id=pi.request_id
 AND pr.deleted_at IS NULL
LEFT JOIN public.workspaces w
  ON w.id=c.workspace_id
LEFT JOIN LATERAL (
  SELECT pv2.post_text,pv2.title,pv2.version_number,pv2.is_current
  FROM public.post_versions pv2
  WHERE pv2.idea_id=pi.id
    AND COALESCE(NULLIF(BTRIM(pv2.post_text),''),'')<>''
  ORDER BY COALESCE(pv2.is_current,false) DESC,pv2.version_number DESC
  LIMIT 1
) pv ON true
ORDER BY c.next_send_at ASC,c.idea_id,c.user_id;