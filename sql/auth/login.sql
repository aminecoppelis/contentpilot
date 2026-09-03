-- Port exact de "AUTH - BDD Vérifier Login" (Cahier technique, Annexe B.2)
-- Params: $1 email, $2 password, $3 redirect, $4 anti_bot_ok, $5 ip_address
WITH input AS (
  SELECT
    lower(trim($1::text)) AS email,
    $2::text AS password,
    $3::text AS redirect,
    COALESCE($4::boolean, false) AS anti_bot_ok,
    COALESCE(NULLIF(trim($5::text), ''), 'unknown') AS ip_address
), current_state AS (
  SELECT a.*
  FROM public.auth_login_attempts a
  JOIN input i ON a.email = i.email AND a.ip_address = i.ip_address
), state AS (
  SELECT
    i.*,
    COALESCE(cs.failed_attempts, 0) AS current_failed_attempts,
    COALESCE(cs.lock_level, 0) AS current_lock_level,
    cs.locked_until,
    (cs.locked_until IS NOT NULL AND cs.locked_until > now()) AS is_locked
  FROM input i
  LEFT JOIN current_state cs ON true
), matched_user AS (
  SELECT
    u.id::text AS user_id, u.email,
    COALESCE(u.first_name, split_part(COALESCE(u.full_name, ''), ' ', 1), '') AS first_name,
    COALESCE(u.last_name, trim(regexp_replace(COALESCE(u.full_name, ''), '^\S+\s*', '')), '') AS last_name,
    COALESCE(u.full_name, trim(concat_ws(' ', u.first_name, u.last_name)), '') AS full_name,
    COALESCE(u.role, 'user') AS role
  FROM state s
  JOIN public.app_users u ON lower(u.email) = s.email
  WHERE s.anti_bot_ok = true
    AND s.is_locked = false
    AND u.is_active = true
    AND u.deleted_at IS NULL
    AND u.password_hash = crypt(s.password, u.password_hash)
  LIMIT 1
), reset_after_success AS (
  DELETE FROM public.auth_login_attempts a
  USING state s
  WHERE EXISTS (SELECT 1 FROM matched_user) AND a.email = s.email
  RETURNING 1
), failure_result AS (
  INSERT INTO public.auth_login_attempts AS attempts (
    email, ip_address, failed_attempts, lock_level, locked_until,
    first_failed_at, last_failed_at, updated_at
  )
  SELECT s.email, s.ip_address, 1, 0, NULL, now(), now(), now()
  FROM state s
  WHERE s.anti_bot_ok = true AND s.is_locked = false AND NOT EXISTS (SELECT 1 FROM matched_user)
  ON CONFLICT (email, ip_address) DO UPDATE
  SET
    failed_attempts = CASE WHEN attempts.failed_attempts + 1 >= 3 THEN 0 ELSE attempts.failed_attempts + 1 END,
    lock_level = CASE WHEN attempts.failed_attempts + 1 >= 3 THEN attempts.lock_level + 1 ELSE attempts.lock_level END,
    locked_until = CASE
      WHEN attempts.failed_attempts + 1 >= 3 THEN
        now() + make_interval(mins => CASE attempts.lock_level + 1
          WHEN 1 THEN 1 WHEN 2 THEN 5 WHEN 3 THEN 15 WHEN 4 THEN 30 ELSE 60 END)
      ELSE NULL
    END,
    first_failed_at = COALESCE(attempts.first_failed_at, now()),
    last_failed_at = now(),
    updated_at = now()
  RETURNING failed_attempts, lock_level, locked_until
), cleanup AS (
  DELETE FROM public.auth_login_attempts
  WHERE updated_at < now() - interval '90 days' AND NOT EXISTS (SELECT 1 FROM matched_user)
  RETURNING 1
)
SELECT
  EXISTS (SELECT 1 FROM matched_user) AS login_ok,
  NOT s.anti_bot_ok AS anti_bot_error,
  s.is_locked AS was_locked,
  CASE
    WHEN s.is_locked THEN GREATEST(1, ceil(extract(epoch FROM (s.locked_until - now())))::int)
    WHEN fr.locked_until IS NOT NULL AND fr.locked_until > now()
      THEN GREATEST(1, ceil(extract(epoch FROM (fr.locked_until - now())))::int)
    ELSE 0
  END AS retry_after_seconds,
  CASE WHEN s.is_locked THEN s.current_lock_level ELSE COALESCE(fr.lock_level, s.current_lock_level) END AS lock_level,
  CASE
    WHEN s.is_locked THEN 0
    WHEN fr.locked_until IS NOT NULL AND fr.locked_until > now() THEN 0
    WHEN s.anti_bot_ok = true AND NOT EXISTS (SELECT 1 FROM matched_user)
      THEN GREATEST(0, 3 - COALESCE(fr.failed_attempts, 0))
    ELSE 3
  END AS attempts_remaining,
  s.redirect,
  s.ip_address AS remote_ip,
  mu.user_id, mu.email, mu.first_name, mu.last_name, mu.full_name, mu.role
FROM state s
LEFT JOIN failure_result fr ON true
LEFT JOIN matched_user mu ON true
LIMIT 1;
