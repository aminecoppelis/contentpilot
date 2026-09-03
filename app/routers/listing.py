"""
Pages tabulaires : Idées de post (/history) et Posts publiés (/published).
Port fidèle de "HTML - Historique" et "HTML - Publications" :
  - filtre multi-statuts via ?filter=a,b,c (valeur 'all' = pas de filtre)
  - scroll infini (endpoint ...-list-page renvoyant du HTML de lignes)
  - suppression groupée des publications (POST /published/delete-bulk)
"""
from __future__ import annotations

from fastapi import APIRouter, Request, Depends, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.database import get_pool
from app.dependencies.auth import require_auth
from app.user_timezone import format_user_datetime

router = APIRouter(tags=["Listing"])
templates = Jinja2Templates(directory="templates")

PAGE_SIZE = 25

# Libellés exacts (statusLabelMap de l'original)
STATUS_LABEL_MAP = {
    "pending_review": "En attente", "ready_for_review": "À valider", "needs_changes": "En attente",
    "approved": "Prêt à publier", "ready": "Prêt à publier", "published": "Publié",
    "error": "En erreur", "rejected": "Rejeté", "cancelled": "Annulé", "scheduled": "Programmé",
    "pending": "En attente", "failed": "En erreur", "processing": "En cours",
}

HISTORY_FILTER_OPTIONS = [
    {"value": "all", "label": "Tous"},
    {"value": "ready_for_review", "label": "À valider"},
    {"value": "cancelled", "label": "Annulé"},
    {"value": "pending_review", "label": "En attente"},
    {"value": "error", "label": "En erreur"},
    {"value": "approved", "label": "Prêt à publier"},
    {"value": "scheduled", "label": "Programmé"},
    {"value": "published", "label": "Publié"},
    {"value": "rejected", "label": "Rejeté"},
]

PUBLISHED_FILTER_OPTIONS = [
    {"value": "all", "label": "Tous"},
    {"value": "scheduled", "label": "Programmé"},
    {"value": "pending", "label": "En attente"},
    {"value": "published", "label": "Publié"},
    {"value": "failed", "label": "En erreur"},
    {"value": "cancelled", "label": "Annulé"},
]

PLATFORM_LABELS = {"linkedin": "LinkedIn", "instagram": "Instagram", "facebook": "Facebook", "buffer": "Buffer"}


def _label_status(value: str) -> str:
    return STATUS_LABEL_MAP.get(str(value or ""), str(value or "-"))


def _parse_filter(raw: str | None) -> list[str]:
    """Port de selectedFiltersFromQuery : 'all' ou liste de statuts."""
    values = [v.strip().lower() for v in str(raw or "").split(",") if v.strip()]
    return values or ["all"]


def _initials(name: str | None) -> str:
    """Port exact de personCell() : initiales à partir d'un nom ou d'un email."""
    n = str(name or "").strip()
    if not n or n == "-":
        return ""
    words = [w for w in n.split() if w]
    if len(words) > 1:
        ini = (words[0][:1] + words[-1][:1]).upper()
    else:
        local = str(words[0]).split("@")[0]
        parts = [p for p in local.replace(".", " ").replace("_", " ").replace("-", " ").split() if p]
        ini = ((parts[0][:1] + parts[-1][:1]) if len(parts) > 1 else local[:2]).upper()
    return ini or n[:1].upper()


def _fmt(dt, timezone_name: str) -> str:
    return format_user_datetime(dt, timezone_name)


# ---------------------------------------------------------------------------
# /history — Idées de post
# ---------------------------------------------------------------------------

