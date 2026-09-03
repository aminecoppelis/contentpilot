-- Port exact de la logique de "AUTH - Lire session" (Cahier technique, Annexe B.4)
-- Params: $1 session_hash (sha256 du cookie), $2 fallback_session_id (uuid|null),
--         $3 fallback_request_token
WITH input AS (
  SELECT
    $1::text AS session_hash,
    NULLIF($2::text,'')::uuid AS fallback_session_id,
    $3::text AS fallback_request_token
), matched AS (
  SELECT
    u.id, u.email, u.first_name, u.last_name, u.full_name, u.role, u.timezone, u.last_workspace_id,
    s.id AS session_id, s.session_token_hash
  FROM input
  LEFT JOIN public.auth_sessions s
    ON (
      (input.session_hash <> '' AND s.session_token_hash = input.session_hash)
      OR (
        input.fallback_session_id IS NOT NULL
        AND s.id = input.fallback_session_id
        AND input.fallback_request_token <> ''
        AND encode(digest(s.id::text || ':' || s.session_token_hash, 'sha256'), 'hex') = input.fallback_request_token
      )
    )
   AND s.revoked_at IS NULL
   AND s.expires_at > now()
  LEFT JOIN public.app_users u
    ON u.id = s.user_id AND u.is_active = true AND u.deleted_at IS NULL
  LIMIT 1
)
SELECT
  m.id::text AS user_id, m.email, m.first_name, m.last_name, m.full_name,
  COALESCE(m.role,'user') AS role,
  COALESCE(NULLIF(m.timezone,''),'Europe/Paris') AS timezone,
  m.session_id::text AS session_id,
  CASE WHEN m.session_id IS NULL THEN ''
       ELSE encode(digest(m.session_id::text || ':' || m.session_token_hash, 'sha256'), 'hex')
  END AS request_auth_token,
  COALESCE(active_ws.workspace_id::text,'') AS active_workspace_id,
  COALESCE(active_ws.workspace_name,'') AS active_workspace_name,
  COALESCE(active_ws.workspace_role,'') AS active_workspace_role,
  COALESCE(workspace_list.workspaces,'[]'::jsonb) AS workspaces
FROM matched m
LEFT JOIN LATERAL (
  SELECT w.id AS workspace_id, w.name AS workspace_name,
    CASE WHEN lower(COALESCE(m.role,'user')) = 'admin' THEN 'super_admin' ELSE wm.role END AS workspace_role
  FROM public.workspaces w
  LEFT JOIN public.workspace_members wm
    ON wm.workspace_id = w.id AND wm.user_id = m.id AND wm.status = 'active'
  WHERE w.status = 'active'
    AND (lower(COALESCE(m.role,'user')) = 'admin' OR wm.user_id IS NOT NULL)
  ORDER BY
    (w.id = m.last_workspace_id) DESC,
    (w.is_personal = true AND w.owner_user_id = m.id) DESC,
    w.is_personal ASC, w.created_at ASC
  LIMIT 1
) active_ws ON true
LEFT JOIN LATERAL (
  SELECT jsonb_agg(
    jsonb_build_object(
      'id', w.id::text, 'name', w.name,
      'role', CASE WHEN lower(COALESCE(m.role,'user')) = 'admin' THEN 'super_admin' ELSE wm.role END,
      'is_personal', w.is_personal,
      'is_active', (w.id = active_ws.workspace_id),
      'is_super_admin_access', (lower(COALESCE(m.role,'user')) = 'admin'),
      'owner_name', COALESCE(NULLIF(owner.full_name,''), NULLIF(btrim(concat_ws(' ',owner.first_name,owner.last_name)),''), ''),
      'owner_email', COALESCE(owner.email,'')
    ) ORDER BY
      (w.id = active_ws.workspace_id) DESC,
      (w.is_personal = true AND w.owner_user_id = m.id) DESC,
      w.is_personal ASC, lower(w.name)
  ) AS workspaces
  FROM public.workspaces w
  LEFT JOIN public.workspace_members wm
    ON wm.workspace_id = w.id AND wm.user_id = m.id AND wm.status = 'active'
  LEFT JOIN public.app_users owner
    ON owner.id = w.owner_user_id
  WHERE w.status = 'active'
    AND (lower(COALESCE(m.role,'user')) = 'admin' OR wm.user_id IS NOT NULL)
) workspace_list ON true;
