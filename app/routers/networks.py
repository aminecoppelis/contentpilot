"""
Routes de connexion des réseaux sociaux — Cahier technique §6.5, §7.7.
OAuth Meta/Instagram avec état anti-CSRF (Cahier technique §3.7).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Depends, Body
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.database import get_pool, sql
from app.public_origin import resolve_public_origin
from app.dependencies.auth import require_auth, require_admin
from app.security import new_oauth_state, oauth_state_hash, constant_time_eq, session_token_hash
from app.services import meta as meta_client
from app.services.crypto import encrypt_token, decrypt_token
from app.services.social_accounts import (
    fetch_accessible_account, ensure_local_workspace_link, ensure_explicit_workspace_link,
)
from app.user_timezone import format_user_datetime
from app.services.settings_service import (
    get_meta_settings, save_meta_settings,
    PROVIDER_META_FACEBOOK, PROVIDER_META_INSTAGRAM, DEFAULT_GRAPH_VERSION,
)

# Permissions minimales exigées par l'API Instagram pour lire le compte et
# publier. Le workflow d'origine utilisait cette même paire.
INSTAGRAM_DEFAULT_SCOPES = "instagram_business_basic,instagram_business_content_publish"
FACEBOOK_DEFAULT_SCOPES = "pages_show_list,pages_read_engagement,pages_manage_posts"


def _session_hash(request: Request) -> str:
    raw = request.cookies.get(get_settings().session_cookie_name, "")
    return session_token_hash(raw) if raw else ""


router = APIRouter(tags=["Networks"])
from app.templating import templates, render_fragment
logger = logging.getLogger("routers.networks")


def _network_access_list_sql(*, cursor: bool = False) -> str:
    cursor_clause = "AND ($2::timestamptz IS NULL OR (a.updated_at, a.id) < ($2::timestamptz, $3::uuid))" if cursor else ""
    return f"""
        SELECT a.id::text, a.provider, a.display_name, a.platform_account_name,
               a.external_account_id, a.external_parent_id, a.external_username,
               a.token_expires_at, a.updated_at, a.workspace_id::text AS owner_workspace_id,
               (a.workspace_id = $1::uuid) AS is_owner_workspace,
               a.is_active AS global_is_active,
               saw.is_active AS workspace_link_is_active, saw.revoked_at AS workspace_link_revoked_at,
               a.is_active AND (
                 CASE
                   WHEN saw.account_id IS NULL AND a.workspace_id = $1::uuid THEN true
                   ELSE COALESCE(saw.is_active,false) AND saw.revoked_at IS NULL
                 END
               ) AS is_active,
               COALESCE(a.metadata->>'connection_provider','') AS connection_provider,
               COALESCE(a.metadata->>'service','') AS service,
               COALESCE(a.metadata->>'token_mode','') AS token_mode
        FROM public.app_social_accounts a
        LEFT JOIN public.app_social_account_workspaces saw
          ON saw.account_id = a.id AND saw.workspace_id = $1::uuid
        WHERE a.deleted_at IS NULL
          AND (a.workspace_id = $1::uuid OR saw.account_id IS NOT NULL)
          AND (saw.revoked_at IS NULL OR saw.account_id IS NULL)
          {cursor_clause}
    """


def _normalize_buffer_platform(service: str) -> str:
    value = str(service or "").strip().lower()
    aliases = {
        "twitter": "x", "x/twitter": "x", "twitter/x": "x",
        "facebookpage": "facebook", "instagram_business": "instagram",
        "linkedinpage": "linkedin", "linkedin_profile": "linkedin",
    }
    return aliases.get(value, value or "instagram")


def _decorate_network_rows(rows, timezone_name: str, now=None) -> list[dict]:
    """Normalise les comptes pour la page initiale ET les pages incrémentales."""
    now = now or datetime.now(timezone.utc)
    accounts: list[dict] = []
    for r in rows:
        d = dict(r)
        provider = d.get("provider") or ""
        conn_provider = d.get("connection_provider") or ""
        service = (d.get("service") or "").strip()
        is_buffer = provider == "buffer" or conn_provider == "buffer"
        is_meta_direct = provider == "instagram" and conn_provider == "meta_direct"
        is_legacy_ig = provider == "instagram" and conn_provider == "meta_facebook"
        if is_buffer:
            label = "Buffer" + (f" · {service}" if service else "")
        elif is_meta_direct:
            label = "Instagram · Meta direct"
        elif is_legacy_ig:
            label = "Instagram via Facebook · ancien/non utilisé"
        elif provider == "facebook":
            label = "Facebook · Meta"
        else:
            label = "Meta"
        d["provider_label"] = label
        d["is_buffer"] = is_buffer
        d["is_legacy_instagram"] = is_legacy_ig
        username = d.get("external_username") or ""
        account_parts = [username if provider == "buffer" else (f"@{username}" if username else ""), d.get("platform_account_name") or ""]
        d["account_label"] = " · ".join(part for part in account_parts if part)
        d["reconnect_url"] = "" if (is_buffer or not d.get("is_owner_workspace")) else (
            f"/app/networks/{'facebook' if provider == 'facebook' else 'instagram'}/connect?force_reconnect=1")
        expires = d.get("token_expires_at")
        d["token_expired"] = bool(provider == "instagram" and expires and expires <= now)
        d["token_temporary"] = bool(provider == "instagram" and not d["token_expired"] and d.get("token_mode") in ("short_lived", "short_lived_pending_exchange"))
        d["token_expires_label"] = format_user_datetime(expires, timezone_name, "%d/%m/%Y")
        updated = d.get("updated_at")
        d["updated_label"] = format_user_datetime(updated, timezone_name)
        accounts.append(d)
    return accounts


@router.get("/networks", response_class=HTMLResponse)
async def get_networks(request: Request, user=Depends(require_auth),
                        connected: str | None = None, oauth_error: str | None = None,
                        oauth_provider: str | None = None, oauth_stage: str | None = None,
                        oauth_warning: str | None = None):
    """Port fidèle de "HTML - Mes réseaux" (libellés de provider, états de jeton,
    cibles de partage, notice OAuth)."""
    from datetime import datetime, timezone

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            _network_access_list_sql() + " ORDER BY a.updated_at DESC NULLS LAST, a.id DESC LIMIT 21",
            user.active_workspace_id,
        )
        total = await conn.fetchval(
            "SELECT count(*)::int FROM (" + _network_access_list_sql() + ") network_access",
            user.active_workspace_id,
        )

    has_more = len(rows) > 20
    first_page = rows[:20]
    accounts = _decorate_network_rows(first_page, user.timezone)
    next_cursor_at = first_page[-1]["updated_at"].isoformat() if first_page and first_page[-1]["updated_at"] else ""
    next_cursor_id = first_page[-1]["id"] if first_page else ""

    share_targets = [
        {"id": w.id, "name": w.name} for w in user.workspaces if w.id != user.active_workspace_id
    ]

    # Notice OAuth (port exact du bloc `notice` de l'original)
    provider_label = {"facebook": "Facebook", "instagram": "Instagram", "buffer": "Buffer"}.get(
        (oauth_provider or "").lower(), "réseau")
    notice, notice_type = "", "ok"
    if connected:
        notice = f"{connected} compte(s) {provider_label} connecté(s) ou actualisé(s)."
        if oauth_warning:
            notice += f" Diagnostic {provider_label} : {oauth_warning}"
            notice_type = "warn"
    elif oauth_error:
        stage = f" · étape {oauth_stage}" if oauth_stage else ""
        notice = f"Connexion {provider_label} impossible{stage} : {oauth_error}"
        notice_type = "err"

    return templates.TemplateResponse(request, "networks/list.html", {
        "auth_user": user, "active_nav": "networks",
        "accounts": accounts, "total": int(total or 0), "share_targets": share_targets,
        "has_more": has_more, "next_cursor_at": next_cursor_at, "next_cursor_id": next_cursor_id,
        "notice": notice, "notice_type": notice_type,
    })


async def _start_oauth(request: Request, user, provider: str, force_reconnect: bool = False):
    """
    Démarre le flux OAuth. ATTENTION : Facebook et Instagram utilisent deux
    points d'autorisation TOTALEMENT différents, avec des App ID différents.

      Facebook  -> https://www.facebook.com/{version}/dialog/oauth
                   (App ID de l'app Facebook ; `config_id` si Facebook Login
                   for Business est configuré, sinon `scope`)

      Instagram -> https://www.instagram.com/oauth/authorize
                   (App ID *Instagram*, distinct de celui de Facebook ;
                   paramètre enable_fb_login=0 pour forcer Instagram Login direct)

    Utiliser l'App ID Instagram sur le dialogue facebook.com provoque
    exactement l'erreur « ID d'app non valide » renvoyée par Meta.
    """
    provider_key = PROVIDER_META_INSTAGRAM if provider == "instagram" else PROVIDER_META_FACEBOOK
    settings = await get_meta_settings(provider_key)

    def fail(message: str, stage: str) -> RedirectResponse:
        return RedirectResponse(
            f"/app/networks?{urlencode({'oauth_provider': provider, 'oauth_stage': stage, 'oauth_error': message[:900]})}",
            status_code=302)

    if settings is None or not settings.is_enabled:
        return fail(f"L'intégration {provider} n'est pas activée dans la configuration Meta.", "config_missing")

    app_id = str(settings.app_id or "").strip()
    if not app_id.isdigit():
        return fail(
            f"App ID {provider} invalide ou absent. Vérifie la configuration Meta : "
            f"l'App ID Instagram est différent de l'App ID Facebook.", "config_invalid")
    if not str(settings.app_secret or "").strip():
        return fail(f"App Secret {provider} absent.", "config_invalid")

    # L'URI de redirection doit correspondre EXACTEMENT à celle déclarée dans Meta.
    public_base = resolve_public_origin(request, settings.public_app_url).rstrip("/")
    redirect_uri = f"{public_base}/app/networks/{provider}/callback"

    state = new_oauth_state()
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO public.app_social_oauth_states
                (user_id, workspace_id, state_hash, redirect_uri, provider, expires_at)
            VALUES ($1::uuid,$2::uuid,$3,$4,$5, now() + interval '10 minutes')
            """,
            user.id, user.active_workspace_id, oauth_state_hash(state), redirect_uri, provider,
        )

    if provider == "instagram":
        scope = (settings.scopes or "").strip() or INSTAGRAM_DEFAULT_SCOPES
        scopes = [s.strip() for s in scope.split(",") if s.strip()]
        for required in ("instagram_business_basic", "instagram_business_content_publish"):
            if required not in scopes:
                return fail(f"La permission {required} est absente de la configuration Instagram.",
                            "config_invalid")
        params = {
            "enable_fb_login": "0",           # force Instagram Login direct
            "client_id": app_id,              # App ID INSTAGRAM
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": ",".join(scopes),
            "state": state,
        }
        if force_reconnect:
            params["force_reauth"] = "true"
        return RedirectResponse(
            "https://www.instagram.com/oauth/authorize?" + urlencode(params), status_code=302)

    # --- Facebook ---
    version = (settings.graph_version or DEFAULT_GRAPH_VERSION).strip().strip("/")
    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
        "return_scopes": "true",
    }
    # Avec Facebook Login for Business, les permissions viennent de la config Meta ;
    # sans Configuration ID, on repasse par le parcours OAuth classique avec scope.
    config_id = str(settings.login_config_id or "").strip()
    if config_id:
        params["config_id"] = config_id
    else:
        params["scope"] = (settings.scopes or "").strip() or FACEBOOK_DEFAULT_SCOPES
    if force_reconnect:
        params["auth_type"] = "rerequest"

    return RedirectResponse(
        f"https://www.facebook.com/{version}/dialog/oauth?" + urlencode(params), status_code=302)


