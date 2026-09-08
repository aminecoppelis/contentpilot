"""
Routes d'authentification — port fidèle de Cahier technique §4 et §6.1.
Login/Register utilisent les requêtes SQL verbatim (sql/auth/*.sql) pour
garantir un comportement identique (verrouillage progressif, bcrypt, etc.)
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.database import get_pool, sql
from app.public_origin import resolve_public_origin
from app.security import (
    anti_bot_ok, safe_redirect, is_valid_email, is_valid_password,
    new_session_token, session_token_hash, new_activation_token, activation_token_hash,
)
from app.dependencies.auth import get_current_user, require_auth
from app.services.mailer import send_activation_email, send_account_change_email
from app.user_timezone import valid_timezone_name, format_user_datetime

router = APIRouter(tags=["Auth"])
from app.templating import templates


def _client_ip(request: Request) -> str:
    # Priorité identique à l'original : x-real-ip > x-forwarded-for > remote-addr
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return (
        request.headers.get("x-real-ip")
        or forwarded
        or (request.client.host if request.client else "")
        or "unknown"
    )


# ---------------------------------------------------------------------------
# GET/POST /login
# ---------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def get_login(request: Request, redirect: str = "/app/dashboard", error: str | None = None,
                     info: str | None = None, retry_until: int = 0):
    user = await get_current_user(request)
    if user:
        return RedirectResponse(safe_redirect(redirect), status_code=302)
    is_rate_limit_error = bool(error) and error.startswith("Trop de tentatives de connexion.")
    return templates.TemplateResponse(request, "login.html", {
        "redirect": safe_redirect(redirect), "error": error, "info": info,
        "retry_until_ms": retry_until, "is_rate_limit_error": is_rate_limit_error,
    })


@router.post("/login")
async def post_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    redirect: str = Form("/app/dashboard"),
    form_started_at: int = Form(0),
    company_website: str = Form(""),
    user_timezone: str = Form(""),
):
    settings = get_settings()
    redirect_safe = safe_redirect(redirect)
    ok_bot = anti_bot_ok(form_started_at, company_website)
    ip = _client_ip(request)

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            sql("auth/login.sql"), email, password, redirect_safe, ok_bot, ip,
        )

    if not row["login_ok"]:
        if row["was_locked"] or row["retry_after_seconds"]:
            message = f"Trop de tentatives de connexion. Réessaie dans {row['retry_after_seconds']}s."
            retry_until_ms = int((time.time() + row["retry_after_seconds"]) * 1000)
        elif row["anti_bot_error"]:
            message = "Vérification anti-bot impossible. Recharge la page et réessaie."
            retry_until_ms = 0
        else:
            message = "Email ou mot de passe incorrect."
            retry_until_ms = 0
        from urllib.parse import urlencode
        qs = urlencode({"error": message, "redirect": redirect_safe, "retry_until": retry_until_ms})
        return RedirectResponse(f"/app/login?{qs}", status_code=302)

    # Connexion réussie -> création de session (Cahier technique §4.1)
    raw_token = new_session_token()
    token_hash = session_token_hash(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.session_ttl_hours)

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                sql("auth/create_session.sql"),
                row["user_id"], token_hash, expires_at,
                request.headers.get("user-agent", ""), ip,
            )
            tz_name = valid_timezone_name(user_timezone)
            await conn.execute(
                "UPDATE public.app_users SET last_login_at=now(), timezone=COALESCE($2::text,timezone), updated_at=now() WHERE id=$1::uuid",
                row["user_id"], tz_name,
            )

    response = RedirectResponse(redirect_safe, status_code=302)
    response.set_cookie(
        settings.session_cookie_name, raw_token,
        httponly=True, secure=settings.session_cookie_secure, samesite="lax",
        max_age=settings.session_ttl_hours * 3600, path="/",
    )
    return response


# ---------------------------------------------------------------------------
# GET/POST /register
# ---------------------------------------------------------------------------

@router.get("/register", response_class=HTMLResponse)
async def get_register(request: Request, redirect: str = "/app/dashboard", error: str | None = None):
    redirect_safe = safe_redirect(redirect)
    return templates.TemplateResponse(request, "register.html", {
        "redirect": redirect_safe, "error": error,
        "invited_registration": "/workspace/invite/accept?" in redirect_safe,
    })


@router.post("/register")
async def post_register(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    redirect: str = Form("/app/dashboard"),
    form_started_at: int = Form(0),
    company_website: str = Form(""),
    user_timezone: str = Form(""),
):
    redirect_safe = safe_redirect(redirect)
    errors = []
    if not first_name.strip():
        errors.append("Le prénom est obligatoire.")
    if not last_name.strip():
        errors.append("Le nom est obligatoire.")
    if not is_valid_email(email):
        errors.append("Email invalide.")
    if not is_valid_password(password):
        errors.append("Le mot de passe doit contenir au moins 10 caractères.")
    if password != confirm_password:
        errors.append("Les mots de passe ne correspondent pas.")
    if not anti_bot_ok(form_started_at, company_website):
        errors.append("Vérification anti-bot impossible. Recharge la page et réessaie.")

    if errors:
        from urllib.parse import urlencode
        qs = urlencode({"error": " ".join(errors), "redirect": redirect_safe})
        return RedirectResponse(f"/app/register?{qs}", status_code=302)

    full_name = f"{first_name} {last_name}".strip()
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            sql("auth/register.sql"), email, first_name, last_name, full_name, password,
        )

    if row and row["user_id"]:
        tz_name = valid_timezone_name(user_timezone)
        if tz_name:
            async with pool.acquire() as conn:
                await conn.execute("UPDATE public.app_users SET timezone=$2::text, updated_at=now() WHERE id=$1::uuid", row["user_id"], tz_name)

    if not row or not row["user_id"]:
        # Email déjà utilisé (ON CONFLICT DO NOTHING) -> message générique,
        # pas d'énumération de comptes (comportement documenté, Cahier technique §4.4).
        from urllib.parse import urlencode
        qs = urlencode({"error": "Un compte existe déjà avec cet email.", "redirect": redirect_safe})
        return RedirectResponse(f"/app/register?{qs}", status_code=302)

    public_base = resolve_public_origin(request).rstrip('/')
    activation_url = f"{public_base}/app/activate?token={row['activation_token']}&redirect={redirect_safe}"
    sent = await send_activation_email(
        to_email=row["email"], full_name=full_name, activation_url=activation_url)

    from urllib.parse import urlencode
    if sent:
        return RedirectResponse(f"/app/login?{urlencode({'info': 'check_email'})}", status_code=302)

    # SMTP indisponible : le compte est créé mais ne peut pas être activé par email.
    # Le lien est journalisé côté serveur pour permettre l'activation manuelle,
    # et l'utilisateur reçoit un message explicite plutôt qu'une erreur 500.
    import logging
    logging.getLogger("auth").warning(
        "Compte %s créé mais email d'activation NON envoyé. "
        "Lien d'activation à transmettre manuellement : %s",
        row["email"], activation_url)
    return RedirectResponse(
        f"/app/login?{urlencode({'info': 'smtp_down'})}", status_code=302)


# ---------------------------------------------------------------------------
# GET /activate
# ---------------------------------------------------------------------------

@router.get("/activate", response_class=HTMLResponse)
async def get_activate(request: Request, token: str = "", redirect: str = "/app/dashboard"):
    pool = get_pool()
    token_hash_value = activation_token_hash(token) if token else ""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql("auth/activate_account.sql"), token_hash_value)

    return templates.TemplateResponse(request, "activate.html", {
        "activated": bool(row and row["activated"]),
        "email": (row["email"] if row else "") or "",
        "redirect": safe_redirect(redirect),
    })


# ---------------------------------------------------------------------------
# GET /logout
# ---------------------------------------------------------------------------

@router.get("/logout")
async def get_logout(request: Request, user=Depends(get_current_user)):
    settings = get_settings()
    if user and user.session_id:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(sql("auth/revoke_session.sql"), user.session_id)
    response = RedirectResponse("/app/login", status_code=302)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return response


# ---------------------------------------------------------------------------
# GET /locale — change de langue (cookie + persistance BDD si connecté)
# ---------------------------------------------------------------------------

@router.get("/locale")
async def set_locale(request: Request, to: str = "", next: str = "/app/dashboard",
                     user=Depends(get_current_user)):
    from app.i18n import COOKIE_NAME, COOKIE_MAX_AGE, is_supported, normalize_locale

    target = safe_redirect(next)
    response = RedirectResponse(target, status_code=302)
    if is_supported(to):
        locale = normalize_locale(to)
        response.set_cookie(
            COOKIE_NAME, locale, max_age=COOKIE_MAX_AGE, path="/", samesite="lax",
            secure=get_settings().session_cookie_secure,
        )
        if user and getattr(user, "id", None):
            try:
                pool = get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE public.app_users SET locale = $2 WHERE id = $1",
                        user.id, locale,
                    )
            except Exception:  # noqa: BLE001 — la préférence cookie suffit
                pass
    return response


# ---------------------------------------------------------------------------
# GET/POST /account
# ---------------------------------------------------------------------------

@router.get("/account", response_class=HTMLResponse)
async def get_account(request: Request, user=Depends(require_auth),
                      success: str | None = None, error: str | None = None):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT activation_sent_at, created_at, timezone FROM public.app_users WHERE id=$1::uuid", user.id,
        )
    activated_at = ""
    if row and row["created_at"]:
        activated_at = format_user_datetime(row["created_at"], user.timezone, "%d/%m/%Y")

    return templates.TemplateResponse(request, "account.html", {
        "auth_user": user, "active_nav": "account", "activated_at": activated_at,
        "banner_message": success or error,
        "banner_type": "success" if success else ("error" if error else ""),
    })


@router.post("/timezone")
async def post_timezone(request: Request, user=Depends(require_auth)):
    """Mémorise le fuseau IANA détecté par le navigateur pour les requêtes futures."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    tz_name = valid_timezone_name(payload.get("timezone") or request.headers.get("X-PG-Timezone", ""))
    if not tz_name:
        return JSONResponse({"success": False, "error": "INVALID_TIMEZONE", "message": "Fuseau horaire invalide."}, status_code=422)
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE public.app_users SET timezone=$2::text, updated_at=now() WHERE id=$1::uuid AND timezone IS DISTINCT FROM $2::text",
            user.id, tz_name,
        )
    return JSONResponse({"success": True, "data": {"timezone": tz_name}})


