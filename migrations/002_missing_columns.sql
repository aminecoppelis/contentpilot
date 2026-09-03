-- =====================================================================
--  Migration additive — colonnes découvertes après coup
--
--  Le SQL verbatim repris du workflow n8n référence des colonnes qui
--  n'apparaissaient dans aucune instruction INSERT (donc invisibles lors
--  de la reconstruction initiale du schéma) mais bien dans des SELECT.
--
--  Idempotente : relançable sans risque.
-- =====================================================================

-- app_users : utilisées par sql/admin/list_users.sql
ALTER TABLE public.app_users ADD COLUMN IF NOT EXISTS activated_at  timestamptz;
ALTER TABLE public.app_users ADD COLUMN IF NOT EXISTS last_login_at timestamptz;

-- Renseigne rétroactivement activated_at pour les comptes déjà actifs
UPDATE public.app_users
SET activated_at = COALESCE(activated_at, activation_sent_at, created_at)
WHERE is_active = true AND activated_at IS NULL;

-- post_publications : colonnes ajoutées lors de l'audit fonctionnel
ALTER TABLE public.post_publications ADD COLUMN IF NOT EXISTS error_message text;
ALTER TABLE public.post_publications ADD COLUMN IF NOT EXISTS published_by  uuid;
ALTER TABLE public.post_publications ADD COLUMN IF NOT EXISTS published_at  timestamptz;

DO $do$ BEGIN
  ALTER TABLE public.post_publications
    ADD CONSTRAINT fk_publication_published_by
    FOREIGN KEY (published_by) REFERENCES public.app_users(id);
EXCEPTION WHEN duplicate_object THEN NULL; END $do$;

-- post_ideas : lien direct vers la version affichée
ALTER TABLE public.post_ideas ADD COLUMN IF NOT EXISTS current_version_id uuid;

DO $do$ BEGIN
  ALTER TABLE public.post_ideas
    ADD CONSTRAINT fk_current_version
    FOREIGN KEY (current_version_id) REFERENCES public.post_versions(id);
EXCEPTION WHEN duplicate_object THEN NULL; END $do$;

-- workspace_members : date d'adhésion effective
ALTER TABLE public.workspace_members ADD COLUMN IF NOT EXISTS joined_at timestamptz;
UPDATE public.workspace_members
SET joined_at = COALESCE(joined_at, created_at)
WHERE status = 'active' AND joined_at IS NULL;