@router.get("/networks/facebook/connect")
async def get_facebook_connect(request: Request, force_reconnect: int = 0, user=Depends(require_auth)):
    return await _start_oauth(request, user, "facebook", force_reconnect=bool(force_reconnect))


@router.get("/networks/instagram/connect")
async def get_instagram_connect(request: Request, force_reconnect: int = 0, user=Depends(require_auth)):
    return await _start_oauth(request, user, "instagram", force_reconnect=bool(force_reconnect))


async def _handle_oauth_callback(
    request: Request, provider: str, code: str | None, state: str | None,
    oauth_error: str | None = None, oauth_error_description: str | None = None,
):
    """Termine OAuth en conservant le contrat fonctionnel du V90.

    Toutes les erreurs Meta/BDD sont converties en diagnostic visible dans
    Mes réseaux ; aucune exception attendue ne doit finir en simple HTTP 500.
    """
    def fail(message: str, stage: str) -> RedirectResponse:
        params = {
            "oauth_provider": provider,
            "oauth_stage": stage,
            "oauth_error": str(message or "Erreur OAuth inconnue.")[:900],
        }
        return RedirectResponse(f"/app/networks?{urlencode(params)}", status_code=302)

    if oauth_error:
        return fail(oauth_error_description or oauth_error, "provider_denied")
    if not code or not state:
        return fail("Code ou state OAuth manquant dans le callback.", "callback_invalid")

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            state_row = await conn.fetchrow(
                "SELECT user_id::text, workspace_id::text, redirect_uri "
                "FROM public.app_social_oauth_states "
                "WHERE state_hash=$1 AND provider=$2 AND expires_at > now() LIMIT 1",
                oauth_state_hash(state), provider,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Lecture de l'état OAuth impossible (%s)", provider)
        return fail(f"Lecture de l'état OAuth impossible : {exc}", "state_lookup")

    if state_row is None:
        return fail("État OAuth invalide, expiré ou déjà consommé.", "state_invalid")

    redirect_uri = str(state_row["redirect_uri"] or "").strip()
    if not redirect_uri:
        settings = await get_meta_settings(
            PROVIDER_META_INSTAGRAM if provider == "instagram" else PROVIDER_META_FACEBOOK
        )
        public_base = resolve_public_origin(request, settings.public_app_url if settings else None)
        redirect_uri = f"{public_base}/app/networks/{provider}/callback"

    try:
        if provider == "instagram":
            token_data = await meta_client.exchange_instagram_code(code, redirect_uri)
            short_token = str(token_data.get("access_token") or "").strip()
            if not short_token:
                message = (token_data.get("error_message")
                           or (token_data.get("error") or {}).get("message")
                           or "Échange du code Instagram impossible.")
                return fail(message, "code_exchange")

            # La conversion longue durée peut échouer temporairement. Comme le V90,
            # on conserve alors le jeton court et le cron retentera plus tard.
            token_warning = ""
            token_mode = "long_lived"
            try:
                long_lived = await meta_client.exchange_instagram_long_lived(short_token)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Conversion du jeton Instagram longue durée impossible")
                long_lived = {}
                token_warning = str(exc)
            access_token = str(long_lived.get("access_token") or short_token).strip()
            if long_lived.get("access_token"):
                expires_in = int(long_lived.get("expires_in") or 60 * 24 * 3600)
            else:
                token_mode = "short_lived_pending_exchange"
                expires_in = int(token_data.get("expires_in") or 3600)
                raw_error = long_lived.get("error") if isinstance(long_lived, dict) else None
                if not token_warning and raw_error:
                    token_warning = raw_error.get("message") if isinstance(raw_error, dict) else str(raw_error)
        else:
            token_data = await meta_client.exchange_code_for_token(code, redirect_uri)
            short_token = str(token_data.get("access_token") or "").strip()
            if not short_token:
                message = ((token_data.get("error") or {}).get("message")
                           or "Échange du code Facebook impossible.")
                return fail(message, "code_exchange")
            long_lived = await meta_client.exchange_for_long_lived_token(short_token)
            access_token = str(long_lived.get("access_token") or short_token).strip()
            expires_in = int(long_lived.get("expires_in") or 60 * 24 * 3600)
            token_warning = ""
            token_mode = "long_lived"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Échange OAuth impossible (%s)", provider)
        return fail(f"Échange du jeton impossible : {exc}", "code_exchange")

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(60, expires_in))

    if provider == "facebook":
        try:
            pages_response = await meta_client.list_facebook_pages(access_token)
            pages = pages_response.get("data", []) if isinstance(pages_response, dict) else []
            async with pool.acquire() as conn:
                async with conn.transaction():
                    if pages:
                        await conn.executemany(
                            """
                            INSERT INTO public.app_social_oauth_candidates (
                                user_id, workspace_id, provider, display_name, platform_account_name,
                                external_account_id, token_ciphertext, token_expires_at, metadata
                            ) VALUES ($1::uuid,$2::uuid,'facebook',$3,$3,$4,$5,$6::timestamptz,$7)
                            """,
                            [(
                                state_row["user_id"], state_row["workspace_id"], p.get("name", ""),
                                p.get("id", ""), encrypt_token(p.get("access_token", access_token)),
                                expires_at, json.dumps({"connection_provider": "meta_facebook"}),
                            ) for p in pages if p.get("id")],
                        )
                    await conn.execute(
                        "DELETE FROM public.app_social_oauth_states WHERE state_hash=$1::text",
                        oauth_state_hash(state))
            return RedirectResponse(
                f"/app/networks?oauth_provider=facebook&candidates={len(pages)}", status_code=302)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Sauvegarde des candidats Facebook impossible")
            return fail(f"Sauvegarde Facebook impossible : {exc}", "database_save")

    # Instagram Login direct : on résout d'abord l'identité canonique puis on
    # fait un UPSERT workspace/provider/external_account_id. Cela permet une
    # reconnexion du même compte sans violation d'unicité PostgreSQL.
    try:
        identity = await meta_client.get_instagram_canonical_identity(access_token)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Lecture de l'identité Instagram impossible")
        return fail(f"Lecture du compte Instagram impossible : {exc}", "identity_lookup")

    identity_error = identity.get("error") if isinstance(identity, dict) else None
    external_account_id = str((identity or {}).get("user_id") or (identity or {}).get("id") or "").strip()
    username = str((identity or {}).get("username") or "").strip()
    if not external_account_id:
        message = (identity_error.get("message") if isinstance(identity_error, dict) else None) or \
                  "Instagram n'a retourné aucun user_id canonique."
        return fail(message, "identity_lookup")

    metadata = {
        "connection_provider": "meta_direct",
        "instagram_direct": True,
        "token_mode": token_mode,
        "oauth_redirect_uri": redirect_uri,
    }
    if token_warning:
        metadata["token_warning"] = token_warning[:900]

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Verrou transactionnel stable : évite deux créations simultanées du
                # même compte sans dépendre de la présence d'un index unique hérité de n8n.
                lock_key = f"instagram:{state_row['workspace_id']}:{external_account_id}"
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1::text))", lock_key)
                existing_account_id = await conn.fetchval(
                    """
                    SELECT id::text
                    FROM public.app_social_accounts
                    WHERE workspace_id=$1::uuid AND provider='instagram'
                      AND external_account_id=$2::text AND deleted_at IS NULL
                    ORDER BY updated_at DESC NULLS LAST, created_at DESC
                    LIMIT 1
                    FOR UPDATE
                    """,
                    state_row["workspace_id"], external_account_id,
                )
                if existing_account_id:
                    account_row = await conn.fetchrow(
                        """
                        UPDATE public.app_social_accounts
                        SET user_id=$2::uuid, display_name=$3, platform_account_name=$3,
                            external_username=$4, token_ciphertext=$5,
                            token_expires_at=$6::timestamptz,
                            metadata=COALESCE(metadata,'{}'::jsonb) || $7::jsonb,
                            is_active=true, deleted_at=NULL, updated_at=now()
                        WHERE id=$1::uuid
                        RETURNING id::text AS account_id
                        """,
                        existing_account_id, state_row["user_id"], username or "Instagram",
                        username, encrypt_token(access_token), expires_at, json.dumps(metadata),
                    )
                else:
                    account_row = await conn.fetchrow(
                        """
                        INSERT INTO public.app_social_accounts (
                            user_id, workspace_id, provider, display_name, platform_account_name,
                            external_account_id, external_username, token_ciphertext, token_expires_at,
                            metadata, is_active, deleted_at, updated_at
                        ) VALUES (
                            $1::uuid,$2::uuid,'instagram',$3,$3,$4,$5,$6,$7::timestamptz,$8::jsonb,true,NULL,now()
                        )
                        RETURNING id::text AS account_id
                        """,
                        state_row["user_id"], state_row["workspace_id"],
                        username or "Instagram", external_account_id, username,
                        encrypt_token(access_token), expires_at, json.dumps(metadata),
                    )
                await ensure_local_workspace_link(
                    conn, account_row["account_id"], state_row["workspace_id"], state_row["user_id"]
                )
                await conn.execute(
                    "DELETE FROM public.app_social_oauth_states WHERE state_hash=$1::text",
                    oauth_state_hash(state))
    except Exception as exc:  # noqa: BLE001
        logger.exception("UPSERT du compte Instagram impossible")
        return fail(f"Enregistrement du compte Instagram impossible : {exc}", "database_upsert")

    params = {"oauth_provider": "instagram", "connected": "1"}
    if token_warning:
        params["oauth_warning"] = "Compte connecté avec un jeton temporaire ; la conversion longue durée sera retentée automatiquement."
    return RedirectResponse(f"/app/networks?{urlencode(params)}", status_code=302)