HISTORY_SQL = """
SELECT
    pi.id::text AS idea_id, pi.request_id::text, pi.title AS idea_title, pi.status AS idea_status,
    pr.subject, COALESCE(pi.updated_at, pi.created_at) AS last_modified_at,
    cu.first_name || ' ' || cu.last_name AS created_by_name,
    pu.first_name || ' ' || pu.last_name AS published_by_name,
    (SELECT count(*) FROM public.post_media pm WHERE pm.idea_id = pi.id AND pm.workspace_id=pi.workspace_id AND pm.status='ready' AND COALESCE(pm.public_url,pm.external_url,'')<>'') AS media_count,
    COALESCE((
        SELECT jsonb_agg(jsonb_build_object('platform', pp.platform, 'status', pp.status))
        FROM public.post_publications pp WHERE pp.idea_id = pi.id
    ), '[]'::jsonb) AS publication_items
FROM public.post_ideas pi
JOIN public.post_requests pr ON pr.id = pi.request_id
LEFT JOIN public.app_users cu ON cu.id = pi.user_id
-- Auteur de la publication : premier publieur réel de cette idée (peut différer du créateur)
LEFT JOIN LATERAL (
    SELECT pp2.published_by
    FROM public.post_publications pp2
    WHERE pp2.idea_id = pi.id AND pp2.published_by IS NOT NULL
    ORDER BY pp2.published_at NULLS LAST, pp2.created_at
    LIMIT 1
) first_pub ON true
LEFT JOIN public.app_users pu ON pu.id = first_pub.published_by
WHERE pi.workspace_id = $1::uuid AND pi.deleted_at IS NULL AND pr.deleted_at IS NULL
  AND ($2::text[] IS NULL OR pi.status = ANY($2::text[]))
ORDER BY COALESCE(pi.updated_at, pi.created_at) DESC
LIMIT $3 OFFSET $4
"""

HISTORY_COUNT_SQL = """
SELECT count(*)::int
FROM public.post_ideas pi
JOIN public.post_requests pr ON pr.id = pi.request_id
WHERE pi.workspace_id = $1::uuid AND pi.deleted_at IS NULL AND pr.deleted_at IS NULL
  AND ($2::text[] IS NULL OR pi.status = ANY($2::text[]))
"""


async def _load_history(workspace_id: str, statuses: list[str], offset: int, timezone_name: str):
    status_array = None if "all" in statuses else statuses
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(HISTORY_SQL, workspace_id, status_array, PAGE_SIZE, offset)
        total = await conn.fetchval(HISTORY_COUNT_SQL, workspace_id, status_array)

    import json as _json
    out = []
    for r in rows:
        d = dict(r)
        d["status_label"] = _label_status(d["idea_status"])
        d["last_modified"] = _fmt(d["last_modified_at"], timezone_name)
        d["created_by_initials"] = _initials(d.get("created_by_name"))
        d["published_by_initials"] = _initials(d.get("published_by_name"))
        items = d.get("publication_items")
        items = _json.loads(items) if isinstance(items, str) else (items or [])
        grouped: dict[str, set[str]] = {}
        for item in items:
            platform = str(item.get("platform") or "").strip().lower()
            status = str(item.get("status") or "").strip().lower()
            if not platform:
                continue
            grouped.setdefault(platform, set())
            if status:
                grouped[platform].add(status)
        publications = []
        for platform, platform_statuses in grouped.items():
            labels = [_label_status(status) for status in sorted(platform_statuses)]
            if any(status in {"failed", "error", "rejected", "cancelled"} for status in platform_statuses):
                tone = "error"
            elif any(status in {"published", "success", "posted", "completed"} for status in platform_statuses):
                tone = "published"
            else:
                tone = "pending"
            platform_label = PLATFORM_LABELS.get(platform, platform[:1].upper() + platform[1:] if platform else "Publication")
            status_label = ", ".join(labels) if labels else "Statut inconnu"
            publications.append({
                "platform": platform,
                "platform_label": platform_label,
                "statuses": sorted(platform_statuses),
                "tone": tone,
                "title": f"{platform_label} · {status_label}",
            })
        d["publications"] = publications
        out.append(d)
    return out, total


@router.get("/history", response_class=HTMLResponse)
async def get_history(request: Request, filter: str | None = None, user=Depends(require_auth)):
    statuses = _parse_filter(filter)
    rows, total = await _load_history(user.active_workspace_id, statuses, 0, user.timezone)
    return templates.TemplateResponse(request, "posts/history.html", {
        "auth_user": user, "active_nav": "history",
        "rows": rows, "total": total,
        "options": HISTORY_FILTER_OPTIONS, "selected": statuses, "all_selected": "all" in statuses,
        "has_more": len(rows) >= PAGE_SIZE and total > len(rows), "next_offset": len(rows),
    })


@router.get("/history/list-page")
async def get_history_list_page(request: Request, offset: int = 0, filter: str | None = None,
                                 user=Depends(require_auth)):
    statuses = _parse_filter(filter)
    rows, total = await _load_history(user.active_workspace_id, statuses, offset, user.timezone)
    html = templates.get_template("posts/_history_rows.html").render(rows=rows)
    return JSONResponse({"success": True, "data": {
        "rows_html": html, "has_more": offset + len(rows) < total,
        "next_offset": offset + len(rows), "total": total,
    }})


