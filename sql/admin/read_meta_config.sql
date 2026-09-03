-- Port verbatim de "BDD - Lire configuration Meta Admin"
WITH auth_ctx AS (
  SELECT
    u.id::text AS user_id,
    u.email,
    COALESCE(u.first_name,'') AS first_name,
    COALESCE(u.last_name,'') AS last_name,
    COALESCE(u.full_name,trim(concat_ws(' ',u.first_name,u.last_name)),u.email,'Compte') AS full_name,
    lower(COALESCE(u.role,'user')) AS role,
    s.id::text AS session_id,
    encode(digest(s.id::text || ':' || s.session_token_hash,'sha256'),'hex') AS request_token,
    u.last_workspace_id
  FROM public.auth_sessions s
  JOIN public.app_users u ON u.id=s.user_id
  WHERE s.session_token_hash=$1::text
    AND s.revoked_at IS NULL
    AND s.expires_at>now()
    AND u.is_active=true
    AND u.deleted_at IS NULL
  LIMIT 1
), cfg AS (

  SELECT
    provider,
    COALESCE(app_id,'') AS app_id,
    COALESCE(public_app_url,'') AS public_app_url,
    COALESCE(NULLIF(BTRIM(graph_version),''),'v25.0') AS graph_version,
    COALESCE(login_config_id,'') AS login_config_id,
    COALESCE(scopes,'') AS scopes,
    is_enabled,
    (NULLIF(BTRIM(app_secret),'') IS NOT NULL) AS has_app_secret,
    (NULLIF(BTRIM(token_encryption_key),'') IS NOT NULL) AS has_token_key,
    last_tested_at,
    last_test_success,
    COALESCE(last_test_message,'') AS last_test_message,
    updated_at
  FROM public.app_integration_settings
  WHERE provider IN ('meta_facebook','meta_instagram')
    AND EXISTS(SELECT 1 FROM auth_ctx WHERE role='admin')
), active_ws AS (
  SELECT
    w.id::text AS id,
    w.name,
    CASE WHEN a.role='admin' THEN 'super_admin' ELSE wm.role END AS role
  FROM auth_ctx a
  JOIN LATERAL (
    SELECT w0.*
    FROM public.workspaces w0
    LEFT JOIN public.workspace_members wm0
      ON wm0.workspace_id=w0.id
     AND wm0.user_id=a.user_id::uuid
     AND wm0.status='active'
    WHERE w0.status='active'
      AND (a.role='admin' OR wm0.user_id IS NOT NULL)
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
      'role',CASE WHEN a.role='admin' THEN 'super_admin' ELSE wm.role END,
      'is_personal',w.is_personal,
      'is_active',(w.id::text=COALESCE((SELECT id FROM active_ws),'')),
      'is_super_admin_access',(a.role='admin')
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
  WHERE a.role='admin' OR wm.user_id IS NOT NULL
)
SELECT
  COALESCE((SELECT user_id FROM auth_ctx),'') AS current_user_id,
  COALESCE((SELECT email FROM auth_ctx),'') AS current_email,
  COALESCE((SELECT first_name FROM auth_ctx),'') AS current_first_name,
  COALESCE((SELECT last_name FROM auth_ctx),'') AS current_last_name,
  COALESCE((SELECT full_name FROM auth_ctx),'') AS current_full_name,
  COALESCE((SELECT role FROM auth_ctx),'') AS current_role,
  COALESCE((SELECT session_id FROM auth_ctx),'') AS current_session_id,
  COALESCE((SELECT request_token FROM auth_ctx),'') AS current_request_token,
  COALESCE((SELECT id FROM active_ws),'') AS active_workspace_id,
  COALESCE((SELECT name FROM active_ws),'') AS active_workspace_name,
  COALESCE((SELECT role FROM active_ws),'') AS active_workspace_role,
  COALESCE((SELECT workspaces FROM workspace_list),'[]'::jsonb) AS workspaces,
  EXISTS(SELECT 1 FROM auth_ctx WHERE role='admin') AS is_admin,
  COALESCE((SELECT jsonb_agg(to_jsonb(cfg) ORDER BY provider) FROM cfg),'[]'::jsonb) AS configurations;