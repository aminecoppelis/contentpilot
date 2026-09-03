-- Port verbatim de "BDD - Action Workspace"
-- PROTECT_LAST_ACCESSIBLE_WORKSPACE_V65_2026_08_07
WITH p AS (
 SELECT NULLIF($1::text,'')::uuid AS actor_id,NULLIF($2::text,'')::uuid AS workspace_id,$3::text AS action,NULLIF(BTRIM($4::text),'') AS name,NULLIF(lower(BTRIM($5::text)),'') AS email,CASE WHEN $6::text IN ('admin','member') THEN $6::text ELSE 'member' END AS role,NULLIF($7::text,'')::uuid AS target_user_id,NULLIF($8::text,'')::uuid AS invitation_id
), actor AS (
 SELECT
   p.*,
   CASE WHEN lower(COALESCE(u.role,'user'))='admin' THEN 'super_admin' ELSE wm.role END AS actor_role,
   lower(COALESCE(u.role,'user')) AS global_role,
   w.owner_user_id,w.is_personal,w.system_key,w.name AS current_name
 FROM p
 LEFT JOIN public.app_users u ON u.id=p.actor_id AND u.is_active=true AND u.deleted_at IS NULL
 LEFT JOIN public.workspace_members wm ON wm.workspace_id=p.workspace_id AND wm.user_id=p.actor_id AND wm.status='active'
 LEFT JOIN public.workspaces w ON w.id=p.workspace_id AND w.status='active'
), generated AS (SELECT encode(gen_random_bytes(32),'hex') AS token),
created_workspace AS (
 INSERT INTO public.workspaces(name,slug,owner_user_id,is_personal,system_key)
 SELECT a.name,lower(regexp_replace(a.name,'[^a-zA-Z0-9]+','-','g'))||'-'||substr(replace(gen_random_uuid()::text,'-',''),1,8),a.actor_id,false,NULL FROM actor a
 WHERE a.action='create' AND a.name IS NOT NULL AND a.actor_id IS NOT NULL RETURNING id,name,owner_user_id
),created_member AS (
 INSERT INTO public.workspace_members(workspace_id,user_id,role,status,invited_by)
 SELECT id,owner_user_id,'owner','active',owner_user_id FROM created_workspace ON CONFLICT(workspace_id,user_id) DO UPDATE SET role='owner',status='active',updated_at=now() RETURNING workspace_id,user_id
),activate_created AS (UPDATE public.app_users u SET last_workspace_id=cm.workspace_id FROM created_member cm WHERE u.id=cm.user_id RETURNING cm.workspace_id),
renamed AS (UPDATE public.workspaces w SET name=a.name,updated_at=now() FROM actor a WHERE w.id=a.workspace_id AND a.action='rename' AND a.name IS NOT NULL AND a.actor_role IN ('owner','admin','super_admin') RETURNING w.id,w.name),
invited AS (
 INSERT INTO public.workspace_invitations(workspace_id,email,role,token_hash,invited_by,expires_at)
 SELECT a.workspace_id,a.email,a.role,encode(digest(g.token,'sha256'),'hex'),a.actor_id,now()+interval '7 days' FROM actor a CROSS JOIN generated g
 WHERE a.action='invite' AND a.email IS NOT NULL AND a.actor_role IN ('owner','admin','super_admin')
   AND NOT EXISTS(SELECT 1 FROM public.workspace_members wm JOIN public.app_users u ON u.id=wm.user_id WHERE wm.workspace_id=a.workspace_id AND wm.status='active' AND lower(u.email)=a.email)
   AND NOT EXISTS(SELECT 1 FROM public.workspace_invitations wi WHERE wi.workspace_id=a.workspace_id AND lower(wi.email)=a.email AND wi.accepted_at IS NULL AND wi.revoked_at IS NULL AND wi.expires_at>now())
 RETURNING id,workspace_id,email,role
),revoked AS (UPDATE public.workspace_invitations wi SET revoked_at=now(),updated_at=now() FROM actor a WHERE wi.id=a.invitation_id AND wi.workspace_id=a.workspace_id AND a.action='revoke_invite' AND a.actor_role IN ('owner','admin','super_admin') AND wi.accepted_at IS NULL RETURNING wi.id),
role_changed AS (UPDATE public.workspace_members wm SET role=a.role,updated_at=now() FROM actor a WHERE wm.workspace_id=a.workspace_id AND wm.user_id=a.target_user_id AND a.action='member_role' AND a.actor_role IN ('owner','admin','super_admin') AND wm.role<>'owner' AND a.target_user_id<>a.actor_id RETURNING wm.user_id),
removed AS (UPDATE public.workspace_members wm SET status='removed',updated_at=now() FROM actor a WHERE wm.workspace_id=a.workspace_id AND wm.user_id=a.target_user_id AND a.action='remove_member' AND a.actor_role IN ('owner','admin','super_admin') AND wm.role<>'owner' AND a.target_user_id<>a.actor_id RETURNING wm.user_id),
left_ws AS (UPDATE public.workspace_members wm SET status='removed',updated_at=now() FROM actor a WHERE wm.workspace_id=a.workspace_id AND wm.user_id=a.actor_id AND a.action='leave' AND wm.role<>'owner' RETURNING wm.user_id),
fallback_ws AS (UPDATE public.app_users u SET last_workspace_id=(SELECT wm.workspace_id FROM public.workspace_members wm JOIN public.workspaces w ON w.id=wm.workspace_id WHERE wm.user_id=u.id AND wm.status='active' AND w.status='active' ORDER BY w.is_personal DESC,w.created_at LIMIT 1) FROM actor a WHERE u.id=a.actor_id AND a.action='leave' AND EXISTS(SELECT 1 FROM left_ws) RETURNING u.last_workspace_id),
delete_authorization AS MATERIALIZED (
 SELECT
   a.workspace_id,
   a.actor_id,
   a.current_name,
   EXISTS (
     SELECT 1
     FROM public.workspaces w2
     LEFT JOIN public.workspace_members wm2
       ON wm2.workspace_id=w2.id
      AND wm2.user_id=a.actor_id
      AND wm2.status='active'
     WHERE w2.status='active'
       AND w2.id<>a.workspace_id
       AND (
         a.global_role='admin'
         OR wm2.user_id IS NOT NULL
       )
   ) AS has_alternative_workspace
 FROM actor a
 WHERE a.action='delete'
   AND a.workspace_id IS NOT NULL
   AND a.actor_id IS NOT NULL
   AND (a.actor_role='super_admin' OR (a.actor_role='owner' AND a.owner_user_id=a.actor_id))
   AND COALESCE(a.is_personal,false)=false
   AND a.system_key IS NULL
   AND a.name IS NOT NULL
   AND a.name=a.current_name
),delete_target AS MATERIALIZED (
 SELECT da.workspace_id,da.actor_id,da.current_name
 FROM delete_authorization da
 WHERE da.has_alternative_workspace=true
),delete_users AS MATERIALIZED (
 SELECT wm.user_id
 FROM public.workspace_members wm
 JOIN delete_target dt ON dt.workspace_id=wm.workspace_id
 WHERE wm.status='active'
 UNION
 SELECT actor_id AS user_id FROM delete_target
),deleted_ws AS (
 UPDATE public.workspaces w
 SET status='deleted',updated_at=now()
 FROM delete_target dt
 WHERE w.id=dt.workspace_id AND w.status='active'
 RETURNING w.id,w.name
),revoked_delete_invites AS (
 UPDATE public.workspace_invitations wi
 SET revoked_at=COALESCE(wi.revoked_at,now()),updated_at=now()
 FROM delete_target dt
 WHERE wi.workspace_id=dt.workspace_id AND wi.accepted_at IS NULL
 RETURNING wi.id
),removed_delete_members AS (
 UPDATE public.workspace_members wm
 SET status='removed',updated_at=now()
 FROM delete_target dt
 WHERE wm.workspace_id=dt.workspace_id AND wm.status='active'
 RETURNING wm.user_id
),fallback_after_delete AS (
 UPDATE public.app_users u
 SET last_workspace_id=(
   SELECT wm.workspace_id
   FROM public.workspace_members wm
   JOIN public.workspaces w ON w.id=wm.workspace_id
   CROSS JOIN delete_target dt2
   WHERE wm.user_id=u.id
     AND wm.workspace_id<>dt2.workspace_id
     AND wm.status='active'
     AND w.status='active'
   ORDER BY w.is_personal DESC,w.created_at ASC
   LIMIT 1
 )
 FROM delete_target dt
 WHERE u.id IN (SELECT user_id FROM delete_users)
   AND u.last_workspace_id=dt.workspace_id
 RETURNING u.id,u.last_workspace_id
)
SELECT
 CASE WHEN p.action='create' THEN EXISTS(SELECT 1 FROM created_workspace) WHEN p.action='rename' THEN EXISTS(SELECT 1 FROM renamed) WHEN p.action='invite' THEN EXISTS(SELECT 1 FROM invited) WHEN p.action='revoke_invite' THEN EXISTS(SELECT 1 FROM revoked) WHEN p.action='member_role' THEN EXISTS(SELECT 1 FROM role_changed) WHEN p.action='remove_member' THEN EXISTS(SELECT 1 FROM removed) WHEN p.action='leave' THEN EXISTS(SELECT 1 FROM left_ws) WHEN p.action='delete' THEN EXISTS(SELECT 1 FROM deleted_ws) ELSE false END AS success,
 p.action,
 COALESCE((SELECT id::text FROM created_workspace),(SELECT id::text FROM deleted_ws),(SELECT workspace_id::text FROM actor),'') AS workspace_id,
 COALESCE((SELECT email FROM invited),'') AS invite_email,
 COALESCE((SELECT role FROM invited),'') AS invite_role,
 COALESCE((SELECT id::text FROM invited),'') AS invite_id,
 CASE WHEN EXISTS(SELECT 1 FROM invited) THEN (SELECT token FROM generated) ELSE '' END AS invite_token,
 CASE WHEN p.action='create' AND EXISTS(SELECT 1 FROM created_workspace) THEN 'Workspace créé.' WHEN p.action='rename' AND EXISTS(SELECT 1 FROM renamed) THEN 'Workspace renommé.' WHEN p.action='invite' AND EXISTS(SELECT 1 FROM invited) THEN 'Invitation créée.' WHEN p.action='revoke_invite' AND EXISTS(SELECT 1 FROM revoked) THEN 'Invitation annulée.' WHEN p.action='member_role' AND EXISTS(SELECT 1 FROM role_changed) THEN 'Rôle modifié.' WHEN p.action='remove_member' AND EXISTS(SELECT 1 FROM removed) THEN 'Membre retiré.' WHEN p.action='leave' AND EXISTS(SELECT 1 FROM left_ws) THEN 'Workspace quitté.' WHEN p.action='delete' AND EXISTS(SELECT 1 FROM deleted_ws) THEN 'Workspace supprimé.' WHEN p.action='delete' AND EXISTS(SELECT 1 FROM delete_authorization WHERE has_alternative_workspace=false) THEN 'Impossible de supprimer le dernier workspace accessible. Crée d’abord un autre workspace.' WHEN p.action='delete' THEN 'Suppression impossible : vérifie le nom du workspace et tes droits.' ELSE 'Action impossible ou droits insuffisants.' END AS message
FROM p;