@router.get("/networks/facebook/callback")
async def get_facebook_callback(
    request: Request, code: str | None = None, state: str | None = None,
    error: str | None = None, error_description: str | None = None,
):
    return await _handle_oauth_callback(request, "facebook", code, state, error, error_description)


@router.get("/networks/instagram/callback")
async def get_instagram_callback(
    request: Request, code: str | None = None, state: str | None = None,
    error: str | None = None, error_description: str | None = None,
):
    return await _handle_oauth_callback(request, "instagram", code, state, error, error_description)


@router.post("/networks/action")
async def post_networks_action(payload: dict = Body(...), user=Depends(require_auth)):
    """Actions de Mes réseaux, avec la même règle multi-workspace partout.

    ``app_social_accounts`` garde le token global. Le lien du workspace est
    activé/désactivé dans ``app_social_account_workspaces``. Un partage ne
    duplique donc jamais le token OAuth.
    """
    pool = get_pool()
    account_id = str(payload.get("id") or "").strip()
    action = str(payload.get("action") or "").strip().lower()
    if not account_id or not action:
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR",
                             "message": "Compte ou action manquant."}, status_code=422)

    async with pool.acquire() as conn:
      async with conn.transaction():
        account = await fetch_accessible_account(conn, account_id, user.active_workspace_id)
        if account is None:
            return JSONResponse({"success": False, "error": "NOT_FOUND",
                                 "message": "Compte introuvable dans ce workspace."}, status_code=404)

        # Les anciens comptes créés avant le modèle multi-workspace n'ont pas
        # forcément encore de lien local. On le matérialise avant une action.
        if account["is_owner_workspace"] and account["workspace_link_is_active"] is None:
            await ensure_local_workspace_link(conn, account_id, user.active_workspace_id, user.id)

        if action == "toggle":
            row = await conn.fetchrow(
                """
                UPDATE public.app_social_account_workspaces
                SET is_active = NOT COALESCE(is_active,true), revoked_at=NULL, updated_at=now()
                WHERE account_id=$1::uuid AND workspace_id=$2::uuid
                RETURNING is_active
                """,
                account_id, user.active_workspace_id,
            )
            if row is None:
                return JSONResponse({"success": False, "error": "NOT_FOUND",
                                     "message": "Lien workspace introuvable."}, status_code=404)
            effective = bool(account["global_is_active"]) and bool(row["is_active"])
            return JSONResponse({"success": True, "data": {"account": {"is_active": effective}},
                                 "account": {"is_active": effective}})

        if action == "delete":
            if not account["is_owner_workspace"]:
                return JSONResponse({
                    "success": False, "error": "FORBIDDEN",
                    "message": "Ce compte appartient à un autre workspace. Utilise « Retirer de ce workspace ».",
                }, status_code=403)
            await conn.execute(
                "UPDATE public.app_social_accounts SET deleted_at=now(), is_active=false, updated_at=now() "
                "WHERE id=$1::uuid", account_id)
            await conn.execute(
                """
                UPDATE public.app_social_account_workspaces
                SET is_active=false, revoked_at=now(), updated_at=now()
                WHERE account_id=$1::uuid
                """, account_id)
            return JSONResponse({"success": True, "message": "Connexion supprimée."})

        if action == "remove_workspace":
            if account["is_owner_workspace"]:
                return JSONResponse({
                    "success": False, "error": "OWNER_WORKSPACE",
                    "message": "Le workspace d'origine ne peut pas retirer sa propre connexion. Désactive-la ou supprime-la.",
                }, status_code=409)
            result = await conn.execute(
                """
                UPDATE public.app_social_account_workspaces
                SET is_active=false, revoked_at=now(), updated_at=now()
                WHERE account_id=$1::uuid AND workspace_id=$2::uuid
                """,
                account_id, user.active_workspace_id,
            )
            if result.endswith(" 0"):
                return JSONResponse({"success": False, "error": "NOT_FOUND",
                                     "message": "Lien workspace introuvable."}, status_code=404)
            return JSONResponse({"success": True, "message": "Compte retiré de ce workspace."})

        if action == "share":
            if not account["is_owner_workspace"]:
                return JSONResponse({
                    "success": False, "error": "FORBIDDEN",
                    "message": "Seul le workspace d'origine peut partager cette connexion.",
                }, status_code=403)
            target = str(payload.get("target_workspace_id") or "").strip()
            allowed = bool(target) and target != user.active_workspace_id and any(w.id == target for w in user.workspaces)
            if not allowed:
                return JSONResponse({"success": False, "error": "FORBIDDEN",
                                     "message": "Workspace cible non autorisé."}, status_code=403)
            await ensure_explicit_workspace_link(conn, account_id, target, user.id)
            return JSONResponse({"success": True, "message": "Compte partagé."})

        if action == "rename":
            if not account["is_owner_workspace"]:
                return JSONResponse({
                    "success": False, "error": "FORBIDDEN",
                    "message": "Seul le workspace d'origine peut renommer cette connexion.",
                }, status_code=403)
            display_name = str(payload.get("display_name") or "").strip()[:120]
            if not display_name:
                return JSONResponse({"success": False, "error": "VALIDATION_ERROR",
                                     "message": "Le nom ne peut pas être vide."}, status_code=422)
            row = await conn.fetchrow(
                "UPDATE public.app_social_accounts SET display_name=$2, updated_at=now() "
                "WHERE id=$1::uuid AND workspace_id=$3::uuid AND deleted_at IS NULL RETURNING id",
                account_id, display_name, user.active_workspace_id)
            if row is None:
                return JSONResponse({"success": False, "error": "NOT_FOUND",
                                     "message": "Connexion introuvable dans le workspace d'origine."}, status_code=404)
            return JSONResponse({"success": True, "message": "Nom mis à jour."})

    return JSONResponse({"success": False, "error": "INVALID_ACTION", "message": "Action inconnue."}, status_code=400)


