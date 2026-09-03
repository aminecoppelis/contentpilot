-- Port verbatim de "AUTH - BDD Admin User Action"
WITH input AS (
  SELECT
    $1::text AS session_hash,
    lower(trim($2::text)) AS requested_action,
    $3::uuid AS target_user_id,
    NULLIF(trim($4::text), '') AS first_name,
    NULLIF(trim($5::text), '') AS last_name,
    NULLIF(lower(trim($6::text)), '') AS email,
    NULLIF(lower(trim($7::text)), '') AS requested_role,
    NULLIF(trim($8::text), '')::uuid AS fallback_session_id,
    NULLIF(trim($9::text), '') AS fallback_request_token
), admin_ctx AS (
  SELECT u.id, u.role
  FROM input i
  JOIN public.auth_sessions s ON (
    (i.session_hash <> '' AND s.session_token_hash = i.session_hash)
    OR
    (
      i.fallback_session_id IS NOT NULL
      AND s.id = i.fallback_session_id
      AND i.fallback_request_token IS NOT NULL
      AND encode(digest(s.id::text || ':' || s.session_token_hash, 'sha256'), 'hex') = i.fallback_request_token
    )
  )
  JOIN public.app_users u ON u.id = s.user_id
  WHERE s.revoked_at IS NULL
    AND s.expires_at > now()
    AND u.is_active = true
    AND u.deleted_at IS NULL
    AND lower(COALESCE(u.role, 'user')) = 'admin'
  LIMIT 1
), target AS (
  SELECT u.*
  FROM public.app_users u
  JOIN input i ON u.id = i.target_user_id
  WHERE u.deleted_at IS NULL
  LIMIT 1
), checks AS (
  SELECT
    i.*,
    a.id AS admin_id,
    t.id AS existing_target_id,
    lower(COALESCE(t.role, 'user')) AS current_role,
    COALESCE(t.is_active, false) AS current_active,
    (a.id = t.id) AS is_self,
    EXISTS (
      SELECT 1
      FROM public.app_users duplicate
      WHERE duplicate.deleted_at IS NULL
        AND lower(duplicate.email) = i.email
        AND duplicate.id <> i.target_user_id
    ) AS email_taken,
    (
      SELECT count(*)
      FROM public.app_users admin_user
      WHERE admin_user.deleted_at IS NULL
        AND admin_user.is_active = true
        AND lower(COALESCE(admin_user.role, 'user')) = 'admin'
    ) AS active_admin_count
  FROM input i
  LEFT JOIN admin_ctx a ON true
  LEFT JOIN target t ON true
), decision AS (
  SELECT *,
    CASE
      WHEN session_hash = '' AND fallback_session_id IS NULL THEN 'Authentification absente de la requête.'
      WHEN admin_id IS NULL THEN 'Session invalide, expirée ou droits administrateur insuffisants.'
      WHEN requested_action NOT IN ('update', 'activate', 'deactivate', 'delete') THEN 'Action administrateur invalide.'
      WHEN existing_target_id IS NULL THEN 'Utilisateur introuvable ou déjà supprimé.'
      WHEN requested_action = 'update' AND (first_name IS NULL OR last_name IS NULL OR email IS NULL) THEN 'Prénom, nom et email sont obligatoires.'
      WHEN requested_action = 'update' AND email !~* '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$' THEN 'Adresse email invalide.'
      WHEN requested_action = 'update' AND requested_role IS NOT NULL AND requested_role NOT IN ('admin', 'user') THEN 'Rôle invalide.'
      WHEN requested_action = 'update' AND email_taken THEN 'Un autre compte utilise déjà cette adresse email.'
      WHEN requested_action = 'deactivate' AND is_self THEN 'Tu ne peux pas désactiver ton propre compte.'
      WHEN requested_action = 'delete' AND is_self THEN 'Tu ne peux pas supprimer ton propre compte.'
      WHEN requested_action = 'update' AND is_self AND current_role = 'admin' AND COALESCE(requested_role, current_role) <> 'admin' THEN 'Tu ne peux pas retirer ton propre rôle administrateur.'
      WHEN current_role = 'admin' AND active_admin_count <= 1 AND (
        requested_action IN ('deactivate', 'delete') OR
        (requested_action = 'update' AND COALESCE(requested_role, current_role) <> 'admin')
      ) THEN 'Au moins un administrateur actif doit être conservé.'
      ELSE NULL
    END AS error_message
  FROM checks
), updated AS (
  UPDATE public.app_users u
  SET
    first_name = d.first_name,
    last_name = d.last_name,
    full_name = trim(concat_ws(' ', d.first_name, d.last_name)),
    email = d.email,
    role = COALESCE(d.requested_role, u.role)
  FROM decision d
  WHERE u.id = d.target_user_id
    AND d.requested_action = 'update'
    AND d.error_message IS NULL
  RETURNING u.id, 'update'::text AS applied_action
), activated AS (
  UPDATE public.app_users u
  SET is_active = true,
      activated_at = COALESCE(u.activated_at, now())
  FROM decision d
  WHERE u.id = d.target_user_id
    AND d.requested_action = 'activate'
    AND d.error_message IS NULL
  RETURNING u.id, 'activate'::text AS applied_action
), deactivated AS (
  UPDATE public.app_users u
  SET is_active = false
  FROM decision d
  WHERE u.id = d.target_user_id
    AND d.requested_action = 'deactivate'
    AND d.error_message IS NULL
  RETURNING u.id, 'deactivate'::text AS applied_action
), deleted AS (
  UPDATE public.app_users u
  SET
    is_active = false,
    deleted_at = now(),
    role = 'user',
    first_name = 'Compte',
    last_name = 'supprimé',
    full_name = 'Compte supprimé',
    email = 'deleted+' || replace(u.id::text, '-', '') || '@invalid.local'
  FROM decision d
  WHERE u.id = d.target_user_id
    AND d.requested_action = 'delete'
    AND d.error_message IS NULL
  RETURNING u.id, 'delete'::text AS applied_action
), applied AS (
  SELECT * FROM updated
  UNION ALL SELECT * FROM activated
  UNION ALL SELECT * FROM deactivated
  UNION ALL SELECT * FROM deleted
), revoked AS (
  UPDATE public.auth_sessions s
  SET revoked_at = now()
  WHERE s.user_id = (SELECT target_user_id FROM decision)
    AND (SELECT error_message FROM decision) IS NULL
    AND (SELECT requested_action FROM decision) IN ('deactivate', 'delete')
  RETURNING s.id
)
SELECT
  ((SELECT error_message FROM decision) IS NULL AND EXISTS (SELECT 1 FROM applied)) AS success,
  COALESCE((SELECT error_message FROM decision), '') AS error_message,
  COALESCE((SELECT requested_action FROM decision), '') AS action,
  COALESCE((SELECT target_user_id::text FROM decision), '') AS user_id,
  CASE
    WHEN (SELECT error_message FROM decision) IS NOT NULL THEN (SELECT error_message FROM decision)
    WHEN NOT EXISTS (SELECT 1 FROM applied) THEN 'Aucune modification n’a été appliquée.'
    WHEN (SELECT requested_action FROM decision) = 'update' THEN 'Utilisateur modifié avec succès.'
    WHEN (SELECT requested_action FROM decision) = 'activate' THEN 'Compte activé avec succès.'
    WHEN (SELECT requested_action FROM decision) = 'deactivate' THEN 'Compte désactivé et sessions révoquées.'
    WHEN (SELECT requested_action FROM decision) = 'delete' THEN 'Compte supprimé et sessions révoquées.'
    ELSE 'Action effectuée.'
  END AS message;