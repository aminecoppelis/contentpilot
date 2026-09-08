"""
Routes d'administration — port FIDÈLE de "AUTH - HTML Admin Users",
"AUTH - BDD Admin User Action", "HTML - Paramétrage Admin" et
"HTML - Configuration Meta Admin".

Note de sécurité : `sql/admin/user_action.sql` refait sa PROPRE vérification
du rôle admin à partir de la session (défense en profondeur) en plus de la
dépendance `require_admin` — comportement conservé tel quel, la requête est
donc appelée avec le hash de session courant.
"""
from __future__ import annotations

import json
from urllib.parse import urlencode, quote

from fastapi import APIRouter, Request, Depends, Form, Body
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.database import get_pool, sql
from app.dependencies.auth import require_admin
from app.security import session_token_hash
from app.services.settings_service import get_serper_settings, save_serper_settings
from app.user_timezone import format_user_datetime

router = APIRouter(tags=["Admin"])
from app.templating import templates, render_fragment

ADMIN_USERS_PAGE_SIZE = 20


def _session_hash(request: Request) -> str:
    raw = request.cookies.get(get_settings().session_cookie_name, "")
    return session_token_hash(raw) if raw else ""


async def _fetch_users(conn, offset: int = 0, limit: int = ADMIN_USERS_PAGE_SIZE):
    return await conn.fetch(
        """
        SELECT id::text, email, first_name, last_name, full_name,
               COALESCE(role,'user') AS role, is_active, created_at
        FROM public.app_users
        WHERE deleted_at IS NULL
        ORDER BY created_at DESC
        LIMIT $1 OFFSET $2
        """,
        limit, offset,
    )


def _decorate_users(rows, current_user_id: str, timezone_name: str) -> list[dict]:
    out = []
    for r in rows:
        d = dict(r)
        full = " ".join(filter(None, [d.get("first_name"), d.get("last_name")])) or d.get("full_name") or "—"
        d["display_name"] = full
        d["is_self"] = d["id"] == current_user_id
        d["created_label"] = format_user_datetime(d.get("created_at"), timezone_name, "%d %b %Y, %H:%M", "—")
        d["edit_payload"] = quote(json.dumps({
            "id": d["id"], "first_name": d.get("first_name") or "", "last_name": d.get("last_name") or "",
            "email": d.get("email") or "", "role": d.get("role") or "user", "active": bool(d.get("is_active")),
        }))
        out.append(d)
    return out


@router.get("/admin/users", response_class=HTMLResponse)
async def get_admin_users(request: Request, user=Depends(require_admin),
                           success: str | None = None, error: str | None = None):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await _fetch_users(conn)
        total = await conn.fetchval("SELECT count(*)::int FROM public.app_users WHERE deleted_at IS NULL")

    return templates.TemplateResponse(request, "admin/users.html", {
        "auth_user": user, "active_nav": "admin",
        "users": _decorate_users(rows, user.id, user.timezone),
        "total_users": total, "users_has_more": total > ADMIN_USERS_PAGE_SIZE,
        "notice": success or error, "notice_error": bool(error),
    })


@router.get("/admin/users/list-page")
async def get_admin_users_list_page(request: Request, page: int = 1, user=Depends(require_admin)):
    """Pagination du scroll infini de la page Admin Users (JSON)."""
    pool = get_pool()
    offset = max(0, (page - 1)) * ADMIN_USERS_PAGE_SIZE
    async with pool.acquire() as conn:
        rows = await _fetch_users(conn, offset=offset)
        total = await conn.fetchval("SELECT count(*)::int FROM public.app_users WHERE deleted_at IS NULL")
    decorated = _decorate_users(rows, user.id, user.timezone)
    rows_html = render_fragment(request, "admin/_user_rows.html", users=decorated)
    return JSONResponse({
        "success": True,
        "data": {
            "rows_html": rows_html,
            "has_more": offset + len(rows) < total,
            "next_page": page + 1,
            "total": total,
        },
    })


@router.post("/admin/users/action")
async def post_admin_users_action(
    request: Request,
    action: str = Form(...),
    user_id: str = Form(...),
    first_name: str = Form(""),
    last_name: str = Form(""),
    email: str = Form(""),
    role: str = Form(""),
    user=Depends(require_admin),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            sql("admin/user_action.sql"),
            _session_hash(request), action, user_id,
            first_name, last_name, email, role,
            request.headers.get("X-PG-Session-Id") or None,
            request.headers.get("X-PG-Request-Token") or None,
        )

    key = "success" if (row and row["success"]) else "error"
    message = (row["message"] if row else "Action impossible.")
    return RedirectResponse(f"/app/admin/users?{urlencode({key: message})}", status_code=302)


