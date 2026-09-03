-- Création de session à la connexion réussie (Cahier technique §4.1)
-- Params: $1 user_id, $2 session_token_hash, $3 expires_at, $4 user_agent, $5 ip_address
INSERT INTO public.auth_sessions (user_id, session_token_hash, expires_at, user_agent, ip_address)
VALUES ($1::uuid, $2::text, $3::timestamptz, $4::text, $5::text)
RETURNING id::text AS session_id;
