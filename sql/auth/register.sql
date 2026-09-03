-- Port exact de "AUTH - BDD Créer utilisateur" (Cahier technique, Annexe B.3)
-- Params: $1 email, $2 first_name, $3 last_name, $4 full_name, $5 password
WITH raw_token AS (
  SELECT encode(gen_random_bytes(32), 'hex') AS token
), new_user AS (
  INSERT INTO public.app_users(email, first_name, last_name, full_name, password_hash, is_active, activation_sent_at)
  VALUES (
    lower($1::text),
    NULLIF($2::text, ''),
    NULLIF($3::text, ''),
    NULLIF($4::text, ''),
    crypt($5::text, gen_salt('bf', 10)),
    false,
    now()
  )
  ON CONFLICT (email) DO NOTHING
  RETURNING
    id, email,
    COALESCE(first_name, '') AS first_name,
    COALESCE(last_name, '') AS last_name,
    COALESCE(full_name, trim(concat_ws(' ', first_name, last_name)), '') AS full_name
), activation AS (
  INSERT INTO public.account_activation_tokens(user_id, token_hash, expires_at)
  SELECT new_user.id, encode(digest(raw_token.token, 'sha256'), 'hex'), now() + interval '24 hours'
  FROM new_user, raw_token
  RETURNING user_id
), personal_workspace AS (
  -- Création du workspace personnel (comportement documenté, Cahier technique §4.4,
  -- absent du nœud SQL original isolé mais nécessaire au flux complet)
  INSERT INTO public.workspaces (name, slug, owner_user_id, is_personal, system_key)
  SELECT
    'Espace personnel', NULL, new_user.id, true, NULL
  FROM new_user
  RETURNING id, owner_user_id
), personal_member AS (
  INSERT INTO public.workspace_members (workspace_id, user_id, role, status, invited_by)
  SELECT personal_workspace.id, personal_workspace.owner_user_id, 'owner', 'active', NULL
  FROM personal_workspace
  RETURNING workspace_id
)
SELECT
  new_user.id::text AS user_id,
  new_user.email,
  new_user.first_name,
  new_user.last_name,
  new_user.full_name,
  raw_token.token AS activation_token
FROM new_user, raw_token;
