"""
Routes de génération/gestion des posts — Cahier technique §6.3, §7.2-7.4.
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, Request, Depends, Body
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.database import get_pool
from app.dependencies.auth import require_auth
from app.services import ai
from app.services.ai import AIGenerationError
from app.services import post_generation
from app.services.copy_ready import build_copy_ready_text
from app.user_timezone import format_user_datetime

router = APIRouter(tags=["Posts"])
from app.templating import templates, render_fragment

URL_RE = re.compile(r"https?://[^\s]+")

STATUS_LABELS = {
    "generated": "Generated", "generating": "Génération en cours", "generating_more": "Ajout en cours",
    "pending_review": "En attente", "ready_for_review": "À valider", "draft": "Brouillon",
    "needs_changes": "En attente", "approved": "Prêt à publier", "scheduled": "Programmé",
    "published": "Publié", "error": "En erreur", "rejected": "Rejeté", "deleted": "Supprimé",
    "no_ideas": "Aucune idée", "ready": "Generated",
}


def _status_label(status: str, ideas_count: int) -> str:
    if status in ("generated_empty", "no_ideas"):
        return "Generated" if ideas_count > 0 else "Aucune idée"
    return STATUS_LABELS.get(status, (status or "draft").replace("_", " ").capitalize())


@router.get("/posts/new", response_class=HTMLResponse)
async def get_posts_new(request: Request, user=Depends(require_auth)):
    return templates.TemplateResponse(request, "posts/new.html", {
        "active_nav": "posts","auth_user": user})


@router.post("/post-ideas-generate")
async def post_ideas_generate(request: Request, user=Depends(require_auth)):
    """Enfile la génération et répond immédiatement, comme le webhook n8n V90.

    Accepte JSON (interface moderne) et formulaire HTML (fallback sans JS).
    """
    content_type = str(request.headers.get("content-type") or "").lower()
    try:
        if "application/json" in content_type:
            parsed = await request.json()
            payload = parsed if isinstance(parsed, dict) else {}
        else:
            form = await request.form()
            payload = dict(form)
            # Les multi-selects arrivent plusieurs fois sous le même nom en fallback HTML.
            for key in ("content_domains", "target_audience", "preferred_formats"):
                values = form.getlist(key)
                if values:
                    payload[key] = values
    except Exception:  # noqa: BLE001
        payload = {}
    try:
        request_id, job_id = await post_generation.enqueue_initial(
            payload=payload, user_id=user.id, workspace_id=user.active_workspace_id
        )
    except ValueError as exc:
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR", "message": str(exc)}, status_code=422)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"success": False, "error": "QUEUE_ERROR", "message": str(exc)}, status_code=500)
    post_generation.kick(job_id)
    redirect_url = f"/app/posts/view?request_id={request_id}&queued=1"
    wants_json = "application/json" in str(request.headers.get("accept") or "").lower() or "application/json" in content_type
    if not wants_json:
        return RedirectResponse(redirect_url, status_code=303)
    return JSONResponse({
        "success": True, "async": True, "status": "queued", "generation_status": "queued",
        "request_id": request_id, "job_id": job_id, "redirect_url": redirect_url,
        "message": "Génération lancée en arrière-plan."
    }, status_code=202)


@router.get("/posts/ideas-page", response_class=HTMLResponse)
async def get_ideas_page(request: Request, request_id: str, user=Depends(require_auth)):
    pool = get_pool()
    async with pool.acquire() as conn:
        ideas = await conn.fetch(
            """
            SELECT pi.id::text AS idea_id, pi.title, pi.hook, pi.summary, pi.recommended_format,
                   pv.post_text, pv.hashtags, pv.cta
            FROM public.post_ideas pi
            JOIN public.post_versions pv ON pv.id = pi.current_version_id
            WHERE pi.request_id = $1::uuid AND pi.workspace_id=$2::uuid AND pi.deleted_at IS NULL
            ORDER BY pi.number ASC
            """,
            request_id, user.active_workspace_id,
        )
    return templates.TemplateResponse(request, "posts/ideas_page.html", {
        "active_nav": "posts",
        "auth_user": user, "request_id": request_id, "ideas": [dict(r) for r in ideas],
    })


@router.post("/post-ideas-action")
async def post_ideas_action(request: Request, payload: dict = Body(...), user=Depends(require_auth)):
    idea_id = payload["idea_id"]
    action = payload["action"]
    instructions = payload.get("instructions")
    pool = get_pool()

    async with pool.acquire() as conn:
        idea_row = await conn.fetchrow(
            """SELECT pi.raw_idea, pr.form_data
               FROM public.post_ideas pi
               JOIN public.post_requests pr ON pr.id=pi.request_id AND pr.workspace_id=pi.workspace_id
              WHERE pi.id=$1::uuid AND pi.workspace_id=$2::uuid AND pi.deleted_at IS NULL""",
            idea_id, user.active_workspace_id,
        )
    if idea_row is None:
        return JSONResponse({"success": False, "error": "NOT_FOUND", "message": "Idée introuvable."}, status_code=404)

    idea = json.loads(idea_row["raw_idea"]) if isinstance(idea_row["raw_idea"], str) else idea_row["raw_idea"]
    generation_context = json.loads(idea_row["form_data"]) if isinstance(idea_row["form_data"], str) else (idea_row["form_data"] or {})

    # Actions de statut simples (port des boutons Valider / Refuser / Demander validation)
    STATUS_ACTIONS = {
        "validate": ("approved", "Valider"),
        "reject": ("rejected", "Refuser"),
        "request_review": ("ready_for_review", "À valider"),
    }
    if action in STATUS_ACTIONS:
        new_status, review_action = STATUS_ACTIONS[action]
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE public.post_ideas
                SET status = $2,
                    raw_idea = COALESCE(raw_idea,'{}'::jsonb) || jsonb_build_object(
                        'review_note', $3::text, 'review_action', $4::text,
                        'reviewed_at', now()::text, 'reviewed_by', $5::text),
                    updated_at = now()
                WHERE id = $1::uuid AND workspace_id = $6::uuid
                """,
                idea_id, new_status, instructions or "", review_action, user.id, user.active_workspace_id,
            )
            await conn.execute(
                """
                INSERT INTO public.post_activity_logs (workspace_id, entity_type, entity_id, action, details)
                VALUES ($1::uuid,'post_idea',$2::uuid,$3,jsonb_build_object('note',$4::text))
                """,
                user.active_workspace_id, idea_id, new_status, instructions or "",
            )
        return JSONResponse({"success": True, "data": {"idea_id": idea_id, "status": new_status}})

    if action in ("edit", "regenerate"):
        try:
            ai_result = await ai.modify_idea(idea, instructions, generation_context)
        except AIGenerationError as exc:
            return JSONResponse({"success": False, "error": "AI_GENERATION_FAILED", "message": str(exc)}, status_code=502)

        new_idea = ai_result.parsed["idea"]
        ready = new_idea.get("ready_post", {})
        async with pool.acquire() as conn:
          async with conn.transaction():
            next_version = await conn.fetchval(
                "SELECT COALESCE(MAX(version_number)+1,1) FROM public.post_versions WHERE idea_id=$1::uuid AND workspace_id=$2::uuid",
                idea_id, user.active_workspace_id,
            )
            version_row = await conn.fetchrow(
                """
                INSERT INTO public.post_versions (
                    idea_id, workspace_id, version_number, source, title, post_text, hashtags, cta,
                    instructions, is_current, raw_version, edited_by
                ) VALUES ($1::uuid,$2::uuid,$3,$4,$5,$6,$7,$8,$9,true,$10,$11::uuid)
                RETURNING id::text AS version_id
                """,
                idea_id, user.active_workspace_id, next_version, f"ai_{action}",
                ready.get("title", ""), ready.get("text", ""),
                json.dumps(ready.get("tags", [])), ready.get("simple_action", ""),
                instructions, json.dumps(ready), user.id,
            )
            await conn.execute(
                "UPDATE public.post_versions SET is_current=false WHERE idea_id=$1::uuid AND workspace_id=$3::uuid AND id<>$2::uuid",
                idea_id, version_row["version_id"], user.active_workspace_id,
            )
            await conn.execute(
                "UPDATE public.post_ideas SET current_version_id=$2::uuid, raw_idea=$3, updated_at=now() "
                "WHERE id=$1::uuid AND workspace_id=$4::uuid",
                idea_id, version_row["version_id"], json.dumps(new_idea), user.active_workspace_id,
            )
        return JSONResponse({"success": True, "data": {"idea": new_idea, "version_id": version_row["version_id"]}})

    return JSONResponse({"success": False, "error": "INVALID_ACTION", "message": "Action inconnue."}, status_code=400)


