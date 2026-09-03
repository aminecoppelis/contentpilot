-- Fuseau IANA individuel. Les instants métier restent des timestamptz ; cette
-- colonne ne sert qu'à interpréter les saisies locales et à restituer l'heure.
ALTER TABLE public.app_users
  ADD COLUMN IF NOT EXISTS timezone text NOT NULL DEFAULT 'Europe/Paris';

UPDATE public.app_users
SET timezone='Europe/Paris'
WHERE NULLIF(btrim(COALESCE(timezone,'')),'') IS NULL;
