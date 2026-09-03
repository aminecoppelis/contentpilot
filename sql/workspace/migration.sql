-- Port verbatim de "BDD - Migration Workspaces" (idempotent).
-- Exposé par GET /app/admin/workspaces/setup : crée/complète les tables
-- multi-workspace et corrige les partages de comptes sociaux hérités.

-- MULTI_WORKSPACE_SOCIAL_ACCOUNTS_SCHEMA_2026_07_31
CREATE OR REPLACE FUNCTION public.pg_strategy_uuid_v4()
RETURNS uuid
LANGUAGE sql
VOLATILE
AS $pg_uuid$
  WITH seed AS (
    SELECT md5(random()::text || clock_timestamp()::text || txid_current()::text) AS h,
           floor(random() * 4)::integer AS variant_index
  )
  SELECT (
    substr(h,1,8) || '-' || substr(h,9,4) || '-4' || substr(h,14,3) || '-' ||
    substr('89ab',1 + variant_index,1) || substr(h,18,3) || '-' || substr(h,21,12)
  )::uuid
  FROM seed;
$pg_uuid$;

CREATE TABLE IF NOT EXISTS public.app_social_account_workspaces (
  id uuid PRIMARY KEY DEFAULT public.pg_strategy_uuid_v4(),
  account_id uuid NOT NULL,
  workspace_id uuid NOT NULL,
  granted_by uuid,
  role text NOT NULL DEFAULT 'publisher',
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(account_id, workspace_id)
);
ALTER TABLE public.app_social_account_workspaces ADD COLUMN IF NOT EXISTS id uuid DEFAULT public.pg_strategy_uuid_v4();
ALTER TABLE public.app_social_account_workspaces ADD COLUMN IF NOT EXISTS account_id uuid;
ALTER TABLE public.app_social_account_workspaces ADD COLUMN IF NOT EXISTS workspace_id uuid;
ALTER TABLE public.app_social_account_workspaces ADD COLUMN IF NOT EXISTS granted_by uuid;
ALTER TABLE public.app_social_account_workspaces ADD COLUMN IF NOT EXISTS role text DEFAULT 'publisher';
ALTER TABLE public.app_social_account_workspaces ADD COLUMN IF NOT EXISTS is_active boolean DEFAULT true;
ALTER TABLE public.app_social_account_workspaces ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now();
ALTER TABLE public.app_social_account_workspaces ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT now();
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='app_social_account_workspaces_account_workspace_key') THEN
    ALTER TABLE public.app_social_account_workspaces
      ADD CONSTRAINT app_social_account_workspaces_account_workspace_key UNIQUE(account_id, workspace_id);
  END IF;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
CREATE INDEX IF NOT EXISTS app_social_account_workspaces_account_idx ON public.app_social_account_workspaces(account_id);
CREATE INDEX IF NOT EXISTS app_social_account_workspaces_workspace_idx ON public.app_social_account_workspaces(workspace_id, is_active);

-- EXPLICIT_WORKSPACE_SHARE_ONLY_2026_07_31
ALTER TABLE public.app_social_account_workspaces ADD COLUMN IF NOT EXISTS share_source text NOT NULL DEFAULT 'local';
ALTER TABLE public.app_social_account_workspaces ADD COLUMN IF NOT EXISTS shared_at timestamptz;
ALTER TABLE public.app_social_account_workspaces ADD COLUMN IF NOT EXISTS revoked_at timestamptz;

-- lien local = uniquement le workspace d’origine du compte connecté
UPDATE public.app_social_account_workspaces saw
SET
  share_source = 'local',
  is_active = COALESCE(saw.is_active, true),
  updated_at = now()
FROM public.app_social_accounts a
WHERE saw.account_id = a.id
  AND saw.workspace_id = a.workspace_id
  AND COALESCE(saw.share_source,'') <> 'local';

-- correction de sécurité : désactive les liens créés par l'ancienne logique automatique
-- sauf les futurs partages explicites.
UPDATE public.app_social_account_workspaces saw
SET
  is_active = false,
  share_source = 'auto_merge_reverted',
  revoked_at = now(),
  updated_at = now()
FROM public.app_social_accounts a
WHERE saw.account_id = a.id
  AND saw.workspace_id <> a.workspace_id
  AND COALESCE(saw.share_source,'') NOT IN ('explicit','manual')
  AND COALESCE(saw.is_active,true) = true;



-- migration des comptes existants vers leur workspace historique
INSERT INTO public.app_social_account_workspaces(account_id, workspace_id, granted_by, role, is_active, created_at, updated_at)
SELECT DISTINCT
  a.id::uuid,
  a.workspace_id::uuid,
  CASE WHEN COALESCE(to_jsonb(a)->>'user_id','') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' THEN (to_jsonb(a)->>'user_id')::uuid ELSE NULL END,
  'admin',
  CASE WHEN lower(COALESCE(NULLIF(to_jsonb(a)->>'is_active',''),'true')) IN ('false','f','0','no','off') THEN false ELSE true END,
  COALESCE(NULLIF(to_jsonb(a)->>'created_at','')::timestamptz, now()),
  now()
