DO $$
DECLARE
  v_user_id uuid;
  v_workspace_id uuid;
BEGIN
  SELECT id INTO v_user_id FROM public.app_users WHERE email = 'admin@example.com';

  INSERT INTO public.workspaces (name, slug, owner_user_id, is_personal, status)
  VALUES ('Mon Workspace', 'mon-workspace', v_user_id, true, 'active')
  RETURNING id INTO v_workspace_id;

  INSERT INTO public.workspace_members (workspace_id, user_id, role)
  VALUES (v_workspace_id, v_user_id, 'owner');

  UPDATE public.app_users
  SET last_workspace_id = v_workspace_id
  WHERE id = v_user_id;

  RAISE NOTICE 'Workspace créé : %', v_workspace_id;
END;
$$;
