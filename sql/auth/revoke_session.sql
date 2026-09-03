-- Déconnexion (Cahier technique §4.3) — Params: $1 session_id
UPDATE public.auth_sessions
SET revoked_at = now()
WHERE id = $1::uuid;