@router.post("/networks/buffer/save")
async def post_buffer_save(payload: dict = Body(...), user=Depends(require_auth)):
    """Ajoute/modifie un canal Buffer en validant à la fois la clé et le Channel ID."""
    from app.services.buffer import test_user_access, get_channel

    display_name = str(payload.get("display_name", "")).strip()
    api_key = str(payload.get("api_key", "")).strip()
    channel_id = str(payload.get("channel_id", "")).strip()
    account_id = str(payload.get("account_id") or "").strip() or None

    if not display_name or not channel_id or (not api_key and not account_id):
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR",
                             "message": "Nom, clé API et Channel ID sont requis."}, status_code=422)

    pool = get_pool()
    existing = None
    effective_api_key = api_key
    if account_id:
        async with pool.acquire() as conn:
            existing = await fetch_accessible_account(conn, account_id, user.active_workspace_id)
        if existing is None:
            return JSONResponse({"success": False, "error": "NOT_FOUND",
                                 "message": "Compte Buffer introuvable."}, status_code=404)
        if not existing["is_owner_workspace"]:
            return JSONResponse({"success": False, "error": "FORBIDDEN",
                                 "message": "Les identifiants Buffer ne peuvent être modifiés que depuis le workspace d'origine."}, status_code=403)
        if not effective_api_key:
            effective_api_key = decrypt_token(existing["token_ciphertext"])

    try:
        auth_resp = await test_user_access(effective_api_key)
        if auth_resp.status_code >= 400:
            raise ValueError("Clé Buffer invalide ou refusée par l'API.")
        channel_resp = await get_channel(effective_api_key, channel_id)
        if channel_resp.status_code >= 400:
            raise ValueError("Channel ID Buffer invalide ou inaccessible avec cette clé.")
        channel_data = channel_resp.json() if channel_resp.content else {}
        if isinstance(channel_data, dict) and channel_data.get("errors"):
            first = channel_data["errors"][0] if channel_data["errors"] else {}
            raise ValueError(str(first.get("message") or "Channel ID Buffer invalide."))
        channel = ((channel_data.get("data") or {}).get("channel") or {}) if isinstance(channel_data, dict) else {}
        service = str(channel.get("service") or "").strip().lower()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"success": False, "error": "BUFFER_AUTH_FAILED",
                             "message": str(exc) or "Validation Buffer impossible."}, status_code=422)

    metadata_patch = {
        "connection_provider": "buffer",
        "channel_id": channel_id,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    if service:
        metadata_patch["service"] = service

    async with pool.acquire() as conn:
      async with conn.transaction():
        if account_id:
            # L'UI ne permet l'édition que depuis le workspace propriétaire.
            # On refait néanmoins le contrôle dans l'UPDATE pour éviter qu'un
            # compte supprimé/partagé ne soit modifié entre le test API et la sauvegarde.
            duplicate_id = await conn.fetchval(
                """
                SELECT id::text FROM public.app_social_accounts
                WHERE workspace_id=$1::uuid AND provider='buffer'
                  AND external_account_id=$2 AND deleted_at IS NULL AND id<>$3::uuid
                LIMIT 1
                """,
                user.active_workspace_id, channel_id, account_id,
            )
            if duplicate_id:
                return JSONResponse({
                    "success": False, "error": "DUPLICATE_CHANNEL",
                    "message": "Ce Channel ID Buffer est déjà enregistré dans ce workspace.",
                }, status_code=409)
            if api_key:
                row = await conn.fetchrow(
                    """
                    UPDATE public.app_social_accounts
                    SET display_name=$2, external_account_id=$3, token_ciphertext=$4,
                        metadata=COALESCE(metadata,'{}'::jsonb) || $5::jsonb,
                        is_active=true, deleted_at=NULL, updated_at=now()
                    WHERE id=$1::uuid AND workspace_id=$6::uuid
                      AND provider='buffer' AND deleted_at IS NULL
                    RETURNING id::text
                    """,
                    account_id, display_name, channel_id, encrypt_token(api_key),
                    json.dumps(metadata_patch), user.active_workspace_id)
            else:
                row = await conn.fetchrow(
                    """
                    UPDATE public.app_social_accounts
                    SET display_name=$2, external_account_id=$3,
                        metadata=COALESCE(metadata,'{}'::jsonb) || $4::jsonb,
                        is_active=true, deleted_at=NULL, updated_at=now()
                    WHERE id=$1::uuid AND workspace_id=$5::uuid
                      AND provider='buffer' AND deleted_at IS NULL
                    RETURNING id::text
                    """,
                    account_id, display_name, channel_id, json.dumps(metadata_patch),
                    user.active_workspace_id)
            if row is None:
                return JSONResponse({"success": False, "error": "NOT_FOUND",
                                     "message": "Compte Buffer introuvable dans ce workspace."}, status_code=404)
            saved_account_id = row["id"]
        else:
            # Parité n8n sans dépendre d'un index UNIQUE préexistant :
            # on sérialise les créations concurrentes d'un même Channel ID,
            # puis on réactive/met à jour la ligne existante ou on l'insère.
            # Cela fonctionne aussi bien sur une base issue de n8n que sur une
            # installation Python neuve créée uniquement avec migrations/001_init.sql.
            lock_key = f"buffer:{user.active_workspace_id}:{channel_id}"
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1::text))", lock_key)
            existing_buffer_id = await conn.fetchval(
                """
                SELECT id::text
                FROM public.app_social_accounts
                WHERE workspace_id=$1::uuid AND provider='buffer'
                  AND external_account_id=$2 AND deleted_at IS NULL
                ORDER BY updated_at DESC NULLS LAST, created_at DESC
                LIMIT 1
                FOR UPDATE
                """,
                user.active_workspace_id, channel_id,
            )
            if existing_buffer_id:
                row = await conn.fetchrow(
                    """
                    UPDATE public.app_social_accounts
                    SET user_id=$2::uuid, display_name=$3, token_ciphertext=$4,
                        metadata=COALESCE(metadata,'{}'::jsonb) || $5::jsonb,
                        is_active=true, deleted_at=NULL, updated_at=now()
                    WHERE id=$1::uuid AND workspace_id=$6::uuid AND provider='buffer'
                    RETURNING id::text
                    """,
                    existing_buffer_id, user.id, display_name, encrypt_token(api_key),
                    json.dumps(metadata_patch), user.active_workspace_id,
                )
            else:
                row = await conn.fetchrow(
                    """
                    INSERT INTO public.app_social_accounts (
                        user_id, workspace_id, provider, display_name, external_account_id,
                        token_ciphertext, metadata, is_active, deleted_at, updated_at
                    ) VALUES ($1::uuid,$2::uuid,'buffer',$3,$4,$5,$6::jsonb,true,NULL,now())
                    RETURNING id::text
                    """,
                    user.id, user.active_workspace_id, display_name, channel_id,
                    encrypt_token(api_key), json.dumps(metadata_patch),
                )
            saved_account_id = row["id"]
        await ensure_local_workspace_link(conn, saved_account_id, user.active_workspace_id, user.id)

    return JSONResponse({"success": True, "message": "Accès Buffer enregistré.",
                         "data": {"account_id": saved_account_id, "service": service}})