@router.post("/reformulate-prompt")
async def post_reformulate_prompt(payload: dict = Body(...), user=Depends(require_auth)):
    try:
        result = await ai.reformulate_prompt(payload)
    except AIGenerationError as exc:
        return JSONResponse({"success": False, "error": "AI_GENERATION_FAILED", "message": str(exc)}, status_code=502)
    return JSONResponse({"success": True, "data": result.parsed})


@router.get("/posts", response_class=HTMLResponse)
async def get_posts(request: Request, status: str | None = None, page: int = 1, user=Depends(require_auth)):
    """
    Port fidèle de "HTML - Liste Posts" : cette page liste les DEMANDES
    (post_requests), pas les idées individuelles — chaque ligne agrège le
    nombre d'idées/approuvées/médias pour une demande de génération.
    """
    page = max(1, int(page or 1))
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                pr.id::text AS id, pr.title, pr.subject, pr.status, pr.updated_at, pr.created_at,
                u.first_name || ' ' || u.last_name AS created_by_name,
                COUNT(DISTINCT pi.id) FILTER (WHERE pi.deleted_at IS NULL) AS ideas_count,
                COUNT(DISTINCT pi.id) FILTER (WHERE pi.status IN ('validated','approved') AND pi.deleted_at IS NULL) AS approved_count,
                COUNT(DISTINCT pm.id) FILTER (WHERE pm.status='ready' AND COALESCE(pm.public_url,pm.external_url,'')<>'' AND pi.deleted_at IS NULL) AS media_count,
                (SELECT pi0.id::text
                   FROM public.post_ideas pi0
                  WHERE pi0.request_id=pr.id AND pi0.workspace_id=pr.workspace_id AND pi0.deleted_at IS NULL
                  ORDER BY pi0.number ASC, pi0.created_at ASC
                  LIMIT 1) AS first_idea_id
            FROM public.post_requests pr
            LEFT JOIN public.app_users u ON u.id = pr.user_id
            LEFT JOIN public.post_ideas pi ON pi.request_id = pr.id
            LEFT JOIN public.post_media pm ON pm.idea_id = pi.id
            WHERE pr.workspace_id = $1::uuid AND pr.deleted_at IS NULL
              AND ($2::text IS NULL OR pr.status = $2::text)
            GROUP BY pr.id, pr.workspace_id, u.first_name, u.last_name
            ORDER BY pr.updated_at DESC NULLS LAST, pr.created_at DESC
            LIMIT 20 OFFSET $3
            """,
            user.active_workspace_id, status, (page - 1) * 20,
        )
        total = await conn.fetchval(
            "SELECT count(*)::int FROM public.post_requests WHERE workspace_id=$1::uuid AND deleted_at IS NULL "
            "AND ($2::text IS NULL OR status=$2::text)",
            user.active_workspace_id, status,
        )

    requests_out = []
    for r in rows:
        d = dict(r)
        d["last_modified"] = format_user_datetime(d["updated_at"] or d["created_at"], user.timezone)
        d["status_label"] = _status_label(d["status"], d["ideas_count"])
        requests_out.append(d)

    return templates.TemplateResponse(request, "posts/list.html", {
        "auth_user": user, "active_nav": "posts", "requests": requests_out, "status": status, "page": page,
        "total": int(total or 0),
        "has_more": max(0, page - 1) * 20 + len(requests_out) < int(total or 0),
        "next_page": page + 1,
    })


IDEA_STATUS_META = {
    "pending_review": ("warn", "En attente"), "ready_for_review": ("warn", "À valider"),
    "needs_changes": ("warn", "À corriger"), "approved": ("ok", "Prêt à publier"),
    "validated": ("ok", "Prêt à publier"), "published": ("ok", "Publié"),
    "scheduled": ("info", "Programmé"), "rejected": ("reject", "Rejeté"),
    "draft": ("info", "Brouillon"), "error": ("reject", "En erreur"),
}

SCORE_FIELDS = [
    ("Viralité", "virality_score"), ("Commercial", "commercial_potential_score"),
    ("Leads", "lead_generation_score"), ("PME", "sme_interest_score"),
    ("Grandes entreprises", "enterprise_interest_score"), ("Difficulté", "implementation_difficulty_score"),
]



@router.get("/posts/view", response_class=HTMLResponse)
async def get_post_view(request: Request, idea_id: str | None = None, request_id: str | None = None,
                         user=Depends(require_auth)):
    """
    Port fidèle de "Construire page consultation moderne" : affiche soit
    toutes les idées d'une demande, soit une seule idée (vue `one`).
    """
    pool = get_pool()
    request_row = None
    request_deleted = False
    job_row = None
    async with pool.acquire() as conn:
        # Une idée n'est consultable que si son sujet parent est encore actif.
        # La suppression d'un sujet supprime logiquement ses idées associées.
        if idea_id:
            idea_parent = await conn.fetchrow(
                """
                SELECT pi.request_id::text AS request_id,
                       pr.id::text, pr.subject, pr.title, pr.status, pr.last_error,
                       pr.post_count, pr.updated_at, pr.created_at, pr.deleted_at,
                       COALESCE(pr.form_data->>'website', pr.form_data->>'site_web', '') AS website
                FROM public.post_ideas pi
                JOIN public.post_requests pr ON pr.id = pi.request_id
                WHERE pi.id=$1::uuid
                  AND pi.workspace_id=$2::uuid
                  AND pi.deleted_at IS NULL
                  AND pr.workspace_id=$2::uuid
                  AND pr.deleted_at IS NULL
                LIMIT 1
                """,
                idea_id, user.active_workspace_id,
            )
            if idea_parent is None:
                return templates.TemplateResponse(request, "error.html", {
                    "auth_user": user, "active_nav": "history",
                    "title": "Idée introuvable",
                    "message": "Cette idée n'existe pas dans le workspace actif."
                }, status_code=404)
            resolved_request_id = str(idea_parent["request_id"] or "")
            if request_id and str(request_id) != resolved_request_id:
                return templates.TemplateResponse(request, "error.html", {
                    "auth_user": user, "active_nav": "history",
                    "title": "Lien incohérent",
                    "message": "Cette idée n'appartient pas au sujet indiqué."
                }, status_code=404)
            request_id = resolved_request_id
            request_row = idea_parent
            request_deleted = False

        elif request_id:
            # Une ouverture par request_id seul reste réservée aux sujets actifs.
            request_row = await conn.fetchrow(
                """
                SELECT id::text,subject,title,status,last_error,post_count,updated_at,created_at,deleted_at,
                       COALESCE(form_data->>'website', form_data->>'site_web', '') AS website
                FROM public.post_requests
                WHERE id=$1::uuid AND workspace_id=$2::uuid AND deleted_at IS NULL
                """, request_id, user.active_workspace_id)
            if request_row is None:
                return templates.TemplateResponse(request, "error.html", {
                    "auth_user": user, "active_nav": "posts",
                    "title": "Sujet introuvable", "message": "Ce sujet n'existe pas dans le workspace actif."
                }, status_code=404)

        if request_row is not None and not request_deleted:
            job_row = await conn.fetchrow(
                """
                SELECT id::text,mode,status,requested_count,attempt_count,last_error,created_at,updated_at
                FROM public.post_generation_jobs
                WHERE request_id=$1::uuid
                ORDER BY created_at DESC LIMIT 1
                """, request_id)

        rows = await conn.fetch(
            """
            SELECT pi.id::text AS idea_id, pi.title, pi.hook, pi.summary, pi.status,
                   pi.recommended_format, pi.scores, pi.seo_keywords, pi.raw_idea,
                   pi.request_id::text, pr.subject AS request_subject,
                   COALESCE(pr.form_data->>'website', pr.form_data->>'site_web', '') AS website,
                   pv.id::text AS version_id, pv.post_text, pv.hashtags, pv.cta,
                   (SELECT count(*) FROM public.post_media pm WHERE pm.idea_id = pi.id AND pm.workspace_id=pi.workspace_id AND pm.status='ready' AND COALESCE(pm.public_url,pm.external_url,'')<>'') AS media_count,
                   COALESCE((
                       SELECT jsonb_agg(jsonb_build_object(
                           'id', pm.id::text, 'media_type', pm.media_type,
                           'url', COALESCE(pm.public_url, pm.external_url),
                           'public_url', pm.public_url, 'external_url', pm.external_url,
                           'media_role', pm.media_role, 'scenario_text', pm.scenario_text,
                           'file_name', pm.file_name, 'mime_type', pm.mime_type,
                           'prompt', pm.prompt, 'metadata', COALESCE(pm.metadata,'{}'::jsonb),
                           'status', pm.status, 'generation_status', pm.generation_status)
                           ORDER BY pm.created_at)
                       FROM public.post_media pm
                       WHERE pm.idea_id = pi.id AND pm.workspace_id=pi.workspace_id AND pm.status = 'ready' AND COALESCE(pm.public_url,pm.external_url,'')<>''
                   ), '[]'::jsonb) AS media
            FROM public.post_ideas pi
            JOIN public.post_requests pr ON pr.id = pi.request_id
            LEFT JOIN public.post_versions pv ON pv.id = pi.current_version_id
            WHERE pi.workspace_id = $1::uuid AND pi.deleted_at IS NULL
              AND ($2::uuid IS NULL OR pi.request_id = $2::uuid)
              AND ($3::uuid IS NULL OR pi.id = $3::uuid)
            ORDER BY pi.number ASC, pi.created_at ASC
            """,
            user.active_workspace_id, request_id, idea_id,
        )
        active_media_rows = [] if request_deleted else await conn.fetch(
            """
            SELECT pm.id::text AS media_id, pm.idea_id::text AS idea_id, pm.media_type,
                   pm.status, pm.generation_status, pm.metadata, pm.created_at, pm.updated_at
            FROM public.post_media pm
            JOIN public.post_ideas pi ON pi.id=pm.idea_id
            WHERE pm.workspace_id=$1::uuid AND pi.deleted_at IS NULL
              AND pm.status IN ('pending','processing')
              AND pm.generation_status IN ('queued','running','retry')
              AND ($2::uuid IS NULL OR pi.request_id=$2::uuid)
              AND ($3::uuid IS NULL OR pi.id=$3::uuid)
            ORDER BY pm.created_at ASC
            """,
            user.active_workspace_id, request_id, idea_id,
        )

    def _load(value, default):
        if value is None:
            return default
        return json.loads(value) if isinstance(value, str) else value

    ideas = []
    for r in rows:
        d = dict(r)
        raw_idea = _load(d["raw_idea"], {}) or {}
        scores = _load(d["scores"], {}) or {}
        media = _load(d["media"], []) or []
        status = str(d["status"] or "pending_review").lower()
        cls, label = IDEA_STATUS_META.get(status, ("info", status))

        selected = next((m for m in media if m.get("media_role") == "cover"), None)
        ideas.append({
            "idea_id": d["idea_id"], "version_id": d["version_id"],
            "title": d["title"] or "", "hook": d["hook"] or "", "summary": d["summary"] or "",
            "post_title": (raw_idea.get("ready_post") or {}).get("title") or d["title"] or "",
            "full_text": build_copy_ready_text(
                raw_idea, d["post_text"],
                version_hashtags=d["hashtags"], version_cta=d["cta"],
                website=d.get("website") or "",
                title=(raw_idea.get("ready_post") or {}).get("title") or d["title"] or "",
            ),
            "recommended_format": d["recommended_format"] or "",
            "status_cls": cls, "status_label": label,
            "is_published": status == "published", "is_scheduled": status == "scheduled",
            "awaiting_validation": status == "ready_for_review",
            "business_problem_solved": raw_idea.get("business_problem_solved", ""),
            "ai_or_software_solution": raw_idea.get("ai_or_software_solution", ""),
            "why_interesting_today": raw_idea.get("why_interesting_today", ""),
            "concrete_application_example": raw_idea.get("concrete_application_example", ""),
            "seo_keywords": _load(d["seo_keywords"], []) or [],
            "scores_list": [
                {"label": lbl, "value": int(scores.get(key, 0) or 0)}
                for lbl, key in SCORE_FIELDS if scores.get(key) is not None
            ],
            "media": media, "media_count": int(d["media_count"] or 0),
            "selected_media_id": (selected or {}).get("id"),
            "review_note": raw_idea.get("review_note", ""),
            "review_action": raw_idea.get("review_action", ""),
        })

    page_heading = (request_row["subject"] if request_row else None) or (rows[0]["request_subject"] if rows else None) or "Sujet"
    job_status = str(job_row["status"] or "") if job_row else ""
    request_status = str(request_row["status"] or "") if request_row else ""
    generation_in_progress = bool((not request_deleted) and request_id and (
        request_status in {"generating", "generating_more"} or job_status in {"queued", "running", "retry"}
    ))
    generation_failed = bool((not request_deleted) and request_id and (request_status == "failed" or job_status == "failed"))
    generated_count = len(ideas)
    if job_row and generation_in_progress:
        requested_batch = int(job_row["requested_count"] or 0)
        expected_count = generated_count + requested_batch if str(job_row["mode"] or "") == "append" else max(int(request_row["post_count"] or 0), requested_batch)
    else:
        expected_count = max(generated_count, int(request_row["post_count"] or 0) if request_row else generated_count)
    generation_error = str((job_row["last_error"] if job_row and job_row["last_error"] else (request_row["last_error"] if request_row else "")) or "")

    background_jobs = []
    if generation_in_progress:
        background_jobs.append({
            "id": f"ideas-{request_id}", "type": "ideas", "status": "processing",
            "label": "Génération des sujets",
            "message": f"{generated_count}/{expected_count} idée(s) préparée(s)",
        })
    for media_row in active_media_rows:
        media_type = str(media_row["media_type"] or "image").lower()
        metadata = _load(media_row["metadata"], {}) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        background_jobs.append({
            "id": f"media-{media_row['media_id']}",
            "media_id": media_row["media_id"],
            "idea_id": media_row["idea_id"],
            "type": "video" if media_type == "video" else "image",
            "status": "processing",
            "label": "Génération vidéo" if media_type == "video" else "Génération image",
            "message": "Vidéo en cours côté serveur…" if media_type == "video" else "Image en cours côté serveur…",
            "job_id": metadata.get("job_id") or metadata.get("openrouter_job_id"),
        })

    return templates.TemplateResponse(request, "posts/view.html", {
        "auth_user": user, "active_nav": "posts",
        "ideas": ideas, "request_id": request_id or "",
        "page_heading": page_heading,
        "request_deleted": request_deleted,
        "read_only": request_deleted,
        "single_idea_view": bool(idea_id),
        "generation_in_progress": generation_in_progress,
        "generation_failed": generation_failed,
        "generation_error": generation_error,
        "generation_status": job_status or request_status,
        "generated_count": generated_count,
        "expected_count": expected_count,
        "background_jobs": background_jobs,
        "ideas_json": [
            {
                "idea_id": i["idea_id"], "version_id": i["version_id"], "title": i["title"],
                "post_title": i["post_title"], "full_text": i["full_text"],
                "summary": i["summary"], "recommended_format": i["recommended_format"],
                "business_problem_solved": i["business_problem_solved"],
                "ai_or_software_solution": i["ai_or_software_solution"],
                "concrete_application_example": i["concrete_application_example"],
                "selected_media_id": i["selected_media_id"], "media": i["media"],
                "media_count": i["media_count"],
            }
            for i in ideas
        ],
    })


@router.post("/posts/delete")
async def post_delete(request: Request, user=Depends(require_auth)):
    """Supprime logiquement un sujet, en JSON ou formulaire classique.

    Le bouton de liste utilise fetch(JSON), mais accepter aussi
    application/x-www-form-urlencoded garde l'action fonctionnelle si le
    JavaScript est indisponible ou bloqué par le navigateur.
    """
    content_type = str(request.headers.get("content-type") or "").lower()
    payload = {}
    try:
        if "application/json" in content_type:
            parsed = await request.json()
            payload = parsed if isinstance(parsed, dict) else {}
        else:
            form = await request.form()
            payload = dict(form)
    except Exception:  # noqa: BLE001 - validation explicite juste après
        payload = {}
    request_id = str(payload.get("request_id") or payload.get("id") or "").strip()
    if not request_id:
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR",
                             "message": "Identifiant du sujet manquant."}, status_code=422)
    pool = get_pool()
    async with pool.acquire() as conn:
        deleted_row = await conn.fetchrow(
            """
            WITH deleted_request AS (
              UPDATE public.post_requests
              SET deleted_at=COALESCE(deleted_at,now()),
                  status='deleted',
                  last_error=NULL,
                  updated_at=now()
              WHERE id=$1::uuid
                AND workspace_id=$2::uuid
                AND deleted_at IS NULL
              RETURNING id,workspace_id
            ),
            deleted_ideas AS (
              UPDATE public.post_ideas pi
              SET deleted_at=COALESCE(pi.deleted_at,now()),
                  status='deleted',
                  current_version_id=NULL,
                  updated_at=now()
              FROM deleted_request d
              WHERE pi.request_id=d.id
                AND pi.workspace_id=d.workspace_id
                AND pi.deleted_at IS NULL
              RETURNING pi.id,pi.workspace_id
            ),
            cancelled_publications AS (
              UPDATE public.post_publications pp
              SET status='cancelled',
                  error_message='Sujet supprimé.',
                  updated_at=now(),
                  response=COALESCE(pp.response,'{}'::jsonb) || jsonb_build_object(
                    'cancelled_reason','subject_deleted',
                    'cancelled_at',now()::text
                  )
              FROM deleted_ideas di
              WHERE pp.idea_id=di.id
                AND pp.workspace_id=di.workspace_id
                AND lower(COALESCE(pp.status,'')) IN ('scheduled','processing','pending','queued')
              RETURNING pp.id
            ),
            reset_calendar AS (
              UPDATE public.app_growth_strategy_action_calendar c
              SET request_id=NULL,
                  status='pending_reschedule',
                  triggered_at=NULL,
                  error_message=NULL,
                  updated_at=now(),
                  payload=(
                    COALESCE(c.payload,'{}'::jsonb)
                    - 'generated_request_id'
                    - 'generation_error'
                    - 'generation_error_node'
                    - 'error_email_in_progress_key'
                    - 'error_email_in_progress_at'
                    - 'error_email_sent_key'
                    - 'error_email_sent_at'
                    - 'clean_worker_lock_until'
                  ) || jsonb_build_object(
                    'generation_stage','subject_deleted_waiting_reschedule',
                    'generation_stage_updated_at',now()::text,
                    'deleted_request_id',d.id::text,
                    'requires_reschedule',true,
                    'worker_version','V14'
                  )
              FROM deleted_request d
              WHERE c.request_id=d.id
                AND (c.workspace_id IS NULL OR c.workspace_id=d.workspace_id)
              RETURNING c.id
            )
            SELECT d.id::text AS request_id,
                   COALESCE((SELECT COUNT(*)::int FROM deleted_ideas),0) AS deleted_idea_count,
                   COALESCE((SELECT COUNT(*)::int FROM cancelled_publications),0) AS cancelled_publication_count,
                   COALESCE((SELECT COUNT(*)::int FROM reset_calendar),0) AS calendar_reset_count
            FROM deleted_request d
            """,
            request_id, user.active_workspace_id,
        )
        deleted = str(deleted_row["request_id"]) if deleted_row else ""
        deleted_idea_count = int(deleted_row["deleted_idea_count"] or 0) if deleted_row else 0
        cancelled_publication_count = int(deleted_row["cancelled_publication_count"] or 0) if deleted_row else 0
        calendar_reset_count = int(deleted_row["calendar_reset_count"] or 0) if deleted_row else 0
    if not deleted:
        return JSONResponse({"success": False, "error": "NOT_FOUND",
                             "message": "Sujet introuvable dans ce workspace."}, status_code=404)
    return JSONResponse({
        "success": True,
        "data": {
            "request_id": deleted,
            "deleted_idea_count": deleted_idea_count,
            "cancelled_publication_count": cancelled_publication_count,
            "calendar_reset_count": calendar_reset_count,
        },
        "message": "Sujet et idées associées supprimés."
    })


@router.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard(request: Request, user=Depends(require_auth)):
    pool = get_pool()
    async with pool.acquire() as conn:
        connected_accounts = await conn.fetchval(
            """
            SELECT count(DISTINCT a.id)::int
            FROM public.app_social_accounts a
            LEFT JOIN public.app_social_account_workspaces saw
              ON saw.account_id=a.id AND saw.workspace_id=$1::uuid
            WHERE a.deleted_at IS NULL AND a.is_active=true
              AND (a.workspace_id=$1::uuid OR saw.account_id IS NOT NULL)
              AND (
                CASE WHEN saw.account_id IS NULL AND a.workspace_id=$1::uuid THEN true
                     ELSE COALESCE(saw.is_active,false) AND saw.revoked_at IS NULL END
              ) = true
            """,
            user.active_workspace_id,
        )
        active_strategies = await conn.fetchval(
            "SELECT count(*) FROM public.app_growth_strategies WHERE workspace_id=$1::uuid AND status='active'",
            user.active_workspace_id,
        )
        planned_actions = await conn.fetchval(
            "SELECT count(*) FROM public.app_growth_strategy_action_calendar WHERE workspace_id=$1::uuid AND status IN ('scheduled','retry')",
            user.active_workspace_id,
        )
        published_posts = await conn.fetchval(
            "SELECT count(*) FROM public.post_publications WHERE workspace_id=$1::uuid AND status='published'",
            user.active_workspace_id,
        )
        failed_items = await conn.fetchval(
            "SELECT count(*) FROM public.app_growth_strategy_action_calendar WHERE workspace_id=$1::uuid AND status='failed'",
            user.active_workspace_id,
        )
        next_actions_rows = await conn.fetch(
            """
            SELECT c.id::text, c.strategy_id::text, c.planned_for, s.title AS strategy_title
            FROM public.app_growth_strategy_action_calendar c
            LEFT JOIN public.app_growth_strategies s ON s.id = c.strategy_id
            WHERE c.workspace_id=$1::uuid AND c.status IN ('scheduled','retry')
            ORDER BY c.planned_for ASC LIMIT 5
            """,
            user.active_workspace_id,
        )
        recent_rows = await conn.fetch(
            "SELECT entity_type, action, created_at FROM public.post_activity_logs WHERE workspace_id=$1::uuid ORDER BY created_at DESC LIMIT 8",
            user.active_workspace_id,
        )

    next_actions = [
        {"url": f"/app/strategies?strategy_id={r['strategy_id']}#calendar",
         "title": r["strategy_title"] or "Action planifiée",
         "meta": format_user_datetime(r["planned_for"], user.timezone)}
        for r in next_actions_rows if r["strategy_id"]
    ]
    recent_activity = [
        {
            "entity": (r["entity_type"] or "").replace("_", " ").strip(),
            "action": r["action"] or "",
            "at": format_user_datetime(r["created_at"], user.timezone, "%d/%m %H:%M"),
        }
        for r in recent_rows
    ]

    return templates.TemplateResponse(request, "posts/dashboard.html", {
        "auth_user": user, "active_nav": "dashboard",
        "connected_accounts": connected_accounts, "active_strategies": active_strategies,
        "planned_actions": planned_actions, "published_posts": published_posts, "failed_items": failed_items,
        "next_actions": next_actions, "recent_activity": recent_activity, "todos": [],
    })


@router.post("/subject-suggestions")
async def post_subject_suggestions(payload: dict = Body(...), user=Depends(require_auth)):
    """
    Suggestions de sujet via Serper (autocomplete + recherches associées +
    questions fréquentes), utilisées par l'autocomplétion du formulaire.
    Retourne une liste vide silencieusement si Serper n'est pas activé —
    le champ reste utilisable sans suggestions (comportement de l'original).
    """
    from app.services import serper as serper_client

    query = str(payload.get("subject_partial", "")).strip()
    if len(query) < 3:
        return JSONResponse({"success": True, "data": {"suggestions": []}})

    try:
        if not await serper_client.is_enabled():
            return JSONResponse({"success": True, "data": {"suggestions": []}})
        suggestions: list[str] = []
        auto = await serper_client.autocomplete(query)
        for item in (auto.get("suggestions") or [])[:8]:
            value = item.get("value") if isinstance(item, dict) else str(item)
            if value:
                suggestions.append(value)
        if len(suggestions) < 8:
            search = await serper_client.search(query)
            for item in (search.get("relatedSearches") or []):
                value = item.get("query") if isinstance(item, dict) else str(item)
                if value and value not in suggestions:
                    suggestions.append(value)
            for item in (search.get("peopleAlsoAsk") or []):
                value = item.get("question") if isinstance(item, dict) else None
                if value and value not in suggestions:
                    suggestions.append(value)
        return JSONResponse({"success": True, "data": {"suggestions": suggestions[:8]}})
    except Exception:  # noqa: BLE001 - les suggestions ne doivent jamais bloquer le formulaire
        return JSONResponse({"success": True, "data": {"suggestions": []}})


@router.post("/post-ideas-autosave")
async def post_ideas_autosave(payload: dict = Body(...), user=Depends(require_auth)):
    """
    Sauvegarde de l'édition inline du post (éditeur de la page de consultation).
    Met à jour le texte de la version courante plutôt que d'en créer une
    nouvelle : l'historique formel de versions est réservé aux actions
    explicites (édition validée, régénération IA).
    """
    idea_id = payload.get("idea_id")
    field = payload.get("field", "post_text")
    value = payload.get("value", "")
    if field != "post_text":
        return JSONResponse({"success": False, "error": "INVALID_FIELD"}, status_code=400)

    pool = get_pool()
    async with pool.acquire() as conn:
        updated = await conn.fetchval(
            """
            UPDATE public.post_versions pv
            SET post_text = $2
            FROM public.post_ideas pi
            WHERE pi.id = $1::uuid AND pi.workspace_id = $3::uuid
              AND pv.id = pi.current_version_id
            RETURNING pv.id::text
            """,
            idea_id, value, user.active_workspace_id,
        )
    if not updated:
        return JSONResponse({"success": False, "error": "NOT_FOUND",
                              "message": "Version courante introuvable."}, status_code=404)
    return JSONResponse({"success": True, "data": {"version_id": updated}})


@router.post("/posts/generate-more")
async def post_generate_more(request: Request, user=Depends(require_auth)):
    """Ajoute des idées en arrière-plan, sans bloquer la requête HTTP."""
    content_type = str(request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        payload = await request.json()
    else:
        form = await request.form()
        payload = dict(form)
    request_id = str(payload.get("request_id") or "").strip()
    try:
        count = max(1, min(8, int(payload.get("additional_count") or payload.get("post_count") or payload.get("count") or 3)))
    except (TypeError, ValueError):
        count = 3
    instructions = str(payload.get("instructions") or payload.get("extra_instructions") or payload.get("append_instructions") or "").strip()
    if not request_id:
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR", "message": "request_id manquant."}, status_code=422)
    try:
        job_id = await post_generation.enqueue_append(
            request_id=request_id, workspace_id=user.active_workspace_id, user_id=user.id,
            count=count, instructions=instructions,
        )
    except LookupError as exc:
        return JSONResponse({"success": False, "error": "NOT_FOUND", "message": str(exc)}, status_code=404)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"success": False, "error": "QUEUE_ERROR", "message": str(exc)}, status_code=500)
    post_generation.kick(job_id)
    return JSONResponse({
        "success": True, "async": True, "status": "queued", "generation_status": "queued",
        "request_id": request_id, "job_id": job_id,
        "redirect_url": f"/app/posts/view?request_id={request_id}&queued=1",
        "message": "Génération additionnelle lancée en arrière-plan."
    }, status_code=202)


@router.get("/posts/generation-status")
async def get_generation_status(request_id: str, user=Depends(require_auth)):
    state = await post_generation.generation_status(request_id=request_id, workspace_id=user.active_workspace_id)
    if state is None:
        return JSONResponse({"success": False, "error": "NOT_FOUND", "message": "Demande introuvable."}, status_code=404)
    return JSONResponse({"success": True, "data": state})


DOMAIN_OPTIONS = ["Intelligence artificielle", "Agents IA", "Automatisation", "Logiciels professionnels",
                   "SaaS", "Analyse d\u2019images et vidéos par IA", "Productivité", "Data Analytics",
                   "Business Intelligence", "Transformation numérique des entreprises"]
AUDIENCE_OPTIONS = ["PME", "Indépendants", "Grandes entreprises", "Directions métiers", "Dirigeants", "DSI / IT"]
FORMAT_OPTIONS = ["LinkedIn · Post", "Facebook · Post", "Facebook · Reel", "Instagram · Post",
                   "Instagram · Story", "Instagram · Reel", "Démo produit", "Cas d\u2019usage",
                   "Conseil pratique", "Avant / Après", "Mini-guide", "Article expert"]


@router.get("/posts/edit", response_class=HTMLResponse)
async def get_post_edit(request: Request, id: str, user=Depends(require_auth)):
    """Port fidèle de "HTML - Edit Request" : édition des paramètres d'une demande."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM public.post_requests WHERE id=$1::uuid AND workspace_id=$2::uuid AND deleted_at IS NULL",
            id, user.active_workspace_id,
        )
    if row is None:
        return RedirectResponse("/app/posts", status_code=302)

    def _load(value, default):
        if value is None:
            return default
        return json.loads(value) if isinstance(value, str) else value

    r = dict(row)
    r["id"] = str(r["id"])
    form_data = _load(r.get("form_data"), {}) or {}
    selected_domains = _load(r.get("content_domains"), []) or []
    selected_audience = _load(r.get("target_audience"), []) or []
    selected_formats = _load(r.get("preferred_formats"), []) or []

    default_tags = form_data.get("default_tags") or ""
    if isinstance(default_tags, list):
        default_tags = " ".join(default_tags)

    return templates.TemplateResponse(request, "posts/edit.html", {
        "auth_user": user, "active_nav": "posts", "r": r,
        "fd": {"company": form_data.get("company") or form_data.get("entreprise") or "",
               "website": form_data.get("website") or form_data.get("site_web") or "",
               "solution": form_data.get("solution") or ""},
        "default_tags": default_tags,
        "multi_data": {
            "domains": {"options": DOMAIN_OPTIONS + selected_domains, "selected": selected_domains},
            "audiences": {"options": AUDIENCE_OPTIONS + selected_audience, "selected": selected_audience},
            "formats": {"options": FORMAT_OPTIONS + selected_formats, "selected": selected_formats},
        },
    })


