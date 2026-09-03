"""Résolution centralisée de l'origine publique de l'application.

Le domaine n'est jamais recopié dans les routes métier. La valeur canonique
provient d'APP_BASE_URL (renseignée automatiquement au déploiement). Si elle
est absente ou locale, on peut dériver l'origine de l'instance via les en-têtes
X-Forwarded-* transmis par nginx.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request

from app.config import get_settings


def _clean_origin(value: str | None) -> str:
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _is_local(origin: str) -> bool:
    if not origin:
        return True
    try:
        host = (urlsplit(origin).hostname or "").lower()
    except ValueError:
        return True
    return host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _request_origin(request: Request) -> str:
    settings = get_settings()
    if settings.trust_proxy_headers:
        host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",", 1)[0].strip()
        proto = (request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip().lower()
        if not proto:
            proto = request.url.scheme
    else:
        host = request.headers.get("host", "").strip()
        proto = request.url.scheme
    if not host or any(c in host for c in ("/", "\\", "\r", "\n", "\t")):
        return ""
    if proto not in ("http", "https"):
        proto = "https" if settings.env.lower() in {"production", "prod"} else "http"
    return _clean_origin(f"{proto}://{host}")


def resolve_public_origin(request: Request, configured_origin: str | None = None) -> str:
    """Retourne l'origine publique à utiliser pour OAuth et les URLs externes.

    Priorité :
    1. origine réellement reçue du reverse proxy quand TRUST_PROXY_HEADERS=true ;
    2. APP_BASE_URL configurée au déploiement ;
    3. public_app_url historique en BDD ;
    4. origine de la requête / domaine de production en dernier recours.

    Ainsi un ancien domaine resté en BDD ne peut pas écraser le domaine de
    l'instance courante. TRUST_PROXY_HEADERS ne doit être activé que lorsque
    l'API est protégée derrière le reverse proxy de confiance.
    """
    settings = get_settings()
    request_origin = _request_origin(request)
    env_origin = _clean_origin(settings.app_base_url)
    stored_origin = _clean_origin(configured_origin)

    # Un reverse proxy termine souvent TLS puis contacte FastAPI en HTTP.
    # Si X-Forwarded-Proto est absent/mal configuré et vaut "http", il ne
    # doit JAMAIS écraser une origine publique HTTPS explicitement configurée.
    # À l'inverse, une origine HTTPS transmise par le proxy reste prioritaire,
    # ce qui permet de suivre automatiquement le domaine réel de l'instance.
    if settings.trust_proxy_headers and request_origin:
        request_scheme = (urlsplit(request_origin).scheme or "").lower()
        if request_scheme == "https":
            return request_origin
        if env_origin and not _is_local(env_origin) and urlsplit(env_origin).scheme == "https":
            return env_origin
        if stored_origin and urlsplit(stored_origin).scheme == "https":
            return stored_origin

    if env_origin and not _is_local(env_origin):
        return env_origin
    if stored_origin:
        return stored_origin
    return request_origin or env_origin or "https://socialnetwork.coppelis.com"
