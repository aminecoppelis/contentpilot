ALTER TABLE public.linkedin_prospecting_campaigns
  ADD COLUMN IF NOT EXISTS search_status text NOT NULL DEFAULT 'idle',
  ADD COLUMN IF NOT EXISTS search_progress smallint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS search_result text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS search_keywords text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS search_locale text NOT NULL DEFAULT 'fr',
  ADD COLUMN IF NOT EXISTS search_lease uuid,
  ADD COLUMN IF NOT EXISTS search_started_at timestamptz;

CREATE INDEX IF NOT EXISTS linkedin_prospecting_pending_search_idx
  ON public.linkedin_prospecting_campaigns (created_at)
  WHERE search_status IN ('queued', 'running');

ALTER TABLE public.user_table_preferences
  DROP CONSTRAINT IF EXISTS user_table_preferences_view_key_check;
ALTER TABLE public.user_table_preferences
  ADD CONSTRAINT user_table_preferences_view_key_check CHECK
  (view_key IN ('posts','publications','strategies','networks','users','members','invitations','publication_calendar','prospecting_campaigns'));