FROM public.app_social_accounts a
WHERE COALESCE(to_jsonb(a)->>'id','') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
  AND COALESCE(to_jsonb(a)->>'workspace_id','') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
ON CONFLICT(account_id, workspace_id) DO UPDATE SET is_active=EXCLUDED.is_active, updated_at=now();




BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.workspaces (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  slug text NOT NULL UNIQUE,
  owner_user_id uuid NOT NULL REFERENCES public.app_users(id) ON DELETE RESTRICT,
  is_personal boolean NOT NULL DEFAULT false,
  system_key text UNIQUE,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived','deleted')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.workspace_members (
  workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES public.app_users(id) ON DELETE CASCADE,
  role text NOT NULL DEFAULT 'member' CHECK (role IN ('owner','admin','member')),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','removed')),
  invited_by uuid REFERENCES public.app_users(id) ON DELETE SET NULL,
  joined_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_id, user_id)
);

CREATE TABLE IF NOT EXISTS public.workspace_invitations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
  email text NOT NULL,
  role text NOT NULL DEFAULT 'member' CHECK (role IN ('admin','member')),
  token_hash text NOT NULL UNIQUE,
  invited_by uuid NOT NULL REFERENCES public.app_users(id) ON DELETE CASCADE,
  expires_at timestamptz NOT NULL,
  accepted_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.app_users ADD COLUMN IF NOT EXISTS last_workspace_id uuid;

DO $migration$
DECLARE
  table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'post_requests',
    'post_ideas',
    'post_versions',
    'post_media',
    'post_publications',
    'post_activity_logs',
    'app_social_accounts',
    'app_social_oauth_states',
    'app_social_oauth_candidates'
  ]
  LOOP
    IF to_regclass('public.' || table_name) IS NOT NULL THEN
      EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS workspace_id uuid', table_name);
    END IF;
  END LOOP;
END
$migration$;

WITH owner_user AS (
  SELECT id
  FROM public.app_users
  WHERE deleted_at IS NULL
  ORDER BY
    CASE WHEN lower(COALESCE(role,'user')) = 'admin' THEN 0 ELSE 1 END,
    CASE WHEN is_active THEN 0 ELSE 1 END,
    created_at ASC,
    id ASC
  LIMIT 1
)
INSERT INTO public.workspaces(name, slug, owner_user_id, is_personal, system_key)
SELECT 'Espace principal', 'espace-principal-' || substr(replace(id::text,'-',''), 1, 8), id, false, 'legacy-main'
FROM owner_user
ON CONFLICT (system_key) DO NOTHING;

INSERT INTO public.workspaces(name, slug, owner_user_id, is_personal, system_key)
SELECT
  COALESCE(NULLIF(BTRIM(CONCAT_WS(' ', u.first_name, u.last_name)), ''), NULLIF(u.full_name,''), split_part(u.email,'@',1), 'Workspace') || ' · Personnel',
  'personnel-' || substr(replace(u.id::text,'-',''), 1, 12),
  u.id,
  true,
  'personal:' || u.id::text
FROM public.app_users u
WHERE u.deleted_at IS NULL
ON CONFLICT (system_key) DO NOTHING;

INSERT INTO public.workspace_members(workspace_id, user_id, role, status, invited_by)
SELECT w.id, u.id, CASE WHEN w.owner_user_id = u.id THEN 'owner' ELSE 'admin' END, 'active', w.owner_user_id
FROM public.workspaces w
JOIN public.app_users u ON u.deleted_at IS NULL
WHERE w.system_key = 'legacy-main'
ON CONFLICT (workspace_id, user_id) DO UPDATE
SET status = 'active',
    role = CASE WHEN public.workspace_members.role = 'owner' THEN 'owner' ELSE EXCLUDED.role END,
    updated_at = now();

INSERT INTO public.workspace_members(workspace_id, user_id, role, status, invited_by)
SELECT w.id, w.owner_user_id, 'owner', 'active', w.owner_user_id
FROM public.workspaces w
WHERE w.is_personal = true
ON CONFLICT (workspace_id, user_id) DO UPDATE
SET role = 'owner', status = 'active', updated_at = now();

UPDATE public.app_users u
SET last_workspace_id = main.id
FROM public.workspaces main
WHERE main.system_key = 'legacy-main'
  AND u.deleted_at IS NULL
  AND (
    u.last_workspace_id IS NULL
    OR NOT EXISTS (
      SELECT 1
      FROM public.workspace_members wm
      WHERE wm.workspace_id = u.last_workspace_id
        AND wm.user_id = u.id
        AND wm.status = 'active'
    )
  );

