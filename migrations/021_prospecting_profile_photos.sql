ALTER TABLE public.linkedin_prospecting_contacts
  ADD COLUMN IF NOT EXISTS photo_url text NOT NULL DEFAULT '';
