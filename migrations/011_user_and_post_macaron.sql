-- Migration 011: Paramétrage du macaron par utilisateur et activation par post
-- Cahier technique / Demande utilisateur :
-- 1. Import de macaron personnalisé (PNG, ICO, WEBP, JPG...) par utilisateur
-- 2. Positionnement du macaron sur l'image (bottom-right, bottom-left, top-right, top-left, center)
-- 3. Activation ou désactivation du macaron par post / demande

-- Paramétrage utilisateur pour le macaron
ALTER TABLE public.app_users
  ADD COLUMN IF NOT EXISTS macaron_url text,
  ADD COLUMN IF NOT EXISTS macaron_position text NOT NULL DEFAULT 'bottom-right',
  ADD COLUMN IF NOT EXISTS macaron_enabled boolean NOT NULL DEFAULT true;

-- Paramétrage du macaron sur les demandes de posts (post_requests)
ALTER TABLE public.post_requests
  ADD COLUMN IF NOT EXISTS use_macaron boolean NOT NULL DEFAULT true;

-- Paramétrage du macaron sur chaque idée / post (post_ideas)
ALTER TABLE public.post_ideas
  ADD COLUMN IF NOT EXISTS use_macaron boolean NOT NULL DEFAULT true;

-- Rétrocompatibilité : initialisation des valeurs par défaut pour les enregistrements existants
UPDATE public.app_users
SET macaron_position = 'bottom-right'
WHERE macaron_position IS NULL OR macaron_position = '';

UPDATE public.app_users
SET macaron_enabled = true
WHERE macaron_enabled IS NULL;

UPDATE public.post_requests
SET use_macaron = true
WHERE use_macaron IS NULL;

UPDATE public.post_ideas
SET use_macaron = true
WHERE use_macaron IS NULL;

-- Refuse les valeurs incohérentes même si elles arrivent hors de l'application.
UPDATE public.app_users
SET macaron_position = 'bottom-right'
WHERE macaron_position NOT IN ('bottom-right', 'bottom-left', 'top-right', 'top-left', 'center');

ALTER TABLE public.app_users
  DROP CONSTRAINT IF EXISTS app_users_macaron_position_check;
ALTER TABLE public.app_users
  ADD CONSTRAINT app_users_macaron_position_check
  CHECK (macaron_position IN ('bottom-right', 'bottom-left', 'top-right', 'top-left', 'center'));