DO $backfill$
DECLARE
  main_workspace uuid;
BEGIN
  SELECT id INTO main_workspace FROM public.workspaces WHERE system_key = 'legacy-main' LIMIT 1;
  IF main_workspace IS NULL THEN
    RETURN;
  END IF;

  IF to_regclass('public.post_requests') IS NOT NULL THEN
    UPDATE public.post_requests SET workspace_id = main_workspace WHERE workspace_id IS NULL;
  END IF;
  IF to_regclass('public.post_ideas') IS NOT NULL THEN
    UPDATE public.post_ideas pi
    SET workspace_id = COALESCE(pr.workspace_id, main_workspace)
    FROM public.post_requests pr
    WHERE pi.request_id = pr.id AND pi.workspace_id IS NULL;
    UPDATE public.post_ideas SET workspace_id = main_workspace WHERE workspace_id IS NULL;
  END IF;
  IF to_regclass('public.post_versions') IS NOT NULL THEN
    UPDATE public.post_versions pv
    SET workspace_id = COALESCE(pi.workspace_id, main_workspace)
    FROM public.post_ideas pi
    WHERE pv.idea_id = pi.id AND pv.workspace_id IS NULL;
    UPDATE public.post_versions SET workspace_id = main_workspace WHERE workspace_id IS NULL;
  END IF;
  IF to_regclass('public.post_media') IS NOT NULL THEN
    UPDATE public.post_media pm
    SET workspace_id = COALESCE(pi.workspace_id, main_workspace)
    FROM public.post_ideas pi
    WHERE pm.idea_id = pi.id AND pm.workspace_id IS NULL;
    UPDATE public.post_media SET workspace_id = main_workspace WHERE workspace_id IS NULL;
  END IF;
  IF to_regclass('public.post_publications') IS NOT NULL THEN
    UPDATE public.post_publications pp
    SET workspace_id = COALESCE(pi.workspace_id, main_workspace)
    FROM public.post_ideas pi
    WHERE pp.idea_id = pi.id AND pp.workspace_id IS NULL;
    UPDATE public.post_publications SET workspace_id = main_workspace WHERE workspace_id IS NULL;
  END IF;
  IF to_regclass('public.post_activity_logs') IS NOT NULL THEN
    UPDATE public.post_activity_logs SET workspace_id = main_workspace WHERE workspace_id IS NULL;
  END IF;
  IF to_regclass('public.app_social_accounts') IS NOT NULL THEN
    UPDATE public.app_social_accounts SET workspace_id = main_workspace WHERE workspace_id IS NULL;
  END IF;
  IF to_regclass('public.app_social_oauth_states') IS NOT NULL THEN
    UPDATE public.app_social_oauth_states SET workspace_id = main_workspace WHERE workspace_id IS NULL;
  END IF;
  IF to_regclass('public.app_social_oauth_candidates') IS NOT NULL THEN
    UPDATE public.app_social_oauth_candidates c
    SET workspace_id = COALESCE(s.workspace_id, main_workspace)
    FROM public.app_social_oauth_states s
    WHERE c.oauth_state_id = s.id AND c.workspace_id IS NULL;
    UPDATE public.app_social_oauth_candidates SET workspace_id = main_workspace WHERE workspace_id IS NULL;
  END IF;
END
$backfill$;

DO $workspace_not_null$
DECLARE
  table_name text;
  has_null boolean;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'post_requests',
    'post_ideas',
    'post_versions',
    'post_media',
    'post_publications',
    'post_activity_logs',
    'app_social_accounts',
    'app_social_oauth_states',
    'app_social_oauth_candidates'
  ]
  LOOP
    IF to_regclass('public.' || table_name) IS NULL THEN
      CONTINUE;
    END IF;
    EXECUTE format('SELECT EXISTS (SELECT 1 FROM public.%I WHERE workspace_id IS NULL)', table_name)
      INTO has_null;
    IF NOT has_null THEN
      EXECUTE format('ALTER TABLE public.%I ALTER COLUMN workspace_id SET NOT NULL', table_name);
    END IF;
  END LOOP;
END
$workspace_not_null$;

DO $drop_old_social_unique$
DECLARE
  constraint_name text;
  index_name text;
