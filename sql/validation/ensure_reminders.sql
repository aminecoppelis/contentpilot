/* VALIDATION_EMAIL_REMINDERS_SCHEMA_V1 — schéma idempotent partagé par l'envoi immédiat. */
CREATE TABLE IF NOT EXISTS public.app_post_validation_email_reminders (
  idea_id uuid NOT NULL,
  request_id uuid,
  workspace_id uuid NOT NULL,
  user_id uuid NOT NULL,
  recipient_email text NOT NULL,
  recipient_name text,
  first_detected_at timestamptz NOT NULL DEFAULT now(),
  last_sent_at timestamptz,
  next_send_at timestamptz NOT NULL DEFAULT now(),
  sent_count integer NOT NULL DEFAULT 0,
  lease_until timestamptz,
  lease_token text,
  resolved_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (idea_id,user_id)
);
ALTER TABLE public.app_post_validation_email_reminders ADD COLUMN IF NOT EXISTS request_id uuid;
ALTER TABLE public.app_post_validation_email_reminders ADD COLUMN IF NOT EXISTS workspace_id uuid;
ALTER TABLE public.app_post_validation_email_reminders ADD COLUMN IF NOT EXISTS recipient_email text;
ALTER TABLE public.app_post_validation_email_reminders ADD COLUMN IF NOT EXISTS recipient_name text;
ALTER TABLE public.app_post_validation_email_reminders ADD COLUMN IF NOT EXISTS first_detected_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE public.app_post_validation_email_reminders ADD COLUMN IF NOT EXISTS last_sent_at timestamptz;
ALTER TABLE public.app_post_validation_email_reminders ADD COLUMN IF NOT EXISTS next_send_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE public.app_post_validation_email_reminders ADD COLUMN IF NOT EXISTS sent_count integer NOT NULL DEFAULT 0;
ALTER TABLE public.app_post_validation_email_reminders ADD COLUMN IF NOT EXISTS lease_until timestamptz;
ALTER TABLE public.app_post_validation_email_reminders ADD COLUMN IF NOT EXISTS lease_token text;
ALTER TABLE public.app_post_validation_email_reminders ADD COLUMN IF NOT EXISTS resolved_at timestamptz;
ALTER TABLE public.app_post_validation_email_reminders ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
CREATE INDEX IF NOT EXISTS app_post_validation_email_reminders_due_idx
  ON public.app_post_validation_email_reminders(next_send_at) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS app_post_validation_email_reminders_workspace_idx
  ON public.app_post_validation_email_reminders(workspace_id,resolved_at);