@router.get("/networks/meta/config", response_class=HTMLResponse)
async def get_meta_config(request: Request, user=Depends(require_admin),
                           success: str | None = None, error: str | None = None):
    facebook = await get_meta_settings(PROVIDER_META_FACEBOOK)
    instagram = await get_meta_settings(PROVIDER_META_INSTAGRAM)
    return templates.TemplateResponse(request, "networks/meta_config.html", {
        "auth_user": user, "active_nav": "networks",
        "facebook": facebook, "instagram": instagram,
        "resolved_public_app_url": resolve_public_origin(request, facebook.public_app_url if facebook else None),
        "default_graph_version": DEFAULT_GRAPH_VERSION,
        "notice": success or error, "notice_error": bool(error),
    })


@router.post("/networks/meta/config/save")
async def post_meta_config_save(request: Request, user=Depends(require_admin)):
    """
    Port fidèle de "BDD - Enregistrer configuration Meta Admin" : un SEUL
    formulaire enregistre les DEUX providers ('meta_facebook' et
    'meta_instagram') en une transaction, avec validations strictes
    (URL HTTPS, format vX.Y de la version Graph, App IDs numériques,
    secret obligatoire si l'App ID change, configuration complète si activée).
    Un secret laissé vide conserve l'ancien.
    """
    form = await request.form()
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            sql("admin/save_meta_config.sql"),
            _session_hash(request),
            request.headers.get("X-PG-Session-Id") or None,
            request.headers.get("X-PG-Request-Token") or None,
            resolve_public_origin(request, str(form.get("public_app_url", ""))),
            str(form.get("graph_version", DEFAULT_GRAPH_VERSION)),
            str(form.get("facebook_app_id", "")),
            str(form.get("facebook_app_secret", "")),
            str(form.get("facebook_login_config_id", "")),
            str(form.get("facebook_scopes", "") or FACEBOOK_DEFAULT_SCOPES),
            form.get("facebook_enabled") in ("1", "on", "true"),
            str(form.get("instagram_app_id", "")),
            str(form.get("instagram_app_secret", "")),
            str(form.get("instagram_scopes", "") or INSTAGRAM_DEFAULT_SCOPES),
            form.get("instagram_enabled") in ("1", "on", "true"),
        )

    if row and row["success"]:
        # "Enregistrer et tester" : enchaîne sur le parcours OAuth du provider choisi
        after_save = str(form.get("after_save", "")).strip()
        if after_save in ("facebook", "instagram"):
            return RedirectResponse(f"/app/networks/{after_save}/connect", status_code=302)
        return RedirectResponse(
            f"/app/networks/meta/config?{urlencode({'success': row['message']})}", status_code=302)

    message = row["message"] if row else "Enregistrement impossible."
    return RedirectResponse(f"/app/networks/meta/config?{urlencode({'error': message})}", status_code=302)


