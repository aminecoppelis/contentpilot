-- =====================================================================
--  Post Generator — migration initiale (schéma complet)
--
--  Ce fichier est IDEMPOTENT et TRANSACTIONNEL :
--    - toutes les créations utilisent IF NOT EXISTS ;
--    - les contraintes ajoutées après coup sont protégées par un bloc DO ;
--    - install.sh l'exécute avec --single-transaction, donc en cas d'erreur
--      la base revient exactement à son état d'avant, sans schéma partiel.
--  Il peut donc être relancé autant de fois que nécessaire sans risque.
--
--  Ordre des tables : validé automatiquement (aucune clé étrangère ne
--  référence une table créée plus loin dans le fichier).
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.app_users (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email               text UNIQUE NOT NULL,
  first_name          text,
  last_name           text,
  full_name           text,
  password_hash       text NOT NULL,
  role                text NOT NULL DEFAULT 'user',
  is_active           boolean NOT NULL DEFAULT false,
  activation_sent_at  timestamptz,
  activated_at        timestamptz,   -- date d'activation effective du compte
  last_login_at       timestamptz,   -- dernière connexion réussie
  last_workspace_id   uuid,
  deleted_at          timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.account_activation_tokens (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES public.app_users(id),
  token_hash  text NOT NULL,
  expires_at  timestamptz NOT NULL,
  used_at     timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.auth_sessions (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             uuid NOT NULL REFERENCES public.app_users(id),
  session_token_hash  text NOT NULL,
  user_agent          text,
  ip_address          text,
  expires_at          timestamptz NOT NULL,
  revoked_at          timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS auth_sessions_session_token_hash_idx ON public.auth_sessions (session_token_hash);

CREATE TABLE IF NOT EXISTS public.auth_login_attempts (
  email            text NOT NULL,
  ip_address       text NOT NULL,
  failed_attempts  int NOT NULL DEFAULT 0,
  lock_level       int NOT NULL DEFAULT 0,
  locked_until     timestamptz,
  first_failed_at  timestamptz,
  last_failed_at   timestamptz,
  updated_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (email, ip_address)
);

CREATE TABLE IF NOT EXISTS public.workspaces (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name           text NOT NULL,
  slug           text UNIQUE,
  owner_user_id  uuid NOT NULL REFERENCES public.app_users(id),
  is_personal    boolean NOT NULL DEFAULT false,
  system_key     text,
  status         text NOT NULL DEFAULT 'active',
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.workspace_members (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id   uuid NOT NULL REFERENCES public.workspaces(id),
  user_id        uuid NOT NULL REFERENCES public.app_users(id),
  role           text NOT NULL DEFAULT 'member',
  status         text NOT NULL DEFAULT 'pending',
  invited_by     uuid REFERENCES public.app_users(id),
  joined_at      timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, user_id)
);


-- Invitations de workspace (découvert dans "BDD - Charger Workspace" /
-- "BDD - Accepter invitation Workspace" : table distincte de workspace_members)
CREATE TABLE IF NOT EXISTS public.workspace_invitations (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id  uuid NOT NULL REFERENCES public.workspaces(id),
  email         text NOT NULL,
  role          text NOT NULL DEFAULT 'member',
  token_hash    text NOT NULL,
  invited_by    uuid REFERENCES public.app_users(id),
  expires_at    timestamptz NOT NULL,
  accepted_at   timestamptz,
  revoked_at    timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS workspace_invitations_workspace_id_idx ON public.workspace_invitations (workspace_id) WHERE accepted_at IS NULL AND revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS workspace_invitations_token_hash_idx ON public.workspace_invitations (token_hash);

DO $$ BEGIN
  ALTER TABLE public.app_users ADD CONSTRAINT fk_last_workspace
    FOREIGN KEY (last_workspace_id) REFERENCES public.workspaces(id);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS public.post_requests (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  title                 text,
  subject               text,
  prompt                text,
  commercial_objective  text,
  target_sector         text,
  language              text DEFAULT 'français',
  content_domains       jsonb DEFAULT '[]',
  target_audience       jsonb DEFAULT '[]',
  preferred_formats     jsonb DEFAULT '[]',
  constraints           text,
  source_urls           jsonb DEFAULT '[]',
  post_count            int DEFAULT 1,
  form_data             jsonb DEFAULT '{}',
  status                text NOT NULL DEFAULT 'pending',
  last_error            text,
  generated_at          timestamptz,
  user_id               uuid REFERENCES public.app_users(id),
  workspace_id          uuid REFERENCES public.workspaces(id),
  deleted_at            timestamptz,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.post_ideas (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id            uuid NOT NULL REFERENCES public.post_requests(id),
  user_id               uuid REFERENCES public.app_users(id),
  workspace_id          uuid REFERENCES public.workspaces(id),
  current_version_id    uuid,
  number                int,
  status                text NOT NULL DEFAULT 'draft',
  title                 text,
  hook                  text,
  summary               text,
  recommended_format    text,
  target_sector         text,
  target_audience       text,
  scores                jsonb DEFAULT '{}',
  seo_keywords          jsonb DEFAULT '[]',
  raw_idea              jsonb DEFAULT '{}',
  deleted_at            timestamptz,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS post_ideas_request_id_idx ON public.post_ideas (request_id);
CREATE INDEX IF NOT EXISTS post_ideas_workspace_id_status_idx ON public.post_ideas (workspace_id, status) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS public.post_versions (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  idea_id          uuid NOT NULL REFERENCES public.post_ideas(id),
  workspace_id     uuid REFERENCES public.workspaces(id),
  version_number   int NOT NULL,
  source           text NOT NULL,
  title            text,
  post_text        text NOT NULL,
  hashtags         jsonb DEFAULT '[]',
  cta              text,
  instructions     text,
  is_current       boolean NOT NULL DEFAULT true,
  raw_version      jsonb DEFAULT '{}',
  edited_by        uuid REFERENCES public.app_users(id),
  edit_reason      text,
  created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS post_versions_idea_id_is_current_idx ON public.post_versions (idea_id, is_current);

DO $$ BEGIN
  ALTER TABLE public.post_ideas ADD CONSTRAINT fk_current_version
    FOREIGN KEY (current_version_id) REFERENCES public.post_versions(id);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS public.post_media (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  idea_id             uuid NOT NULL REFERENCES public.post_ideas(id),
  workspace_id        uuid REFERENCES public.workspaces(id),
  version_id          uuid REFERENCES public.post_versions(id),
  media_type          text NOT NULL,
  media_role          text,
  source              text,
  status              text NOT NULL DEFAULT 'pending',
  generation_status   text,
  file_path           text,
  public_url          text,
  external_url        text,
  file_name           text,
  mime_type           text,
  size_bytes          bigint,
  prompt              text,
  scenario            jsonb,
  scenario_text       text,
  metadata            jsonb DEFAULT '{}',
  error_message       text,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS post_media_idea_id_idx ON public.post_media (idea_id);

CREATE TABLE IF NOT EXISTS public.post_publications (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  idea_id               uuid NOT NULL REFERENCES public.post_ideas(id),
  workspace_id          uuid REFERENCES public.workspaces(id),
  version_id            uuid REFERENCES public.post_versions(id),
  media_id              uuid REFERENCES public.post_media(id),
  platform              text NOT NULL,
  publication_type      text,
  status                text NOT NULL DEFAULT 'pending',
  publish_mode          text,
  scheduled_at          timestamptz,
  post_text_snapshot    text,
  hashtags_snapshot     jsonb,
  media_url_snapshot    text,
  response              jsonb,
  error_message         text,
  published_by          uuid REFERENCES public.app_users(id),
  published_at          timestamptz,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS post_publications_idea_id_platform_idx ON public.post_publications (idea_id, platform);

CREATE TABLE IF NOT EXISTS public.post_activity_logs (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id  uuid REFERENCES public.workspaces(id),
  entity_type   text NOT NULL,
  entity_id     uuid NOT NULL,
  action        text NOT NULL,
  details       jsonb DEFAULT '{}',
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.app_social_accounts (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                uuid REFERENCES public.app_users(id),
  workspace_id           uuid REFERENCES public.workspaces(id),
  provider               text NOT NULL,
  display_name           text,
  platform_account_name  text,
  external_account_id    text,
  external_parent_id     text,
  external_username      text,
  token_ciphertext       text,
  token_expires_at       timestamptz,
  scopes                 jsonb DEFAULT '[]',
  metadata               jsonb DEFAULT '{}',
  is_active              boolean NOT NULL DEFAULT true,
  deleted_at             timestamptz,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS app_social_accounts_workspace_id_provider_idx ON public.app_social_accounts (workspace_id, provider) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS public.app_social_account_workspaces (
  account_id    uuid NOT NULL REFERENCES public.app_social_accounts(id),
  workspace_id  uuid NOT NULL REFERENCES public.workspaces(id),
  granted_by    uuid REFERENCES public.app_users(id),
  role          text DEFAULT 'publisher',
  is_active     boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (account_id, workspace_id)
);

CREATE TABLE IF NOT EXISTS public.app_social_oauth_states (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid REFERENCES public.app_users(id),
  workspace_id  uuid REFERENCES public.workspaces(id),
  state_hash    text NOT NULL,
  redirect_uri  text,
  provider      text NOT NULL,
  expires_at    timestamptz NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- Configuration des apps Meta. Providers réels : 'meta_facebook', 'meta_instagram'
CREATE TABLE IF NOT EXISTS public.app_integration_settings (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provider              text NOT NULL UNIQUE,
  app_id                text,
  app_secret            text,
  public_app_url        text,
  graph_version         text DEFAULT 'v25.0',
  login_config_id       text,
  scopes                text,
  token_encryption_key  text,
  is_enabled            boolean NOT NULL DEFAULT true,
  last_tested_at        timestamptz,
  last_test_success     boolean,
  last_test_message     text,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);

-- Clés d'API externes (Serper) — table DISTINCTE de app_integration_settings.
-- La clé est chiffrée via pgcrypto : armor(pgp_sym_encrypt(key, shared_key,'cipher-algo=aes256'))
CREATE TABLE IF NOT EXISTS public.app_external_api_settings (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provider              text NOT NULL UNIQUE,
  api_key_ciphertext    text,
  settings              jsonb DEFAULT '{}',
  token_encryption_key  text,
  is_enabled            boolean NOT NULL DEFAULT false,
  last_tested_at        timestamptz,
  last_test_success     boolean,
  last_test_message     text,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);

-- Comptes sociaux candidats détectés pendant un flux OAuth, avant sélection
-- définitive par l'utilisateur (ex. liste des Pages Facebook proposées)
CREATE TABLE IF NOT EXISTS public.app_social_oauth_candidates (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  oauth_state_id         uuid REFERENCES public.app_social_oauth_states(id),
  user_id                uuid REFERENCES public.app_users(id),
  workspace_id           uuid REFERENCES public.workspaces(id),
  provider               text NOT NULL,
  display_name           text,
  platform_account_name  text,
  external_account_id    text,
  external_parent_id     text,
  external_username      text,
  token_ciphertext       text,
  token_expires_at       timestamptz,
  scopes                 jsonb DEFAULT '[]',
  metadata               jsonb DEFAULT '{}',
  created_at             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS app_social_oauth_candidates_oauth_state_id_idx ON public.app_social_oauth_candidates (oauth_state_id);

CREATE TABLE IF NOT EXISTS public.app_growth_strategies (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id        uuid NOT NULL REFERENCES public.workspaces(id),
  social_account_id   uuid REFERENCES public.app_social_accounts(id),
  created_by          uuid REFERENCES public.app_users(id),
  title               text,
  objective_type      text,
  objective_label     text,
  status              text NOT NULL DEFAULT 'draft',
  duration_days       int,
  form_data           jsonb DEFAULT '{}',
  network_snapshot    jsonb DEFAULT '{}',
  research_context    jsonb DEFAULT '{}',
  strategy_data       jsonb DEFAULT '{}',
  current_version     int DEFAULT 1,
  last_analyzed_at    timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now()
);

-- Versions successives d'une stratégie (historique complet des analyses IA)
CREATE TABLE IF NOT EXISTS public.app_growth_strategy_versions (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_id       uuid NOT NULL REFERENCES public.app_growth_strategies(id),
  workspace_id      uuid REFERENCES public.workspaces(id),
  version_no        int NOT NULL DEFAULT 1,
  input_data        jsonb DEFAULT '{}',
  network_snapshot  jsonb DEFAULT '{}',
  research_context  jsonb DEFAULT '{}',
  strategy_data     jsonb DEFAULT '{}',
  created_by        uuid REFERENCES public.app_users(id),
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS app_growth_strategy_versions_strategy_id_version_no_desc_idx ON public.app_growth_strategy_versions (strategy_id, version_no DESC);

CREATE TABLE IF NOT EXISTS public.app_growth_strategy_actions (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_id    uuid NOT NULL REFERENCES public.app_growth_strategies(id),
  workspace_id   uuid REFERENCES public.workspaces(id),
  version_no     int DEFAULT 1,
  title          text NOT NULL,
  description    text,
  category       text,
  priority       text,
  status         text NOT NULL DEFAULT 'planned',
  due_day        int,
  kpi            jsonb DEFAULT '{}',
  media_prefill  jsonb DEFAULT '{}',
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.app_growth_strategy_action_calendar (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id  uuid REFERENCES public.workspaces(id),
  strategy_id   uuid REFERENCES public.app_growth_strategies(id),
  action_id     uuid REFERENCES public.app_growth_strategy_actions(id),
  action_ids    jsonb DEFAULT '[]',
  request_id    uuid REFERENCES public.post_requests(id),
  planned_for   timestamptz NOT NULL,
  status        text NOT NULL DEFAULT 'scheduled',
  payload       jsonb DEFAULT '{}',
  error_message text,
  triggered_at  timestamptz,
  created_by    uuid REFERENCES public.app_users(id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS app_growth_strategy_action_calendar_status_planned_for_idx ON public.app_growth_strategy_action_calendar (status, planned_for);

-- Compte admin de démarrage (mot de passe à changer immédiatement en prod)
-- INSERT INTO public.app_users (email, first_name, last_name, full_name, password_hash, role, is_active)
-- VALUES ('admin@example.com', 'Admin', 'Système', 'Admin Système', crypt('changeme123!', gen_salt('bf',10)), 'admin', true);

-- Rappels de validation par email (la requête du cron la crée aussi à la volée)
CREATE TABLE IF NOT EXISTS public.app_post_validation_email_reminders (
  idea_id           uuid NOT NULL,
  request_id        uuid,
  workspace_id      uuid NOT NULL,
  user_id           uuid NOT NULL,
  recipient_email   text NOT NULL,
  recipient_name    text,
  first_detected_at timestamptz NOT NULL DEFAULT now(),
  last_sent_at      timestamptz,
  next_send_at      timestamptz NOT NULL DEFAULT now(),
  sent_count        integer NOT NULL DEFAULT 0,
  lease_until       timestamptz,
  lease_token       text,
  resolved_at       timestamptz,
  updated_at        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (idea_id, user_id)
);
CREATE INDEX IF NOT EXISTS app_post_validation_email_reminders_due_idx
  ON public.app_post_validation_email_reminders(next_send_at) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS app_post_validation_email_reminders_workspace_idx
  ON public.app_post_validation_email_reminders(workspace_id, resolved_at);

-- ==================== INDEX DE PERFORMANCE ====================
-- Ajoutés après audit : toutes les listes sont filtrées par workspace_id et
-- triées par date, et les lookups par jeton haché doivent être O(log n).

CREATE INDEX IF NOT EXISTS post_requests_workspace_updated_idx
  ON public.post_requests (workspace_id, updated_at DESC NULLS LAST, created_at DESC)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS post_ideas_workspace_updated_idx
  ON public.post_ideas (workspace_id, updated_at DESC NULLS LAST)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS post_publications_workspace_updated_idx
  ON public.post_publications (workspace_id, updated_at DESC NULLS LAST, created_at DESC);

CREATE INDEX IF NOT EXISTS post_publications_status_idx
  ON public.post_publications (workspace_id, status);

CREATE INDEX IF NOT EXISTS app_growth_strategies_workspace_idx
  ON public.app_growth_strategies (workspace_id, updated_at DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS app_growth_strategy_actions_strategy_idx
  ON public.app_growth_strategy_actions (strategy_id, status);

CREATE INDEX IF NOT EXISTS post_activity_logs_workspace_created_idx
  ON public.post_activity_logs (workspace_id, created_at DESC);

CREATE INDEX IF NOT EXISTS app_social_oauth_states_hash_idx
  ON public.app_social_oauth_states (state_hash);

CREATE INDEX IF NOT EXISTS app_social_oauth_candidates_workspace_idx
  ON public.app_social_oauth_candidates (workspace_id, provider);

CREATE INDEX IF NOT EXISTS account_activation_tokens_hash_idx
  ON public.account_activation_tokens (token_hash) WHERE used_at IS NULL;

CREATE INDEX IF NOT EXISTS workspace_invitations_token_idx
  ON public.workspace_invitations (token_hash) WHERE accepted_at IS NULL AND revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS workspace_members_user_idx
  ON public.workspace_members (user_id, status);

-- Index couvrant la réclamation du Worker : la requête filtre sur
-- (planned_for <= now()) ET status IN (...), avec un tri sur planned_for.
CREATE INDEX IF NOT EXISTS calendar_worker_claim_idx
  ON public.app_growth_strategy_action_calendar (planned_for ASC, created_at ASC, id)
  WHERE status IN ('scheduled','retry','processing','generating');
