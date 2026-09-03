-- Activation de compte (Cahier technique §4.5) — Params: $1 token_hash
WITH tok AS (
  SELECT * FROM public.account_activation_tokens
  WHERE token_hash = $1::text AND used_at IS NULL AND expires_at > now()
  LIMIT 1
  FOR UPDATE
), activated AS (
  UPDATE public.app_users
  SET is_active = true,
      activated_at = COALESCE(activated_at, now())
  FROM tok
  WHERE app_users.id = tok.user_id
  RETURNING app_users.id::text AS user_id, app_users.email
), consumed AS (
  UPDATE public.account_activation_tokens
  SET used_at = now()
  FROM tok
  WHERE account_activation_tokens.id = tok.id
  RETURNING 1
)
SELECT
  EXISTS (SELECT 1 FROM activated) AS activated,
  COALESCE((SELECT user_id FROM activated LIMIT 1), '') AS user_id,
  COALESCE((SELECT email FROM activated LIMIT 1), '') AS email;
