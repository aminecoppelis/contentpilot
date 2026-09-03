-- Fiabilisation des interactions UI / comptes sociaux multi-workspace.
-- Migration additive et idempotente.

ALTER TABLE public.app_social_account_workspaces
  ADD COLUMN IF NOT EXISTS share_source text NOT NULL DEFAULT 'local';
ALTER TABLE public.app_social_account_workspaces
  ADD COLUMN IF NOT EXISTS shared_at timestamptz;
ALTER TABLE public.app_social_account_workspaces
  ADD COLUMN IF NOT EXISTS revoked_at timestamptz;

CREATE INDEX IF NOT EXISTS app_social_account_workspaces_access_idx
  ON public.app_social_account_workspaces(workspace_id, account_id, is_active, revoked_at);

-- Les liens du workspace d'origine sont locaux par définition.
UPDATE public.app_social_account_workspaces saw
SET share_source = 'local'
FROM public.app_social_accounts a
WHERE a.id = saw.account_id
  AND a.workspace_id = saw.workspace_id
  AND COALESCE(saw.share_source,'') <> 'local';