@router.get("/networks/quota")
async def get_networks_quota(account_id: str, user=Depends(require_auth)):
    """Port du flux n8n V90 de lecture des publications restantes Buffer."""
    pool = get_pool()
    async with pool.acquire() as conn:
        account = await fetch_accessible_account(conn, account_id, user.active_workspace_id, active_only=True)

    if not account:
        return JSONResponse({
            "success": False, "available": False, "quota_kind": "unavailable",
            "message": "Compte réseau introuvable dans le workspace actif.",
        })
    if account["provider"] != "buffer":
        return JSONResponse({
            "success": False, "available": False, "quota_kind": "unavailable",
            "provider": str(account["provider"] or ""),
            "message": "Compteur non disponible pour ce réseau.",
        })

    from app.services.buffer import get_queue, get_scheduled_queue

    metadata = account["metadata"] or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError):
            metadata = {}
    channel_id = str(
        (metadata or {}).get("channel_id")
        or account["external_parent_id"]
        or account["external_account_id"]
        or ""
    ).removeprefix("buffer:").strip()
    if not channel_id:
        return JSONResponse({
            "success": False, "available": False, "quota_kind": "unavailable",
            "provider": "buffer", "message": "Channel ID Buffer manquant.",
        })

    api_key = decrypt_token(account["token_ciphertext"])
    resp = await get_queue(api_key, channel_id)
    try:
        body = resp.json()
    except Exception:
        body = {}
    errors = body.get("errors") if isinstance(body, dict) else []
    errors = errors if isinstance(errors, list) else []
    error_message = " · ".join(
        str((e or {}).get("message") if isinstance(e, dict) else e or "").strip()
        for e in errors
        if str((e or {}).get("message") if isinstance(e, dict) else e or "").strip()
    )
    data = body.get("data") if isinstance(body, dict) and isinstance(body.get("data"), dict) else {}
    raw_limits = data.get("dailyPostingLimits")
    limits = raw_limits if isinstance(raw_limits, list) else ([raw_limits] if isinstance(raw_limits, dict) else [])
    item = next((v for v in limits if str((v or {}).get("channelId") or "") == channel_id), None)
    if item is None and limits:
        item = limits[0]

    def _number(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    sent = _number((item or {}).get("sent"), 0.0)
    scheduled = _number((item or {}).get("scheduled"), 0.0)
    raw_limit = (item or {}).get("limit")
    try:
        limit = max(0.0, float(raw_limit)) if raw_limit not in (None, "") else None
    except (TypeError, ValueError):
        limit = None
    available = resp.status_code < 400 and item is not None and not error_message
    remaining = max(0.0, limit - sent - scheduled) if available and limit is not None else None
    daily = {
        "success": available,
        "available": available,
        "account_id": str(account_id),
        "provider": "buffer",
        "quota_kind": "daily_posting_limit",
        "scope": "rolling_24_hours",
        "sent": int(sent) if sent.is_integer() else sent,
        "scheduled": int(scheduled) if scheduled.is_integer() else scheduled,
        "used": int(sent + scheduled) if (sent + scheduled).is_integer() else sent + scheduled,
        "total": (int(limit) if limit is not None and limit.is_integer() else limit),
        "remaining": (int(remaining) if remaining is not None and remaining.is_integer() else remaining),
        "unlimited": bool(available and limit is None),
        "is_at_limit": bool((item or {}).get("isAtLimit")) or bool(limit is not None and remaining is not None and remaining <= 0),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "message": (
            "Limite de publication du canal Buffer sur une période de 24 h."
            if available and limit is not None
            else "Buffer ne signale aucune limite de publication chiffrée pour ce canal sur 24 h."
            if available
            else error_message or (
                "Buffer n’a retourné aucune limite pour ce canal." if item is None
                else f"Réponse Buffer invalide (HTTP {resp.status_code})."
            )
        ),
    }

    channel = data.get("channel") if isinstance(data.get("channel"), dict) else {}
    organization_id = str(channel.get("organizationId") or "").strip()
    organizations = ((data.get("account") or {}).get("organizations")
                     if isinstance(data.get("account"), dict) else [])
    organizations = organizations if isinstance(organizations, list) else []
    organization = next((v for v in organizations if str((v or {}).get("id") or "") == organization_id), None)
    raw_queue_limit = ((organization or {}).get("limits") or {}).get("scheduledPosts")
    try:
        queue_limit = max(0, int(float(raw_queue_limit))) if raw_queue_limit not in (None, "") else None
    except (TypeError, ValueError):
        queue_limit = None

    queue = {
        "available": False, "scheduled": None, "total": queue_limit, "remaining": None,
        "exact": False, "has_more": False, "is_at_limit": False,
        "is_paused": bool(channel.get("isQueuePaused")),
        "channel_locked": bool(channel.get("isLocked")),
        "message": "La limite de file d’attente Buffer n’a pas pu être déterminée pour ce canal.",
    }
    if available and organization_id and queue_limit is not None:
        queue_resp = await get_scheduled_queue(
            api_key, channel_id=channel_id, organization_id=organization_id,
            page_size=max(1, min(5000, queue_limit + 1)),
        )
        try:
            queue_body = queue_resp.json()
        except Exception:
            queue_body = {}
        queue_errors = queue_body.get("errors") if isinstance(queue_body, dict) else []
        queue_errors = queue_errors if isinstance(queue_errors, list) else []
        queue_error = " · ".join(
            str((e or {}).get("message") if isinstance(e, dict) else e or "").strip()
            for e in queue_errors
            if str((e or {}).get("message") if isinstance(e, dict) else e or "").strip()
        )
        queue_data = queue_body.get("data") if isinstance(queue_body, dict) and isinstance(queue_body.get("data"), dict) else {}
        posts = queue_data.get("posts") if isinstance(queue_data.get("posts"), dict) else None
        edges = posts.get("edges") if posts and isinstance(posts.get("edges"), list) else []
        has_more = bool(((posts or {}).get("pageInfo") or {}).get("hasNextPage"))
        scheduled_count = sum(
            1 for edge in edges
            if str((((edge or {}).get("node") or {}).get("channelId")) or channel_id) == channel_id
        )
        queue_available = queue_resp.status_code < 400 and posts is not None and not queue_error
        exact = bool(queue_available and not has_more)
        queue_remaining = max(0, queue_limit - scheduled_count) if exact else None
        queue = {
            "available": queue_available,
            "scheduled": scheduled_count if queue_available else None,
            "total": queue_limit,
            "remaining": queue_remaining,
            "exact": exact,
            "has_more": bool(queue_available and has_more),
            "is_at_limit": bool(queue_available and ((exact and queue_remaining is not None and queue_remaining <= 0) or (not exact and scheduled_count >= queue_limit))),
            "is_paused": bool(channel.get("isQueuePaused")),
            "channel_locked": bool(channel.get("isLocked")),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "message": (
                "Capacité actuelle de la file d’attente Buffer pour ce canal."
                if queue_available and exact
                else "La file contient davantage de publications que la première page retournée par Buffer ; le nombre affiché est un minimum."
                if queue_available
                else queue_error or f"Lecture de la file d’attente Buffer impossible (HTTP {queue_resp.status_code})."
            ),
        }

    daily["queue"] = queue
    return JSONResponse(daily)


@router.get("/networks/publishable")
async def get_publishable_accounts(user=Depends(require_auth)):
    """Comptes actifs utilisables dans le workspace, y compris partages explicites."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT a.id::text, a.provider, a.display_name, a.platform_account_name, a.external_username,
                   a.external_account_id, a.is_active,
                   COALESCE(a.metadata->>'connection_provider','') AS connection_provider,
                   COALESCE(a.metadata->>'service','') AS service,
                   (a.workspace_id=$1::uuid) AS is_owner_workspace
            FROM public.app_social_accounts a
            LEFT JOIN public.app_social_account_workspaces saw
              ON saw.account_id=a.id AND saw.workspace_id=$1::uuid
            WHERE a.deleted_at IS NULL AND a.is_active=true
              AND (a.workspace_id=$1::uuid OR saw.account_id IS NOT NULL)
              AND (
                CASE
                  WHEN saw.account_id IS NULL AND a.workspace_id=$1::uuid THEN true
                  ELSE COALESCE(saw.is_active,false) AND saw.revoked_at IS NULL
                END
              ) = true
            ORDER BY a.provider, a.display_name
            """,
            user.active_workspace_id,
        )

    accounts = []
    for r in rows:
        provider = str(r["provider"] or "").lower()
        if provider == "instagram" and r["connection_provider"] == "meta_facebook":
            continue
        name = r["display_name"] or r["platform_account_name"] or r["external_username"] or "Compte"
        service = str(r["service"] or "").strip()
        platform = _normalize_buffer_platform(service) if provider == "buffer" else provider
        provider_label = {
            "facebook": "Facebook", "instagram": "Instagram",
            "buffer": f"Buffer{' · ' + service if service else ''}",
        }.get(provider, provider)
        accounts.append({
            "id": r["id"],
            "provider": provider,
            "platform": platform,
            "service": service,
            "display_name": r["display_name"] or "",
            "platform_account_name": r["platform_account_name"] or "",
            "external_username": r["external_username"] or "",
            "external_account_id": r["external_account_id"] or "",
            "connection_provider": str(r["connection_provider"] or ""),
            "is_active": bool(r["is_active"]),
            "label": f"{name} · {provider_label}",
            "is_owner_workspace": bool(r["is_owner_workspace"]),
        })

    return JSONResponse({"success": True, "data": {"accounts": accounts}})


