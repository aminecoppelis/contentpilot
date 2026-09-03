"""
Routes de gestion des espaces de travail — port FIDÈLE de
"HTML - Workspace" / "BDD - Charger Workspace" / "BDD - Action Workspace" /
"BDD - Accepter invitation Workspace".

Corrections vs première version du portage :
  - Les actions réelles sont : create, rename, invite, revoke_invite,
    member_role, remove_member, leave, delete (et non change_role/etc.).
  - Les invitations vivent dans une table dédiée `workspace_invitations`
    (jeton haché SHA-256, expiration 7 jours), pas dans workspace_members.
  - La suppression d'un workspace exige la saisie exacte de son nom ET
    qu'il existe au moins un autre workspace accessible (protection du
    dernier workspace, PROTECT_LAST_ACCESSIBLE_WORKSPACE_V65).
  - Toute la logique d'autorisation est portée par la requête SQL unique
    `sql/workspace/action.sql` (verbatim) : le routeur ne fait que la passer.
"""
from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.database import get_pool, sql
from app.public_origin import resolve_public_origin
from app.dependencies.auth import require_auth
from app.security import new_activation_token
from app.services.mailer import send_workspace_invite_email
from app.user_timezone import format_user_value

router = APIRouter(tags=["Workspace"])
templates = Jinja2Templates(directory="templates")

ROLE_LABELS = {
    "super_admin": "Super administrateur",
    "owner": "Propriétaire",
    "admin": "Administrateur",
    "member": "Membre",
}


def role_label(role: str | None) -> str:
    return ROLE_LABELS.get(role or "member", "Membre")


@router.get("/workspace", response_class=HTMLResponse)
async def get_workspace(request: Request, user=Depends(require_auth)):
    import json as _json

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql("workspace/load.sql"), user.id, user.active_workspace_id)

    def _parse(value, default):
        if value is None:
            return default
        return _json.loads(value) if isinstance(value, str) else value

    ws = _parse(row["workspace"] if row else None, {}) or {}
    members = _parse(row["members"] if row else None, []) or []
    invitations = _parse(row["invitations"] if row else None, []) or []

    for m in members:
        m["role_label"] = role_label(m.get("role"))
    for i in invitations:
        i["role_label"] = role_label(i.get("role"))
        i["expires_label"] = format_user_value(i.get("expires_at"), user.timezone)

    # Port exact des règles d'affichage/permission de la page originale
    effective_role = ws.get("role") or user.active_workspace_role or ""
    is_super_admin = (user.role or "").lower() == "admin" or effective_role == "super_admin"
    can_admin = is_super_admin or effective_role in ("owner", "admin")
    is_owner = (ws.get("role") or "") == "owner"

    current_workspace_id = str(ws.get("id") or user.active_workspace_id or "")
    has_alternative_workspace = any(
        str(w.id) and str(w.id) != current_workspace_id for w in user.workspaces
    )
    can_delete_base = (
        (is_owner or is_super_admin)
        and ws.get("is_personal") is not True
        and not str(ws.get("system_key") or "").strip()
    )
    can_delete = can_delete_base and has_alternative_workspace

    return templates.TemplateResponse(request, "workspace/index.html", {
        "auth_user": user, "active_nav": "workspace",
        "ws": ws, "members": members, "invitations": invitations,
        "is_super_admin": is_super_admin, "can_admin": can_admin, "is_owner": is_owner,
        "can_delete": can_delete, "can_delete_base": can_delete_base,
        "has_alternative_workspace": has_alternative_workspace,
        "role_label": role_label(effective_role),
    })


@router.post("/workspace/action")
async def post_workspace_action(
    request: Request,
    action: str = Form(...),
    name: str = Form(""),
    email: str = Form(""),
    role: str = Form("member"),
    target_user_id: str = Form(""),
    invitation_id: str = Form(""),
    user=Depends(require_auth),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            sql("workspace/action.sql"),
            user.id, user.active_workspace_id, action, name, email, role,
            target_user_id or None, invitation_id or None,
        )

    params: dict[str, str] = {}
    if row and row["success"]:
        params["success"] = row["message"]
        # Invitation : envoi de l'email avec le jeton en clair retourné par la requête
        if action == "invite" and row["invite_token"]:
            public_base = resolve_public_origin(request).rstrip('/')
            invite_url = f"{public_base}/app/workspace/invite/accept?token={row['invite_token']}"
            sent = await send_workspace_invite_email(
                to_email=row["invite_email"],
                workspace_name=user.active_workspace_name or "Workspace",
                invite_url=invite_url,
                role=row["invite_role"] or "member",
            )
            if sent:
                # La réponse n'est rendue qu'après acceptation du message par le SMTP.
                params["success"] = "Invitation envoyée immédiatement par email."
            else:
                # Ne laisse jamais une invitation active en prétendant qu'elle a été envoyée.
                invite_id = str(row["invite_id"] or "").strip()
                if invite_id:
                    async with pool.acquire() as cleanup_conn:
                        await cleanup_conn.execute(
                            """
                            UPDATE public.workspace_invitations
                            SET revoked_at=COALESCE(revoked_at, now()), updated_at=now()
                            WHERE id=$1::uuid AND workspace_id=$2::uuid AND accepted_at IS NULL
                            """,
                            invite_id, user.active_workspace_id,
                        )
                params.pop("success", None)
                params["error"] = (
                    "Invitation non envoyée : le serveur SMTP n’a pas accepté le message. "
                    "Vérifie la configuration SMTP puis réessaie."
                )
    else:
        params["error"] = (row["message"] if row else "Action impossible ou droits insuffisants.")

    # Après suppression ou départ, le workspace courant n'existe plus : retour au dashboard
    if action in ("delete", "leave") and row and row["success"]:
        return RedirectResponse(f"/app/dashboard?{urlencode(params)}", status_code=302)

    return RedirectResponse(f"/app/workspace?{urlencode(params)}", status_code=302)


@router.post("/workspace/switch")
async def post_workspace_switch(request: Request, user=Depends(require_auth)):
    from fastapi.responses import JSONResponse
    payload = await request.json()
    workspace_id = payload.get("workspace_id")
    pool = get_pool()
    async with pool.acquire() as conn:
        allowed = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM public.workspace_members
                WHERE workspace_id=$1::uuid AND user_id=$2::uuid AND status='active'
            ) OR $3::boolean
            """,
            workspace_id, user.id, user.is_super_admin,
        )
        if not allowed:
            return JSONResponse({"success": False, "error": "FORBIDDEN",
                                  "message": "Accès non autorisé à ce workspace."}, status_code=403)
        await conn.execute("UPDATE public.app_users SET last_workspace_id=$2::uuid WHERE id=$1::uuid",
                            user.id, workspace_id)
    return JSONResponse({"success": True})


@router.get("/workspace/invite/accept")
async def get_workspace_invite_accept(request: Request, token: str, user=Depends(require_auth)):
    """
    Port verbatim de "BDD - Accepter invitation Workspace" : le jeton clair est
    haché puis comparé, l'email de l'invitation doit correspondre à celui du
    compte connecté, et le workspace rejoint devient le workspace actif.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql("workspace/accept_invite.sql"), user.id, token)

    key = "success" if (row and row["success"]) else "error"
    message = row["message"] if row else "Invitation invalide."
    return RedirectResponse(f"/app/workspace?{urlencode({key: message})}", status_code=302)
