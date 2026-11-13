-- OAuth credentials stay in the existing encrypted account token envelope.
CREATE UNIQUE INDEX IF NOT EXISTS social_youtube_workspace_channel_unique
  ON public.app_social_accounts(workspace_id, external_account_id)
  WHERE provider='youtube' AND deleted_at IS NULL;
ALTER TABLE public.app_social_oauth_states ADD COLUMN IF NOT EXISTS session_hash text;
ALTER TABLE public.post_publications ADD COLUMN IF NOT EXISTS youtube_upload_ciphertext text;
ALTER TABLE public.post_publications ADD COLUMN IF NOT EXISTS upload_bytes bigint NOT NULL DEFAULT 0;
ALTER TABLE public.post_publications ADD COLUMN IF NOT EXISTS upload_total_bytes bigint NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS publications_youtube_pending_idx
  ON public.post_publications(scheduled_at, updated_at)
  WHERE platform='youtube' AND status IN ('scheduled','processing');
-- A lost HTTP response or repeated click must not create two active uploads.
CREATE UNIQUE INDEX IF NOT EXISTS publications_youtube_active_channel_unique
  ON public.post_publications(workspace_id, idea_id, (response->>'social_account_id'))
  WHERE platform='youtube' AND status IN ('scheduled','processing');