BEGIN
  IF to_regclass('public.app_social_accounts') IS NULL THEN
    RETURN;
  END IF;

  FOR constraint_name IN
    SELECT c.conname
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE n.nspname = 'public'
      AND t.relname = 'app_social_accounts'
      AND c.contype = 'u'
      AND (
        SELECT array_agg(a.attname ORDER BY x.ordinality)
        FROM unnest(c.conkey) WITH ORDINALITY x(attnum, ordinality)
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = x.attnum
      ) = ARRAY['user_id','provider','external_account_id']::text[]
  LOOP
    EXECUTE format('ALTER TABLE public.app_social_accounts DROP CONSTRAINT %I', constraint_name);
  END LOOP;

  FOR index_name IN
    SELECT indexname
    FROM pg_indexes
    WHERE schemaname = 'public'
      AND tablename = 'app_social_accounts'
      AND indexdef ILIKE '%UNIQUE%'
      AND regexp_replace(indexdef, '\s+', ' ', 'g') ILIKE '%(user_id, provider, external_account_id)%'
  LOOP
    EXECUTE format('DROP INDEX IF EXISTS public.%I', index_name);
  END LOOP;
END
$drop_old_social_unique$;

CREATE UNIQUE INDEX IF NOT EXISTS app_social_accounts_workspace_provider_external_uidx
  ON public.app_social_accounts(workspace_id, provider, external_account_id)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS workspace_members_user_idx ON public.workspace_members(user_id, status, workspace_id);
CREATE INDEX IF NOT EXISTS workspace_invitations_workspace_idx ON public.workspace_invitations(workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS workspace_invitations_email_idx ON public.workspace_invitations(lower(email), expires_at);
CREATE INDEX IF NOT EXISTS post_requests_workspace_idx ON public.post_requests(workspace_id, created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS post_ideas_workspace_idx ON public.post_ideas(workspace_id, request_id, created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS post_media_workspace_idx ON public.post_media(workspace_id, idea_id, created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS post_publications_workspace_idx ON public.post_publications(workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS app_social_accounts_workspace_idx ON public.app_social_accounts(workspace_id, updated_at DESC) WHERE deleted_at IS NULL;

CREATE OR REPLACE FUNCTION public.pg_set_post_idea_workspace()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  parent_workspace_id uuid;
BEGIN
  SELECT workspace_id INTO parent_workspace_id
  FROM public.post_requests
  WHERE id = NEW.request_id AND deleted_at IS NULL;
  IF parent_workspace_id IS NULL THEN
    RAISE EXCEPTION 'Demande parente introuvable pour le workspace';
  END IF;
  NEW.workspace_id := parent_workspace_id;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_set_post_idea_workspace ON public.post_ideas;
CREATE TRIGGER trg_set_post_idea_workspace
BEFORE INSERT OR UPDATE OF request_id, workspace_id ON public.post_ideas
FOR EACH ROW EXECUTE FUNCTION public.pg_set_post_idea_workspace();

CREATE OR REPLACE FUNCTION public.pg_set_post_child_workspace()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  parent_workspace_id uuid;
BEGIN
  SELECT workspace_id INTO parent_workspace_id
  FROM public.post_ideas
  WHERE id = NEW.idea_id AND deleted_at IS NULL;
  IF parent_workspace_id IS NULL THEN
    RAISE EXCEPTION 'Idée parente introuvable pour le workspace';
  END IF;
  NEW.workspace_id := parent_workspace_id;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_set_post_version_workspace ON public.post_versions;
CREATE TRIGGER trg_set_post_version_workspace
BEFORE INSERT OR UPDATE OF idea_id, workspace_id ON public.post_versions
FOR EACH ROW EXECUTE FUNCTION public.pg_set_post_child_workspace();

DROP TRIGGER IF EXISTS trg_set_post_media_workspace ON public.post_media;
CREATE TRIGGER trg_set_post_media_workspace
BEFORE INSERT OR UPDATE OF idea_id, workspace_id ON public.post_media
FOR EACH ROW EXECUTE FUNCTION public.pg_set_post_child_workspace();

DROP TRIGGER IF EXISTS trg_set_post_publication_workspace ON public.post_publications;
CREATE TRIGGER trg_set_post_publication_workspace
BEFORE INSERT OR UPDATE OF idea_id, workspace_id ON public.post_publications
FOR EACH ROW EXECUTE FUNCTION public.pg_set_post_child_workspace();

CREATE OR REPLACE FUNCTION public.pg_set_oauth_candidate_workspace()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  parent_workspace_id uuid;
BEGIN
  SELECT workspace_id INTO parent_workspace_id
  FROM public.app_social_oauth_states
  WHERE id = NEW.oauth_state_id;
  IF parent_workspace_id IS NULL THEN
    RAISE EXCEPTION 'État OAuth parent introuvable pour le workspace';
  END IF;
  NEW.workspace_id := parent_workspace_id;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_set_oauth_candidate_workspace ON public.app_social_oauth_candidates;
CREATE TRIGGER trg_set_oauth_candidate_workspace
BEFORE INSERT OR UPDATE OF oauth_state_id, workspace_id ON public.app_social_oauth_candidates
FOR EACH ROW EXECUTE FUNCTION public.pg_set_oauth_candidate_workspace();

COMMIT;