@router.post("/posts/edit")
async def post_post_edit(request: Request, user=Depends(require_auth)):
    """Enregistre les paramètres modifiés (soumission de formulaire classique)."""
    form = await request.form()
    request_id = form.get("id")
    try:
        post_count = max(1, min(8, int(form.get("post_count") or 3)))
    except (TypeError, ValueError):
        post_count = 3

    pool = get_pool()
    async with pool.acquire() as conn:
        current = await conn.fetchrow(
            "SELECT form_data FROM public.post_requests WHERE id=$1::uuid AND workspace_id=$2::uuid",
            request_id, user.active_workspace_id,
        )
        if current is None:
            return RedirectResponse("/app/posts", status_code=302)
        form_data = current["form_data"]
        form_data = json.loads(form_data) if isinstance(form_data, str) else (form_data or {})
        form_data.update({
            "company": form.get("company", ""), "website": form.get("website", ""),
            "solution": form.get("solution", ""),
            "default_tags": [t for t in str(form.get("default_tags", "")).replace(",", " ").split() if t],
        })

        await conn.execute(
            """
            UPDATE public.post_requests
            SET subject=$2, title=$2, prompt=$3, commercial_objective=$4, target_sector=$5,
                language=$6, constraints=$7, post_count=$8,
                content_domains=$9, target_audience=$10, preferred_formats=$11,
                form_data=$12, updated_at=now()
            WHERE id=$1::uuid AND workspace_id=$13::uuid
            """,
            request_id, form.get("subject", ""), form.get("prompt", ""),
            form.get("commercial_objective", ""), form.get("target_sector", ""),
            form.get("language", "français"), form.get("constraints", ""), post_count,
            json.dumps(form.getlist("content_domains")),
            json.dumps(form.getlist("target_audience")),
            json.dumps(form.getlist("preferred_formats")),
            json.dumps(form_data), user.active_workspace_id,
        )
    return RedirectResponse("/app/posts", status_code=302)