@router.get("/admin/settings", response_class=HTMLResponse)
async def get_admin_settings(request: Request, user=Depends(require_admin),
                              success: str | None = None, error: str | None = None):
    cfg = await get_serper_settings()
    return templates.TemplateResponse(request, "admin/settings.html", {
        "auth_user": user, "active_nav": "admin", "cfg": cfg,
        "gl_options": ["fr", "us", "gb", "ca", "de", "es", "it", "be", "ch", "ma", "world"],
        "hl_options": ["fr", "en", "es", "de", "it"],
        "notice": success or error, "notice_error": bool(error),
    })


@router.post("/admin/settings/save")
async def post_admin_settings_save(request: Request, user=Depends(require_admin)):
    """Port fidèle de "BDD - Enregistrer paramétrage Admin" (Serper)."""
    form = await request.form()
    try:
        num = max(3, min(10, int(form.get("serper_num", 8) or 8)))
    except (TypeError, ValueError):
        num = 8
    await save_serper_settings(
        api_key=str(form.get("serper_api_key", "") or "").strip(),
        shared_key=(get_settings().token_encryption_key or get_settings().database_url),
        gl=str(form.get("serper_gl", "fr")).lower(),
        hl=str(form.get("serper_hl", "fr")).lower(),
        num=num,
        is_enabled=form.get("serper_enabled") in ("1", "on", "true"),
    )
    return RedirectResponse(
        f"/app/admin/settings?{urlencode({'success': 'Paramétrage Serper enregistré.'})}", status_code=302,
    )


@router.get("/admin/workspaces/setup", response_class=HTMLResponse)
async def get_admin_workspaces_setup(request: Request, user=Depends(require_admin)):
    """
    Outil d'initialisation/migration du modèle multi-workspace
    (port verbatim de "BDD - Migration Workspaces"). La requête est
    idempotente : elle peut être relancée sans risque.
    """
    pool = get_pool()
    error = ""
    try:
        async with pool.acquire() as conn:
            await conn.execute(sql("workspace/migration.sql"))
        message = "Migration multi-workspace appliquée (opération idempotente)."
    except Exception as exc:  # noqa: BLE001
        message = "La migration a échoué."
        error = str(exc)

    return templates.TemplateResponse(request, "admin/workspaces_setup.html", {
        "auth_user": user, "active_nav": "admin", "message": message, "error": error,
    })


@router.get("/admin/diagnostics")
async def get_diagnostics(user=Depends(require_admin)):
    """
    État de la configuration, consultable depuis le navigateur.
    Évite d'avoir à fouiller les logs pour savoir si SMTP, OpenRouter ou
    les intégrations Meta sont réellement opérationnels.
    Aucun secret n'est renvoyé, seulement leur présence.
    """
    import socket

    settings = get_settings()
    from app.services.mailer import _tls_mode

    use_tls, start_tls = _tls_mode(settings)
    smtp = {
        "actif": settings.smtp_enabled,
        "hote": settings.smtp_host or None,
        "port": settings.smtp_port,
        "chiffrement": "ssl_implicite" if use_tls else ("starttls" if start_tls else "aucun"),
        "utilisateur": settings.smtp_user or None,
        "expediteur": settings.smtp_from,
        "joignable": None,
        "avertissement": None,
    }
    if settings.smtp_enabled:
        try:
            socket.create_connection((settings.smtp_host, settings.smtp_port), timeout=5).close()
            smtp["joignable"] = True
        except Exception as exc:  # noqa: BLE001
            smtp["joignable"] = False
            smtp["erreur"] = str(exc)
        # Cause n°1 des emails acceptés mais jamais délivrés
        if "example.com" in (settings.smtp_from or ""):
            smtp["avertissement"] = (
                "SMTP_FROM utilise encore example.com. La plupart des fournisseurs "
                "(dont OVH) acceptent le message puis le suppriment sans notification "
                "quand l'expéditeur n'appartient pas au compte SMTP.")
        elif settings.smtp_user and "@" in settings.smtp_user:
            domaine_user = settings.smtp_user.split("@")[-1].lower()
            if domaine_user not in (settings.smtp_from or "").lower():
                smtp["avertissement"] = (
                    f"SMTP_FROM ne contient pas le domaine de SMTP_USER ({domaine_user}). "
                    "Le fournisseur risque de refuser ou d'ignorer l'expéditeur.")

    pool = get_pool()
    async with pool.acquire() as conn:
        comptes_inactifs = await conn.fetchval(
            "SELECT count(*) FROM public.app_users WHERE is_active = false AND deleted_at IS NULL")

    return JSONResponse({"success": True, "data": {
        "url_publique": settings.app_base_url,
        "cookie_securise": settings.session_cookie_secure,
        "smtp": smtp,
        "openrouter": {
            "cle_presente": bool(settings.openrouter_api_key),
            "modele": settings.openrouter_model,
        },
        "worker": {"actif": not settings.disable_scheduler},
        "migrations_auto": settings.auto_migrate,
        "comptes_en_attente_activation": comptes_inactifs,
    }})
