CREATE TABLE IF NOT EXISTS public.linkedin_prospecting_campaigns (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES public.app_users(id) ON DELETE CASCADE,
  workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  name text NOT NULL,
  target text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS linkedin_prospecting_campaigns_owner_idx
  ON public.linkedin_prospecting_campaigns (user_id, workspace_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.linkedin_prospecting_contacts (
  campaign_id uuid NOT NULL REFERENCES public.linkedin_prospecting_campaigns(id) ON DELETE CASCADE,
  profile_slug text NOT NULL,
  display_name text NOT NULL,
  headline text NOT NULL,
  location text NOT NULL,
  reason text NOT NULL,
  relevance smallint NOT NULL,
  added_at timestamptz,
  PRIMARY KEY (campaign_id, profile_slug)
);

ALTER TABLE public.linkedin_prospecting_messages
  ADD COLUMN IF NOT EXISTS campaign_id uuid REFERENCES public.linkedin_prospecting_campaigns(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS linkedin_prospecting_messages_campaign_idx
  ON public.linkedin_prospecting_messages (campaign_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS linkedin_prospecting_campaign_delivery_idx
  ON public.linkedin_prospecting_messages (campaign_id, profile_slug)
  WHERE campaign_id IS NOT NULL AND status IN ('pending', 'sent', 'unknown');