@router.get("/posts/list-page")
async def get_posts_list_page(request: Request, page: int = 1, status: str | None = None,
                               user=Depends(require_auth)):
    """Pagination du tableau des sujets (fragment de lignes pour le scroll infini)."""
    page = max(1, int(page or 1))
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                pr.id::text AS id, pr.title, pr.subject, pr.status, pr.updated_at, pr.created_at,
                u.first_name || ' ' || u.last_name AS created_by_name,
                COUNT(DISTINCT pi.id) FILTER (WHERE pi.deleted_at IS NULL) AS ideas_count,
                COUNT(DISTINCT pi.id) FILTER (WHERE pi.status IN ('validated','approved') AND pi.deleted_at IS NULL) AS approved_count,
                COUNT(DISTINCT pm.id) FILTER (WHERE pm.status='ready' AND COALESCE(pm.public_url,pm.external_url,'')<>'' AND pi.deleted_at IS NULL) AS media_count,
                (SELECT pi0.id::text
                   FROM public.post_ideas pi0
                  WHERE pi0.request_id=pr.id AND pi0.workspace_id=pr.workspace_id AND pi0.deleted_at IS NULL
                  ORDER BY pi0.number ASC, pi0.created_at ASC
                  LIMIT 1) AS first_idea_id
            FROM public.post_requests pr
            LEFT JOIN public.app_users u ON u.id = pr.user_id
            LEFT JOIN public.post_ideas pi ON pi.request_id = pr.id
            LEFT JOIN public.post_media pm ON pm.idea_id = pi.id
            WHERE pr.workspace_id = $1::uuid AND pr.deleted_at IS NULL
              AND ($2::text IS NULL OR pr.status = $2::text)
            GROUP BY pr.id, pr.workspace_id, u.first_name, u.last_name
            ORDER BY pr.updated_at DESC NULLS LAST, pr.created_at DESC
            LIMIT 20 OFFSET $3
            """,
            user.active_workspace_id, status, max(0, page - 1) * 20,
        )
        total = await conn.fetchval(
            "SELECT count(*)::int FROM public.post_requests WHERE workspace_id=$1::uuid AND deleted_at IS NULL "
            "AND ($2::text IS NULL OR status=$2::text)",
            user.active_workspace_id, status,
        )

    out = []
    for r in rows:
        d = dict(r)
        d["last_modified"] = format_user_datetime(d["updated_at"] or d["created_at"], user.timezone)
        d["status_label"] = _status_label(d["status"], d["ideas_count"])
        out.append(d)

    html = render_fragment(request, "posts/_list_rows.html", requests=out)
    loaded = max(0, page - 1) * 20 + len(out)
    return JSONResponse({"success": True, "data": {
        "rows_html": html, "has_more": loaded < total, "next_page": page + 1, "total": total,
    }})


@router.get("/posts/idea-media", response_class=HTMLResponse)
async def get_idea_media_fragment(request: Request, idea_id: str, user=Depends(require_auth)):
    """Chargement différé des médias d'une idée (fragment HTML du carrousel)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id::text, media_type, COALESCE(public_url, external_url) AS url, media_role,
                   prompt, metadata, scenario_text, file_name, mime_type, status, generation_status
            FROM public.post_media
            WHERE idea_id = $1::uuid AND workspace_id = $2::uuid AND status = 'ready'
            ORDER BY created_at
            """,
            idea_id, user.active_workspace_id,
        )
    return templates.TemplateResponse(request, "posts/_media_items.html", {
        "media": [dict(r) for r in rows], "idea_index": request.query_params.get("index", "0"),
    })


@router.post("/post-ideas-media")
async def post_ideas_media(payload: dict = Body(...), user=Depends(require_auth)):
    """
    Action générique sur les médias d'une idée (dispatcher de l'original).
    Redirige vers la logique image/vidéo/import selon `action`.
    """
    from app.routers.media import post_ideas_image, post_ideas_video, post_ideas_media_import

    action = str(payload.get("action", "")).lower()
    if action in ("image", "generate_image"):
        return await post_ideas_image(payload=payload, user=user)
    if action in ("video", "generate_video"):
        return await post_ideas_video(payload=payload, user=user)
    if action in ("import", "import_image"):
        return await post_ideas_media_import(payload=payload, user=user)

    # Sans action explicite : renvoie l'état des médias de l'idée
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id::text, media_type, status, generation_status, "
            "COALESCE(public_url, external_url) AS url, media_role "
            "FROM public.post_media WHERE idea_id=$1::uuid AND workspace_id=$2::uuid ORDER BY created_at",
            payload.get("idea_id"), user.active_workspace_id,
        )
    return JSONResponse({"success": True, "data": {"media": [dict(r) for r in rows]}})
