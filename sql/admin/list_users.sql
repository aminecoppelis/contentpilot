-- Port verbatim de "AUTH - BDD Admin Users"
WITH auth_ctx AS (
  SELECT
    u.id::text AS user_id,
    u.email,
    COALESCE(u.first_name, '') AS first_name,
    COALESCE(u.last_name, '') AS last_name,
    COALESCE(u.full_name, trim(concat_ws(' ', u.first_name, u.last_name)), '') AS full_name,
    COALESCE(u.role, 'user') AS role,
    s.id::text AS session_id,
    encode(digest(s.id::text || ':' || s.session_token_hash, 'sha256'), 'hex') AS request_token,
    u.last_workspace_id
  FROM public.auth_sessions s
  JOIN public.app_users u ON u.id = s.user_id
  WHERE s.session_token_hash = $1::text
    AND s.revoked_at IS NULL
    AND s.expires_at > now()
    AND u.is_active = true
    AND u.deleted_at IS NULL
  LIMIT 1
), all_users AS (
  SELECT
    u.id::text AS id,
    u.email,
    COALESCE(u.first_name, '') AS first_name,
    COALESCE(u.last_name, '') AS last_name,
    COALESCE(u.full_name, trim(concat_ws(' ', u.first_name, u.last_name)), '') AS full_name,
    COALESCE(u.role, 'user') AS role,
    u.is_active,
    u.created_at,
    u.activated_at,
    u.last_login_at
  FROM public.app_users u
  WHERE u.deleted_at IS NULL
    AND EXISTS (SELECT 1 FROM auth_ctx WHERE lower(role) = 'admin')
), first_page AS (
  SELECT * FROM all_users ORDER BY created_at DESC LIMIT 20
), active_ws AS (
  SELECT
    w.id::text AS id,
    w.name,
    CASE WHEN lower(a.role)='admin' THEN 'super_admin' ELSE wm.role END AS role
  FROM auth_ctx a
  JOIN LATERAL (
    SELECT w0.*
    FROM public.workspaces w0
    LEFT JOIN public.workspace_members wm0
      ON wm0.workspace_id=w0.id
     AND wm0.user_id=a.user_id::uuid
     AND wm0.status='active'
    WHERE w0.status='active'
      AND (lower(a.role)='admin' OR wm0.user_id IS NOT NULL)
    ORDER BY
      (w0.id=a.last_workspace_id) DESC,
      (w0.is_personal=true AND w0.owner_user_id=a.user_id::uuid) DESC,
      w0.is_personal ASC,
      w0.created_at ASC
    LIMIT 1
  ) w ON true
  LEFT JOIN public.workspace_members wm
    ON wm.workspace_id=w.id
   AND wm.user_id=a.user_id::uuid
   AND wm.status='active'
), workspace_list AS (
  SELECT jsonb_agg(
    jsonb_build_object(
      'id',w.id::text,
      'name',w.name,
      'role',CASE WHEN lower(a.role)='admin' THEN 'super_admin' ELSE wm.role END,
      'is_personal',w.is_personal,
      'is_active',(w.id::text=COALESCE((SELECT id FROM active_ws),'')),
      'is_super_admin_access',(lower(a.role)='admin')
    ) ORDER BY
      (w.id::text=COALESCE((SELECT id FROM active_ws),'')) DESC,
      (w.is_personal=true AND w.owner_user_id=a.user_id::uuid) DESC,
      w.is_personal ASC,
      lower(w.name)
  ) AS workspaces
  FROM auth_ctx a
  JOIN public.workspaces w ON w.status='active'
  LEFT JOIN public.workspace_members wm
    ON wm.workspace_id=w.id
   AND wm.user_id=a.user_id::uuid
   AND wm.status='active'
  WHERE lower(a.role)='admin' OR wm.user_id IS NOT NULL
)
SELECT
  COALESCE((SELECT user_id FROM auth_ctx), '') AS current_user_id,
  COALESCE((SELECT email FROM auth_ctx), '') AS current_email,
  COALESCE((SELECT first_name FROM auth_ctx), '') AS current_first_name,
  COALESCE((SELECT last_name FROM auth_ctx), '') AS current_last_name,
  COALESCE((SELECT full_name FROM auth_ctx), '') AS current_full_name,
  COALESCE((SELECT role FROM auth_ctx), '') AS current_role,
  COALESCE((SELECT session_id FROM auth_ctx), '') AS current_session_id,
  COALESCE((SELECT request_token FROM auth_ctx), '') AS current_request_token,
  COALESCE((SELECT id FROM active_ws), '') AS active_workspace_id,
  COALESCE((SELECT name FROM active_ws), '') AS active_workspace_name,
  COALESCE((SELECT role FROM active_ws), '') AS active_workspace_role,
  COALESCE((SELECT workspaces FROM workspace_list), '[]'::jsonb) AS workspaces,
  EXISTS(SELECT 1 FROM auth_ctx WHERE lower(role) = 'admin') AS is_admin,
  COALESCE((SELECT jsonb_agg(to_jsonb(first_page) ORDER BY created_at DESC) FROM first_page), '[]'::jsonb) AS users,
  (SELECT COUNT(*)::int FROM all_users) AS total_users,
  ((SELECT COUNT(*) FROM all_users) > 20) AS users_has_more;