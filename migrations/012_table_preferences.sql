CREATE TABLE IF NOT EXISTS public.user_table_preferences (
    user_id uuid NOT NULL REFERENCES public.app_users(id) ON DELETE CASCADE,
    workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
    view_key text NOT NULL,
    state jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, workspace_id, view_key),
    CHECK (view_key IN ('posts','publications','strategies','networks','users','members','invitations')),
    CHECK (jsonb_typeof(state) = 'object')
);