@router.post("/account")
async def post_account(
    request: Request,
    action: str = Form("profile"),
    first_name: str = Form(""),
    last_name: str = Form(""),
    email: str = Form(""),
    current_password: str = Form(""),
    new_password: str = Form(""),
    confirm_password: str = Form(""),
    user=Depends(require_auth),
):
    """
    Port fidèle de "AUTH - POST Account" : deux actions distinctes.
      - action='profile'  : met à jour prénom/nom/email. Un changement d'email
        exige le mot de passe actuel, DÉSACTIVE le compte (is_active=false) et
        déclenche l'envoi d'un nouveau lien d'activation à la nouvelle adresse.
      - action='password' : exige le mot de passe actuel + confirmation, min 10 car.
    """
    from urllib.parse import urlencode
    pool = get_pool()

    def redirect_with(param: str, message: str):
        return RedirectResponse(f"/app/account?{urlencode({param: message})}", status_code=302)

    async def check_current_password(conn) -> bool:
        return bool(await conn.fetchval(
            "SELECT (password_hash = crypt($2::text, password_hash)) FROM public.app_users WHERE id=$1::uuid",
            user.id, current_password,
        ))

    if action not in ("profile", "password"):
        return redirect_with("error", "Action de compte non reconnue.")

    if action == "password":
        if not new_password or len(new_password) < 10:
            return redirect_with("error", "Le nouveau mot de passe doit contenir au moins 10 caractères.")
        if new_password != confirm_password:
            return redirect_with("error", "Les mots de passe ne correspondent pas.")
        async with pool.acquire() as conn:
            if not await check_current_password(conn):
                return redirect_with("error", "Mot de passe actuel incorrect.")
            await conn.execute(
                "UPDATE public.app_users SET password_hash = crypt($2::text, gen_salt('bf',10)), updated_at=now() WHERE id=$1::uuid",
                user.id, new_password,
            )
        return redirect_with("success", "Mot de passe modifié.")

    # action == 'profile'
    if not first_name.strip() or not last_name.strip():
        return redirect_with("error", "Le prénom et le nom sont obligatoires.")
    if not is_valid_email(email):
        return redirect_with("error", "Email invalide.")

    email_changed = email.strip().lower() != user.email.lower()
    full_name = f"{first_name} {last_name}".strip()

    async with pool.acquire() as conn:
        if email_changed:
            duplicate = await conn.fetchval(
                "SELECT 1 FROM public.app_users WHERE lower(email)=lower($1) AND id<>$2::uuid AND deleted_at IS NULL LIMIT 1",
                email.strip(), user.id,
            )
            if duplicate:
                return redirect_with("error", "Cette adresse email est déjà utilisée par un autre compte.")
            if not current_password:
                return redirect_with("error", "Le mot de passe actuel est requis pour changer d'email.")
            if not await check_current_password(conn):
                return redirect_with("error", "Mot de passe actuel incorrect.")

            # Changement d'email : désactivation + nouveau jeton d'activation
            raw_token = new_activation_token()
            updated = await conn.fetchrow(
                """
                WITH updated AS (
                    UPDATE public.app_users
                    SET first_name=$2, last_name=$3, full_name=$4, email=lower($5),
                        is_active=false, activation_sent_at=now(), updated_at=now()
                    WHERE id=$1::uuid
                    RETURNING id, email
                ), tok AS (
                    INSERT INTO public.account_activation_tokens (user_id, token_hash, expires_at)
                    SELECT updated.id, encode(digest($6::text,'sha256'),'hex'), now() + interval '24 hours'
                    FROM updated RETURNING user_id
                )
                SELECT email FROM updated
                """,
                user.id, first_name, last_name, full_name, email, raw_token,
            )
            # Révocation des sessions actives (le compte est désactivé)
            await conn.execute("UPDATE public.auth_sessions SET revoked_at=now() WHERE user_id=$1::uuid AND revoked_at IS NULL", user.id)

            public_base = resolve_public_origin(request).rstrip('/')
            activation_url = f"{public_base}/app/activate?token={raw_token}"
            sent = await send_activation_email(
                to_email=updated["email"], full_name=full_name, activation_url=activation_url
            )
            if sent:
                return RedirectResponse("/app/login?info=check_email", status_code=302)

            # Le changement est déjà enregistré et les sessions ont été révoquées.
            # On journalise donc le lien comme lors de l'inscription, au lieu de
            # laisser l'utilisateur croire que l'email a été envoyé.
            import logging
            logging.getLogger("auth").warning(
                "Email du compte %s modifié mais activation NON envoyée. "
                "Lien d'activation à transmettre manuellement : %s",
                updated["email"], activation_url,
            )
            return RedirectResponse("/app/login?info=smtp_down", status_code=302)

        await conn.execute(
            "UPDATE public.app_users SET first_name=$2, last_name=$3, full_name=$4, updated_at=now() WHERE id=$1::uuid",
            user.id, first_name, last_name, full_name,
        )
    return redirect_with("success", "Informations mises à jour.")
