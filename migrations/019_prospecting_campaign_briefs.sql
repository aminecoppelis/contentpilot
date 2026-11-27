ALTER TABLE public.linkedin_prospecting_campaigns
  ADD COLUMN IF NOT EXISTS goal text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS offer text NOT NULL DEFAULT '';

ALTER TABLE public.linkedin_prospecting_contacts
  ADD COLUMN IF NOT EXISTS draft_message text NOT NULL DEFAULT '';
