"""
Dépendance FastAPI de résolution de session — port fidèle du bloc
AUTH - Préparer session / Lire session / Fusion utilisateur / Session valide ?
répliqué 43 fois dans le workflow original (Cahier technique §3.1, §4.2).

Ici, ce comportement est FACTORISÉ en une seule dépendance réutilisable
(`get_current_user` / `require_auth` / `require_admin`), corrigeant l'un
des points de dette technique identifiés dans le Cahier technique §10.2 —
c'est un choix d'architecture assumé qui n'introduit aucune régression
fonctionnelle : le comportement observable (résolution session, workspace
actif, 401/302 si non connecté) reste strictement identique.
"""
from __future__ import annotations

import json
from urllib.parse import urlencode

from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.database import get_pool, sql
from app.models.auth import AuthUser
from app.security import session_token_hash, login_url
from app.user_timezone import request_timezone_name


class AuthRequiredHTML(Exception):
    """Levée sur une route HTML sans session valide -> 302 vers /login."""
    def __init__(self, redirect_to: str):
        self.redirect_to = redirect_to


async def resolve_session(request: Request) -> AuthUser | None:
    """
    Résout la session à partir du cookie (voie principale) ou des en-têtes
    X-PG-Session-Id / X-PG-Request-Token (voie de secours pour les appels
    fetch() cross-contexte — Cahier technique §4.2).
    """
    settings = get_settings()
    raw_token = request.cookies.get(settings.session_cookie_name, "")
    session_hash = session_token_hash(raw_token) if raw_token else ""

    fallback_session_id = request.headers.get("X-PG-Session-Id", "")
    fallback_request_token = request.headers.get("X-PG-Request-Token", "")

    if not session_hash and not fallback_session_id:
        return None

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            sql("auth/session_resolve.sql"),
            session_hash, fallback_session_id, fallback_request_token,
        )

    if row is None or not row["user_id"]:
        return None

    workspaces_raw = row["workspaces"]
    workspaces = json.loads(workspaces_raw) if isinstance(workspaces_raw, str) else (workspaces_raw or [])

    return AuthUser(
        id=row["user_id"],
        email=row["email"],
        first_name=row["first_name"] or "",
        last_name=row["last_name"] or "",
        full_name=row["full_name"] or "",
        role=row["role"] or "user",
        timezone=request_timezone_name(request, (row["timezone"] if "timezone" in row else "") or "Europe/Paris"),
        is_super_admin=(row["role"] or "").lower() == "admin",
        session_id=row["session_id"] or "",
        request_token=row["request_auth_token"] or "",
        active_workspace_id=row["active_workspace_id"] or "",
        active_workspace_name=row["active_workspace_name"] or "",
        active_workspace_role=row["active_workspace_role"] or "",
        workspaces=workspaces,
    )


async def get_current_user(request: Request) -> AuthUser | None:
    """Dépendance 'douce' : ne lève jamais, retourne None si non connecté."""
    user = await resolve_session(request)
    request.state.auth_user = user
    return user


async def require_auth(request: Request) -> AuthUser:
    """
    Dépendance 'stricte' pour les routes protégées.
    - Route HTML (GET, Accept: text/html) sans session -> redirection 302 /login
      (levée comme HTTPException 307 avec Location, interceptée par un
      exception handler dédié — voir app/main.py).
    - Route API (JSON) sans session -> 401 { success:false, error:AUTH_REQUIRED }
      (enveloppe identique à l'original, Addendum §4).
    """
    user = await get_current_user(request)
    if user is not None:
        return user

    accepts_html = "text/html" in request.headers.get("accept", "")
    is_get = request.method == "GET"

    if is_get and accepts_html:
        redirect_target = str(request.url.path)
        if request.url.query:
            redirect_target += f"?{request.url.query}"
        raise AuthRequiredHTML(redirect_to=login_url(redirect_target))

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"success": False, "error": "AUTH_REQUIRED", "message": "Session expirée ou utilisateur non connecté."},
    )


async def require_admin(request: Request) -> AuthUser:
    user = await require_auth(request)
    if not user.is_super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={
            "success": False, "error": "FORBIDDEN", "message": "Accès réservé aux administrateurs.",
        })
    return user