# ---------------------------------------------------------------------------
# /published — Posts publiés
# ---------------------------------------------------------------------------

PUBLISHED_SQL = """
SELECT
    pp.id::text AS publication_id, pp.platform, pp.publication_type, pp.status, pp.scheduled_at,
    COALESCE(pp.updated_at, pp.created_at) AS last_modified_at,
    COALESCE(pp.error_message, pp.response ->> 'error') AS error_message,
    pp.published_at,
    pi.title AS idea_title,
    cu.first_name || ' ' || cu.last_name AS created_by_name,
    pu.first_name || ' ' || pu.last_name AS published_by_name
FROM public.post_publications pp
LEFT JOIN public.post_ideas pi ON pi.id = pp.idea_id
LEFT JOIN public.app_users cu ON cu.id = pi.user_id
LEFT JOIN public.app_users pu ON pu.id = pp.published_by
WHERE pp.workspace_id = $1::uuid
  AND ($2::text[] IS NULL OR pp.status = ANY($2::text[]))
ORDER BY COALESCE(pp.updated_at, pp.created_at) DESC
LIMIT $3 OFFSET $4
"""

PUBLISHED_COUNT_SQL = """
SELECT count(*)::int FROM public.post_publications pp
WHERE pp.workspace_id = $1::uuid AND ($2::text[] IS NULL OR pp.status = ANY($2::text[]))
"""


async def _load_published(workspace_id: str, statuses: list[str], offset: int, timezone_name: str):
    status_array = None if "all" in statuses else statuses
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(PUBLISHED_SQL, workspace_id, status_array, PAGE_SIZE, offset)
        total = await conn.fetchval(PUBLISHED_COUNT_SQL, workspace_id, status_array)

    out = []
    for r in rows:
        d = dict(r)
        d["status_label"] = _label_status(d["status"])
        d["platform_label"] = PLATFORM_LABELS.get(str(d.get("platform") or ""), d.get("platform") or "—")
        d["last_modified"] = _fmt(d["last_modified_at"], timezone_name)
        d["scheduled_label"] = _fmt(d.get("scheduled_at"), timezone_name)
        d["published_label"] = _fmt(d.get("published_at"), timezone_name)
        d["created_by_initials"] = _initials(d.get("created_by_name"))
        d["published_by_initials"] = _initials(d.get("published_by_name"))
        out.append(d)
    return out, total


@router.get("/published", response_class=HTMLResponse)
async def get_published(request: Request, filter: str | None = None, user=Depends(require_auth)):
    statuses = _parse_filter(filter)
    rows, total = await _load_published(user.active_workspace_id, statuses, 0, user.timezone)
    return templates.TemplateResponse(request, "posts/published.html", {
        "auth_user": user, "active_nav": "published",
        "rows": rows, "total": total,
        "options": PUBLISHED_FILTER_OPTIONS, "selected": statuses, "all_selected": "all" in statuses,
        "has_more": len(rows) >= PAGE_SIZE and total > len(rows), "next_offset": len(rows),
    })


@router.get("/published/list-page")
async def get_published_list_page(request: Request, offset: int = 0, filter: str | None = None,
                                   user=Depends(require_auth)):
    statuses = _parse_filter(filter)
    rows, total = await _load_published(user.active_workspace_id, statuses, offset, user.timezone)
    html = templates.get_template("posts/_published_rows.html").render(rows=rows)
    return JSONResponse({"success": True, "data": {
        "rows_html": html, "has_more": offset + len(rows) < total,
        "next_offset": offset + len(rows), "total": total,
    }})


@router.post("/published/delete-bulk")
async def post_published_delete_bulk(payload: dict = Body(...), user=Depends(require_auth)):
    ids = [str(i) for i in (payload.get("publication_ids") or [])]
    if not ids:
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR",
                              "message": "Aucune ligne sélectionnée."}, status_code=422)
    pool = get_pool()
    async with pool.acquire() as conn:
        deleted = await conn.fetch(
            """
            DELETE FROM public.post_publications
            WHERE workspace_id = $1::uuid AND id = ANY($2::uuid[])
            RETURNING id
            """,
            user.active_workspace_id, ids,
        )
    return JSONResponse({"success": True, "data": {"deleted_count": len(deleted)},
                          "deleted_count": len(deleted)})
