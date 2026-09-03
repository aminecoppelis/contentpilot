/* VALIDATION_EMAIL_CONFIRM_V68_2026_08_07 — port verbatim.
   Un email réussi repousse le prochain rappel de 2 heures.
   Params: $1 idea_id, $2 user_id, $3 lease_token, $4 recipient_email */
/* VALIDATION_EMAIL_CONFIRM_V68_2026_08_07
   Un email réussi repousse le prochain rappel de 2 heures.
*/
WITH input AS (
  SELECT
    CASE WHEN COALESCE($1::text,'') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
      THEN $1::uuid ELSE NULL END AS idea_id,
    CASE WHEN COALESCE($2::text,'') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
      THEN $2::uuid ELSE NULL END AS user_id,
    LEFT(COALESCE(NULLIF($3::text,''),''),200) AS lease_token,
    LEFT(COALESCE(NULLIF($4::text,''),''),500) AS recipient
),
confirmed AS (
  UPDATE public.app_post_validation_email_reminders r
  SET
    last_sent_at=now(),
    next_send_at=now()+interval '2 hours',
    sent_count=COALESCE(r.sent_count,0)+1,
    lease_until=NULL,
    lease_token=NULL,
    recipient_email=COALESCE(NULLIF(i.recipient,''),r.recipient_email),
    updated_at=now()
  FROM input i
  WHERE i.idea_id IS NOT NULL
    AND i.user_id IS NOT NULL
    AND i.lease_token<>''
    AND r.idea_id=i.idea_id
    AND r.user_id=i.user_id
    AND r.lease_token=i.lease_token
  RETURNING r.idea_id,r.user_id,r.sent_count,r.last_sent_at,r.next_send_at
)
SELECT
  COALESCE(idea_id::text,'') AS idea_id,
  COALESCE(user_id::text,'') AS user_id,
  COALESCE(sent_count,0)::int AS sent_count,
  COALESCE(last_sent_at::text,'') AS last_sent_at,
  COALESCE(next_send_at::text,'') AS next_send_at,
  true AS reminder_confirmed
FROM confirmed;