@router.get("/networks/list-page")
async def get_networks_list_page(request: Request, limit: int = 20, cursor_at: str = "", cursor_id: str = "",
                                  user=Depends(require_auth)):
    """Pagination des comptes visibles dans le workspace actif."""
    pool = get_pool()
    limit = max(1, min(50, limit))
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            _network_access_list_sql(cursor=True) + " ORDER BY a.updated_at DESC NULLS LAST, a.id DESC LIMIT $4",
            user.active_workspace_id, cursor_at or None, cursor_id or None, limit + 1,
        )

    has_more = len(rows) > limit
    page = rows[:limit]
    accounts = _decorate_network_rows(page, user.timezone)
    rows_html = render_fragment(request, "networks/_account_rows.html", accounts=accounts)
    next_at = page[-1]["updated_at"].isoformat() if page and page[-1]["updated_at"] else ""
    next_id = page[-1]["id"] if page else ""
    return JSONResponse({
        "success": True, "rows_html": rows_html, "has_more": has_more,
        "next_cursor_at": next_at, "next_cursor_id": next_id,
    })


@router.post("/networks/facebook/select/save")
async def post_facebook_select_save(payload: dict = Body(...), user=Depends(require_auth)):
    """Enregistre les Pages Facebook choisies et crée leur lien workspace local."""
    page_ids = [str(p).strip() for p in (payload.get("page_ids") or []) if str(p).strip()]
    if not page_ids:
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR",
                             "message": "Sélectionne au moins une Page."}, status_code=422)

    pool = get_pool()
    saved: list[dict] = []
    async with pool.acquire() as conn:
      async with conn.transaction():
        candidates = await conn.fetch(
            """
            SELECT * FROM public.app_social_oauth_candidates
            WHERE workspace_id=$1::uuid AND provider='facebook'
              AND external_account_id = ANY($2::text[])
            ORDER BY created_at DESC
            """,
            user.active_workspace_id, page_ids,
        )
        by_external: dict[str, object] = {}
        for candidate in candidates:
            ext = str(candidate["external_account_id"] or "")
            if ext and ext not in by_external:
                by_external[ext] = candidate
        missing = [pid for pid in page_ids if pid not in by_external]
        if missing:
            return JSONResponse({"success": False, "error": "CANDIDATE_NOT_FOUND",
                                 "message": "Une ou plusieurs Pages sélectionnées ne sont plus disponibles. Relance la connexion Facebook."}, status_code=409)

        for page_id in page_ids:
            candidate = by_external[page_id]
            lock_key = f"facebook:{user.active_workspace_id}:{page_id}"
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1::text))", lock_key)
            existing_id = await conn.fetchval(
                """
                SELECT id::text FROM public.app_social_accounts
                WHERE workspace_id=$1::uuid AND provider='facebook' AND external_account_id=$2
                ORDER BY updated_at DESC NULLS LAST, created_at DESC LIMIT 1 FOR UPDATE
                """,
                user.active_workspace_id, page_id,
            )
            metadata = candidate["metadata"]
            metadata = json.loads(metadata) if isinstance(metadata, str) else (metadata or {})
            metadata = {**metadata, "connection_provider": "meta_facebook"}
            if existing_id:
                row = await conn.fetchrow(
                    """
                    UPDATE public.app_social_accounts
                    SET user_id=$2::uuid, display_name=$3, platform_account_name=$4,
                        external_parent_id=$5, external_username=$6, token_ciphertext=$7,
                        token_expires_at=$8, scopes=$9, metadata=$10::jsonb,
                        is_active=true, deleted_at=NULL, updated_at=now()
                    WHERE id=$1::uuid
                    RETURNING id::text, display_name
                    """,
                    existing_id, candidate["user_id"], candidate["display_name"],
                    candidate["platform_account_name"], candidate["external_parent_id"],
                    candidate["external_username"], candidate["token_ciphertext"],
                    candidate["token_expires_at"], candidate["scopes"], json.dumps(metadata),
                )
            else:
                row = await conn.fetchrow(
                    """
                    INSERT INTO public.app_social_accounts (
                        user_id, workspace_id, provider, display_name, platform_account_name,
                        external_account_id, external_parent_id, external_username,
                        token_ciphertext, token_expires_at, scopes, metadata, is_active
                    ) VALUES ($1::uuid,$2::uuid,'facebook',$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,true)
                    RETURNING id::text, display_name
                    """,
                    candidate["user_id"], user.active_workspace_id, candidate["display_name"],
                    candidate["platform_account_name"], page_id, candidate["external_parent_id"],
                    candidate["external_username"], candidate["token_ciphertext"],
                    candidate["token_expires_at"], candidate["scopes"], json.dumps(metadata),
                )
            await ensure_local_workspace_link(conn, row["id"], user.active_workspace_id, user.id)
            saved.append(dict(row))

        await conn.execute(
            "DELETE FROM public.app_social_oauth_candidates WHERE workspace_id=$1::uuid AND provider='facebook'",
            user.active_workspace_id,
        )

    return JSONResponse({"success": True, "data": {"connected": len(saved), "accounts": saved}})


