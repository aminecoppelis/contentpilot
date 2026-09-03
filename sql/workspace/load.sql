-- Port verbatim de "BDD - Charger Workspace"
-- Params: $1 user_id, $2 workspace_id
WITH p AS (
  SELECT NULLIF($1::text,'')::uuid AS user_id,NULLIF($2::text,'')::uuid AS workspace_id
), actor AS (
  SELECT p.*,lower(COALESCE(u.role,'user')) AS global_role
  FROM p
  JOIN public.app_users u ON u.id=p.user_id AND u.is_active=true AND u.deleted_at IS NULL
), allowed AS (
  SELECT
    w.id,w.name,w.slug,w.owner_user_id,w.is_personal,w.system_key,w.created_at,
    CASE WHEN a.global_role='admin' THEN 'super_admin' ELSE wm.role END AS role
  FROM actor a
  JOIN public.workspaces w ON w.id=a.workspace_id AND w.status='active'
  LEFT JOIN public.workspace_members wm
    ON wm.user_id=a.user_id
   AND wm.workspace_id=a.workspace_id
   AND wm.status='active'
  WHERE a.global_role='admin' OR wm.user_id IS NOT NULL
), members AS (
  SELECT
    wm.user_id::text AS user_id,wm.role,wm.joined_at,
    COALESCE(NULLIF(BTRIM(CONCAT_WS(' ',u.first_name,u.last_name)),''),NULLIF(u.full_name,''),u.email) AS name,
    u.email,(u.id=a.owner_user_id) AS is_owner
  FROM allowed a
  JOIN public.workspace_members wm ON wm.workspace_id=a.id AND wm.status='active'
  JOIN public.app_users u ON u.id=wm.user_id AND u.deleted_at IS NULL
), invitations AS (
  SELECT wi.id::text AS id,wi.email,wi.role,wi.expires_at,wi.created_at
  FROM allowed a
  JOIN public.workspace_invitations wi ON wi.workspace_id=a.id
  WHERE wi.accepted_at IS NULL AND wi.revoked_at IS NULL AND wi.expires_at>now()
)
SELECT
  COALESCE((SELECT row_to_json(a) FROM allowed a),'{}'::json) AS workspace,
  COALESCE((SELECT jsonb_agg(to_jsonb(m) ORDER BY m.is_owner DESC,lower(m.name)) FROM members m),'[]'::jsonb) AS members,
  COALESCE((SELECT jsonb_agg(to_jsonb(i) ORDER BY i.created_at DESC) FROM invitations i),'[]'::jsonb) AS invitations;