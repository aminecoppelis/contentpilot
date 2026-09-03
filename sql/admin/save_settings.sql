-- Port verbatim de "BDD - Enregistrer paramétrage Admin"
WITH input AS (
  SELECT
    $1::text AS session_hash,
    NULLIF(BTRIM($2::text),'')::uuid AS fallback_session_id,
    NULLIF(BTRIM($3::text),'') AS fallback_request_token,
    $4::boolean AS is_enabled,
    BTRIM($5::text) AS api_key,
    lower(BTRIM($6::text)) AS gl,
    lower(BTRIM($7::text)) AS hl,
    LEAST(10,GREATEST(3,COALESCE(NULLIF($8::text,'')::int,8))) AS num
), admin_ctx AS (
  SELECT u.id
  FROM input i
  JOIN public.auth_sessions s ON (
    (i.session_hash<>'' AND s.session_token_hash=i.session_hash)
    OR (
      i.fallback_session_id IS NOT NULL
      AND s.id=i.fallback_session_id
      AND i.fallback_request_token IS NOT NULL
      AND encode(digest(s.id::text||':'||s.session_token_hash,'sha256'),'hex')=i.fallback_request_token
    )
  )
  JOIN public.app_users u ON u.id=s.user_id
  WHERE s.revoked_at IS NULL
    AND s.expires_at>now()
    AND u.is_active=true
    AND u.deleted_at IS NULL
    AND lower(COALESCE(u.role,'user'))='admin'
  LIMIT 1
), old AS (
  SELECT * FROM public.app_external_api_settings WHERE provider='serper' LIMIT 1
), checks AS (
  SELECT
    i.*,
    (SELECT id FROM admin_ctx) AS admin_id,
    COALESCE((SELECT api_key_ciphertext FROM old),'') AS old_secret,
    COALESCE(NULLIF((SELECT token_encryption_key FROM old),''),encode(gen_random_bytes(32),'hex')) AS shared_key
  FROM input i
), decision AS (
  SELECT *, CASE
    WHEN admin_id IS NULL THEN 'Session invalide ou droits administrateur insuffisants.'
    WHEN gl NOT IN ('fr','us','gb','ca','de','es','it','be','ch','ma','world') THEN 'Pays Serper invalide.'
    WHEN hl NOT IN ('fr','en','es','de','it') THEN 'Langue Serper invalide.'
    WHEN is_enabled AND api_key='' AND old_secret='' THEN 'Le token Serper est obligatoire pour activer l’intégration.'
    WHEN api_key<>'' AND (length(api_key) < 20 OR length(api_key) > 500 OR position(' ' in api_key)>0 OR position(chr(9) in api_key)>0 OR position(chr(10) in api_key)>0 OR position(chr(13) in api_key)>0) THEN 'Le token Serper semble invalide.'
    ELSE NULL END AS error_message
  FROM checks
), up AS (
  INSERT INTO public.app_external_api_settings(
    provider,api_key_ciphertext,settings,token_encryption_key,is_enabled,created_at,updated_at
  )
  SELECT
    'serper',
    CASE WHEN api_key<>'' THEN armor(pgp_sym_encrypt(api_key,shared_key,'cipher-algo=aes256')) ELSE old_secret END,
    jsonb_build_object('gl',CASE WHEN gl='world' THEN 'us' ELSE gl END,'hl',hl,'num',num),
    shared_key,
    is_enabled,
    now(),
    now()
  FROM decision
  WHERE error_message IS NULL
  ON CONFLICT(provider) DO UPDATE SET
    api_key_ciphertext=EXCLUDED.api_key_ciphertext,
    settings=EXCLUDED.settings,
    token_encryption_key=COALESCE(NULLIF(public.app_external_api_settings.token_encryption_key,''),EXCLUDED.token_encryption_key),
    is_enabled=EXCLUDED.is_enabled,
    updated_at=now()
  RETURNING provider
)
SELECT
  (error_message IS NULL AND EXISTS(SELECT 1 FROM up)) AS success,
  COALESCE(error_message,'') AS error_message,
  CASE WHEN error_message IS NULL THEN 'Paramétrage Serper enregistré.' ELSE error_message END AS message
FROM decision;