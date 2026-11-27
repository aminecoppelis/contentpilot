CREATE TABLE IF NOT EXISTS public.linkedin_prospecting_accounts (
  user_id uuid NOT NULL REFERENCES public.app_users(id) ON DELETE CASCADE,
  workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  unipile_account_id text NOT NULL UNIQUE,
  display_name text NOT NULL,
  PRIMARY KEY (user_id, workspace_id)
);

CREATE TABLE IF NOT EXISTS public.linkedin_prospecting_messages (
  submission_id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES public.app_users(id) ON DELETE CASCADE,
  workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  profile_slug text NOT NULL,
  status text NOT NULL CHECK (status IN ('pending', 'sent', 'failed', 'unknown')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS linkedin_prospecting_history_idx
  ON public.linkedin_prospecting_messages (user_id, workspace_id, created_at DESC);