@router.post("/networks/meta/config/test")
async def post_meta_config_test(payload: dict = Body(...), user=Depends(require_admin)):
    """
    Teste les identifiants d'une app Meta via le jeton applicatif
    (`grant_type=client_credentials`) : valide App ID + App Secret sans
    nécessiter de compte utilisateur connecté.
    """
    provider = payload.get("provider", PROVIDER_META_FACEBOOK)
    settings = await get_meta_settings(provider)
    if not settings or not settings.app_id or not settings.app_secret:
        return JSONResponse({"success": False, "error": "NOT_CONFIGURED",
                              "message": "App ID ou App Secret manquant."}, status_code=422)

    import httpx
    from app.services.meta import graph_base

    base = await graph_base(instagram_direct=(provider == PROVIDER_META_INSTAGRAM))
    try:
        async with httpx.AsyncClient(base_url=base, timeout=30) as client:
            resp = await client.get("/oauth/access_token", params={
                "client_id": settings.app_id, "client_secret": settings.app_secret,
                "grant_type": "client_credentials",
            })
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"success": False, "error": "NETWORK_ERROR", "message": str(exc)}, status_code=502)

    ok = bool(data.get("access_token"))
    message = ("Identifiants valides." if ok
                else (data.get("error", {}).get("message") or "Identifiants refusés par Meta."))

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE public.app_integration_settings "
            "SET last_tested_at=now(), last_test_success=$2, last_test_message=$3 WHERE provider=$1::text",
            provider, ok, message,
        )
    return JSONResponse({"success": ok, "message": message}, status_code=200 if ok else 422)
