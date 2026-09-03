CREATE TABLE IF NOT EXISTS public.post_generation_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id uuid NOT NULL REFERENCES public.post_requests(id) ON DELETE CASCADE,
  workspace_id uuid NOT NULL REFERENCES public.workspaces(id),
  user_id uuid REFERENCES public.app_users(id),
  mode text NOT NULL DEFAULT 'initial',
  requested_count int NOT NULL DEFAULT 1,
  instructions text,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'queued',
  attempt_count int NOT NULL DEFAULT 0,
  locked_until timestamptz,
  started_at timestamptz,
  finished_at timestamptz,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS post_generation_jobs_status_created_idx
  ON public.post_generation_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS post_generation_jobs_request_idx
  ON public.post_generation_jobs(request_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS post_generation_jobs_one_active_per_request_idx
  ON public.post_generation_jobs(request_id)
  WHERE status IN ('queued','running','retry');
