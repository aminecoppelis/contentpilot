"""
Configuration MÉTIER lue en base — CORRIGÉ après ré-analyse du workflow.

Deux tables DISTINCTES existent réellement (ma première version les avait
fusionnées à tort en une seule) :

  1. `app_integration_settings` — configuration des apps Meta.
     Providers réels : 'meta_facebook' et 'meta_instagram' (pas 'meta').
     Colonnes : app_id, app_secret, public_app_url, graph_version (défaut
     'v25.0'), login_config_id, scopes, is_enabled, last_test_*.

  2. `app_external_api_settings` — clés d'API externes (Serper).
     La clé est chiffrée EN BASE via pgcrypto :
        armor(pgp_sym_encrypt(api_key, shared_key, 'cipher-algo=aes256'))
     et n'est déchiffrée que côté serveur au moment de l'appel.
     Les réglages fonctionnels (gl, hl, num) vivent dans la colonne jsonb
     `settings`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from app.database import get_pool

PROVIDER_META_FACEBOOK = "meta_facebook"
PROVIDER_META_INSTAGRAM = "meta_instagram"
DEFAULT_GRAPH_VERSION = "v25.0"


@dataclass
class MetaSettings:
    provider: str
    app_id: str | None
    app_secret: str | None
    public_app_url: str | None
    graph_version: str
    login_config_id: str | None
    scopes: str | None
    is_enabled: bool


@dataclass
class SerperSettings:
    is_enabled: bool
    has_api_key: bool
    gl: str
    hl: str
    num: int


# ---------------------------------------------------------------------------
# Meta (app_integration_settings)
# ---------------------------------------------------------------------------

async def get_meta_settings(provider: str = PROVIDER_META_FACEBOOK) -> MetaSettings | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT provider, app_id, app_secret, public_app_url,
                   COALESCE(NULLIF(BTRIM(graph_version),''), $2::text) AS graph_version,
                   login_config_id, scopes, is_enabled
            FROM public.app_integration_settings
            WHERE provider = $1::text
            LIMIT 1
            """,
            provider, DEFAULT_GRAPH_VERSION,
        )
    return MetaSettings(**dict(row)) if row else None


async def save_meta_settings(provider: str, **fields) -> None:
    pool = get_pool()
    columns = list(fields.keys())
    placeholders = ", ".join(f"${i + 2}" for i in range(len(columns)))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns)
    async with pool.acquire() as conn:
        await conn.execute(
            f"""
            INSERT INTO public.app_integration_settings (provider, {", ".join(columns)}, updated_at)
            VALUES ($1, {placeholders}, now())
            ON CONFLICT (provider) DO UPDATE SET {updates}, updated_at = now()
            """,
            provider, *fields.values(),
        )


# ---------------------------------------------------------------------------
# Serper (app_external_api_settings) — clé chiffrée via pgcrypto
# ---------------------------------------------------------------------------

async def get_serper_settings() -> SerperSettings:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT is_enabled,
                   (NULLIF(BTRIM(api_key_ciphertext),'') IS NOT NULL) AS has_api_key,
                   COALESCE(settings,'{}'::jsonb) AS settings
            FROM public.app_external_api_settings
            WHERE provider = 'serper'
            LIMIT 1
            """,
        )
    if row is None:
        return SerperSettings(is_enabled=False, has_api_key=False, gl="fr", hl="fr", num=8)
    settings = row["settings"]
    settings = json.loads(settings) if isinstance(settings, str) else (settings or {})
    return SerperSettings(
        is_enabled=bool(row["is_enabled"]),
        has_api_key=bool(row["has_api_key"]),
        gl=str(settings.get("gl", "fr")).lower(),
        hl=str(settings.get("hl", "fr")).lower(),
        num=max(3, min(10, int(settings.get("num", 8) or 8))),
    )


async def get_serper_api_key(shared_key: str) -> str:
    """
    Déchiffre la clé Serper côté serveur (jamais renvoyée aux pages).
    Port du déchiffrement pgcrypto inverse de `armor(pgp_sym_encrypt(...))`.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            SELECT pgp_sym_decrypt(dearmor(api_key_ciphertext),
                                    COALESCE(NULLIF(token_encryption_key,''), $1::text))
            FROM public.app_external_api_settings
            WHERE provider='serper' AND NULLIF(BTRIM(api_key_ciphertext),'') IS NOT NULL
            LIMIT 1
            """,
            shared_key,
        ) or ""


async def save_serper_settings(*, api_key: str, shared_key: str, gl: str, hl: str,
                                num: int, is_enabled: bool) -> None:
    """
    Enregistre le paramétrage Serper. Une `api_key` vide CONSERVE la clé
    existante (comportement exact de l'écran d'origine : « Laisser vide pour
    conserver le token actuel »). Le pays 'world' est normalisé en 'us'.
    """
    pool = get_pool()
    normalized_gl = "us" if gl == "world" else gl
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO public.app_external_api_settings (
                provider, api_key_ciphertext, settings, token_encryption_key, is_enabled, created_at, updated_at
            )
            SELECT 'serper',
                   CASE WHEN $1::text <> ''
                        THEN armor(pgp_sym_encrypt($1::text, $2::text, 'cipher-algo=aes256'))
                        ELSE (SELECT api_key_ciphertext FROM public.app_external_api_settings WHERE provider='serper')
                   END,
                   jsonb_build_object('gl', $3::text, 'hl', $4::text, 'num', $5::int),
                   $2::text, $6::boolean, now(), now()
            ON CONFLICT (provider) DO UPDATE SET
                api_key_ciphertext = EXCLUDED.api_key_ciphertext,
                settings = EXCLUDED.settings,
                token_encryption_key = COALESCE(NULLIF(public.app_external_api_settings.token_encryption_key,''),
                                                 EXCLUDED.token_encryption_key),
                is_enabled = EXCLUDED.is_enabled,
                updated_at = now()
            """,
            api_key, shared_key, normalized_gl, hl, num, is_enabled,
        )
