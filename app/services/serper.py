"""
Client Serper.dev — CORRIGÉ : la clé et les réglages sont lus depuis
`app_external_api_settings` (provider='serper'), avec la clé chiffrée en
base via pgcrypto et déchiffrée uniquement côté serveur au moment de
l'appel (comportement documenté dans l'écran Paramétrage admin :
« le token reste côté serveur et n'est jamais renvoyé dans les pages »).

Les paramètres `gl` (pays), `hl` (langue) et `num` (nombre de résultats,
borné 3–10) proviennent de la colonne jsonb `settings`.
"""
from __future__ import annotations

import httpx

from app.config import get_settings
from app.services.settings_service import get_serper_api_key, get_serper_settings

SERPER_SEARCH_URL = "https://google.serper.dev/search"
SERPER_AUTOCOMPLETE_URL = "https://google.serper.dev/autocomplete"


def _shared_key() -> str:
    """Clé de chiffrement partagée (secret d'infrastructure, jamais en page)."""
    settings = get_settings()
    return settings.token_encryption_key or settings.database_url


async def is_enabled() -> bool:
    cfg = await get_serper_settings()
    return cfg.is_enabled and cfg.has_api_key


async def _post(url: str, payload: dict) -> dict:
    api_key = await get_serper_api_key(_shared_key())
    if not api_key:
        raise RuntimeError("Clé Serper non configurée.")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers={"X-API-KEY": api_key, "Content-Type": "application/json"}, json=payload)
        resp.raise_for_status()
        return resp.json()


async def search(query: str) -> dict:
    cfg = await get_serper_settings()
    return await _post(SERPER_SEARCH_URL, {"q": query, "gl": cfg.gl, "hl": cfg.hl, "num": cfg.num})


async def autocomplete(query: str) -> dict:
    cfg = await get_serper_settings()
    return await _post(SERPER_AUTOCOMPLETE_URL, {"q": query, "gl": cfg.gl, "hl": cfg.hl})
