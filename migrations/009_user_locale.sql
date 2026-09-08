-- Préférence de langue par utilisateur (i18n).
-- La locale effective reste pilotée par le cookie `pg_lang` ; cette colonne
-- sert à réappliquer le choix après effacement du cookie / sur un autre appareil.
ALTER TABLE public.app_users
  ADD COLUMN IF NOT EXISTS locale text NOT NULL DEFAULT 'fr';
