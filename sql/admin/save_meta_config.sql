-- Port verbatim de "BDD - Enregistrer configuration Meta Admin"
WITH input AS (
  SELECT $1::text AS session_hash,NULLIF(BTRIM($2::text),'')::uuid AS fallback_session_id,NULLIF(BTRIM($3::text),'') AS fallback_request_token,
    RTRIM(BTRIM($4::text),'/') AS public_app_url,BTRIM($5::text) AS graph_version,
    BTRIM($6::text) AS fb_app_id,BTRIM($7::text) AS fb_secret,BTRIM($8::text) AS fb_config_id,BTRIM($9::text) AS fb_scopes,$10::boolean AS fb_enabled,
    BTRIM($11::text) AS ig_app_id,BTRIM($12::text) AS ig_secret,BTRIM($13::text) AS ig_scopes,$14::boolean AS ig_enabled
), admin_ctx AS (
  SELECT u.id FROM input i JOIN public.auth_sessions s ON ((i.session_hash<>'' AND s.session_token_hash=i.session_hash) OR (i.fallback_session_id IS NOT NULL AND s.id=i.fallback_session_id AND i.fallback_request_token IS NOT NULL AND encode(digest(s.id::text||':'||s.session_token_hash,'sha256'),'hex')=i.fallback_request_token)) JOIN public.app_users u ON u.id=s.user_id
  WHERE s.revoked_at IS NULL AND s.expires_at>now() AND u.is_active=true AND u.deleted_at IS NULL AND lower(COALESCE(u.role,'user'))='admin' LIMIT 1
), old_fb AS (SELECT * FROM public.app_integration_settings WHERE provider='meta_facebook'), old_ig AS (SELECT * FROM public.app_integration_settings WHERE provider='meta_instagram'), checks AS (
 SELECT i.*,(SELECT id FROM admin_ctx) AS admin_id,
   COALESCE((SELECT app_secret FROM old_fb),'') AS old_fb_secret,COALESCE((SELECT app_id FROM old_fb),'') AS old_fb_id,
   COALESCE((SELECT app_secret FROM old_ig),'') AS old_ig_secret,COALESCE((SELECT app_id FROM old_ig),'') AS old_ig_id,
   COALESCE(NULLIF((SELECT token_encryption_key FROM old_fb),''),NULLIF((SELECT token_encryption_key FROM old_ig),''),encode(gen_random_bytes(32),'hex')) AS shared_key
 FROM input i
), decision AS (
 SELECT *,CASE
  WHEN admin_id IS NULL THEN 'Session invalide ou droits administrateur insuffisants.'
  WHEN public_app_url !~ '^https://[^[:space:]]+$' THEN 'L’URL publique doit être une URL HTTPS valide.'
  WHEN graph_version !~ '^v[0-9]+\.[0-9]+$' THEN 'La version Graph API doit utiliser le format v25.0.'
  WHEN fb_app_id<>'' AND fb_app_id !~ '^[0-9]+$' THEN 'Le Meta App ID / Facebook App ID doit contenir uniquement des chiffres.'
  WHEN ig_app_id<>'' AND ig_app_id !~ '^[0-9]+$' THEN 'L’Instagram App ID doit contenir uniquement des chiffres.'
  WHEN fb_app_id<>old_fb_id AND fb_secret='' THEN 'Le Meta App Secret / Facebook App Secret est obligatoire lorsque le Meta App ID / Facebook App ID change.'
  WHEN ig_app_id<>old_ig_id AND ig_secret='' THEN 'Le secret Instagram est obligatoire lorsque l’App ID change.'
  WHEN fb_enabled AND (fb_app_id='' OR COALESCE(NULLIF(fb_secret,''),NULLIF(old_fb_secret,'')) IS NULL OR fb_scopes='') THEN 'La configuration Facebook est incomplète.'
  WHEN ig_enabled AND (ig_app_id='' OR COALESCE(NULLIF(ig_secret,''),NULLIF(old_ig_secret,'')) IS NULL OR ig_scopes='') THEN 'La configuration Instagram est incomplète.'
  ELSE NULL END AS error_message
 FROM checks
), up_fb AS (
 INSERT INTO public.app_integration_settings(provider,app_id,app_secret,public_app_url,graph_version,login_config_id,scopes,token_encryption_key,is_enabled,created_at,updated_at)
 SELECT 'meta_facebook',fb_app_id,COALESCE(NULLIF(fb_secret,''),old_fb_secret),public_app_url,graph_version,fb_config_id,fb_scopes,shared_key,fb_enabled,now(),now() FROM decision WHERE error_message IS NULL
 ON CONFLICT(provider) DO UPDATE SET app_id=EXCLUDED.app_id,app_secret=EXCLUDED.app_secret,public_app_url=EXCLUDED.public_app_url,graph_version=EXCLUDED.graph_version,login_config_id=EXCLUDED.login_config_id,scopes=EXCLUDED.scopes,token_encryption_key=COALESCE(NULLIF(public.app_integration_settings.token_encryption_key,''),EXCLUDED.token_encryption_key),is_enabled=EXCLUDED.is_enabled,updated_at=now() RETURNING provider
), up_ig AS (
 INSERT INTO public.app_integration_settings(provider,app_id,app_secret,public_app_url,graph_version,login_config_id,scopes,token_encryption_key,is_enabled,created_at,updated_at)
 SELECT 'meta_instagram',ig_app_id,COALESCE(NULLIF(ig_secret,''),old_ig_secret),public_app_url,graph_version,'',ig_scopes,shared_key,ig_enabled,now(),now() FROM decision WHERE error_message IS NULL
 ON CONFLICT(provider) DO UPDATE SET app_id=EXCLUDED.app_id,app_secret=EXCLUDED.app_secret,public_app_url=EXCLUDED.public_app_url,graph_version=EXCLUDED.graph_version,scopes=EXCLUDED.scopes,token_encryption_key=COALESCE(NULLIF(public.app_integration_settings.token_encryption_key,''),EXCLUDED.token_encryption_key),is_enabled=EXCLUDED.is_enabled,updated_at=now() RETURNING provider
)
SELECT (error_message IS NULL AND EXISTS(SELECT 1 FROM up_fb) AND EXISTS(SELECT 1 FROM up_ig)) AS success,COALESCE(error_message,'') AS error_message,
CASE WHEN error_message IS NULL THEN 'Configuration Meta enregistrée.' ELSE error_message END AS message FROM decision;