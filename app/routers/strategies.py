"""
Routes des stratégies de croissance IA — Cahier technique §6.6, §7.7, §9.5-9.7.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Request, Depends, Body, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.database import get_pool
from app.dependencies.auth import require_auth
from app.services import ai
from app.services.ai import AIGenerationError
from app.services import meta as meta_client
from app.services import serper as serper_client
from app.services.crypto import decrypt_token
from app.services.social_accounts import fetch_accessible_account
from app.services import strategy_calendar_n8n
from app.worker.calendar_worker import run_cycle
from app.user_timezone import parse_user_datetime, to_user_datetime, format_user_datetime
from app.pagination import page_meta
from app.i18n import resolve_locale

router = APIRouter(tags=["Strategies"])
from app.templating import templates


STRATEGY_STATUS_LABELS = {
    "generating": "Génération en cours", "draft": "Brouillon",
    "active": "Active", "failed": "Échec", "archived": "Archivée",
}
PLATFORM_LABELS = {"facebook": "Facebook", "instagram": "Instagram", "buffer": "Buffer", "linkedin": "LinkedIn"}
def _parse_future_planned_for(value: object, timezone_name: str) -> datetime:
    """Interprète la saisie dans le fuseau utilisateur puis retourne l'instant UTC."""
    parsed = parse_user_datetime(value, timezone_name)
    if parsed <= datetime.now(timezone.utc):
        raise ValueError("La date et l’heure doivent être dans le futur.")
    return parsed


async def _reschedule_calendar_task(conn, *, calendar_id: str, strategy_id: str,
                                    workspace_id: str, planned_for: object, timezone_name: str) -> dict:
    try:
        future = _parse_future_planned_for(planned_for, timezone_name)
    except ValueError as exc:
        return {"success": False, "error": "PAST_OR_INVALID_DATETIME",
                "message": str(exc), "status_code": 422}

    # Même principe que V90 : une tâche finale n'est plus modifiable ; une tâche
    # sans sujet actif est réarmée et tous les verrous/erreurs worker sont nettoyés.
    row = await conn.fetchrow(
        """
        UPDATE public.app_growth_strategy_action_calendar c
        SET planned_for = $2::timestamptz,
            status = 'scheduled',
            request_id = NULL,
            triggered_at = NULL,
            error_message = NULL,
            updated_at = now(),
            payload = jsonb_set(
              jsonb_set(
                (COALESCE(c.payload,'{}'::jsonb)
                  - 'generated_request_id'
                  - 'generation_error'
                  - 'generation_error_node'
                  - 'clean_worker_lock_until'
                  - 'clean_worker_attempt_count')
                || jsonb_build_object(
                  'planned_for',$2::timestamptz::text,
                  'manual_rescheduled',true,
                  'rescheduled_at',now()::text,
                  'requires_reschedule',false,
                  'generation_stage','calendar_rescheduled_waiting_due_date'
                ),
                '{ai_calendar,planned_for}',to_jsonb($2::timestamptz::text),true
              ),
              '{planned_for}',to_jsonb($2::timestamptz::text),true
            )
        WHERE c.id = $1::uuid
          AND c.workspace_id = $3::uuid
          AND c.strategy_id = $4::uuid
          AND lower(COALESCE(c.status,'scheduled')) NOT IN
              ('published','cancelled','canceled','obsolete','skipped','archived','done','generated','completed')
          AND (
            c.request_id IS NULL
            OR NOT EXISTS (
              SELECT 1 FROM public.post_requests pr
              WHERE pr.id=c.request_id AND pr.deleted_at IS NULL
            )
          )
        RETURNING c.id::text, c.planned_for, c.status
        """,
        calendar_id, future, workspace_id, strategy_id,
    )
    if row is None:
        return {"success": False, "error": "NOT_RESCHEDULABLE",
                "message": "Cette tâche possède encore un sujet actif, est terminée ou n’est plus modifiable.",
                "status_code": 409}
    return {"success": True, "message": "Créneau mis à jour.",
            "data": {"calendar_id": row["id"],
                     "planned_for": (to_user_datetime(row["planned_for"], timezone_name) or row["planned_for"]).isoformat(),
                     "timezone": timezone_name,
                     "status": row["status"]},
            "status_code": 200}


@router.get("/strategies", response_class=HTMLResponse)
async def get_strategies(request: Request, strategy_id: str | None = None, page: int = 1,
                         action_page: int = 1, post_page: int = 1, status: str = "all",
                         q: str = "", user=Depends(require_auth)):
    """Liste des stratégies ou détail d'une stratégie lorsque strategy_id est fourni."""
    pool = get_pool()

    def json_object(value):
        if isinstance(value, dict):
            return value
        if value in (None, ""):
            return {}
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, dict) else {}
            except (TypeError, ValueError, json.JSONDecodeError):
                return {}
        return {}

    def json_list(value):
        if isinstance(value, list):
            return value
        if value in (None, ""):
            return []
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return parsed if isinstance(parsed, list) else []
            except (TypeError, ValueError, json.JSONDecodeError):
                return []
        return []

    def format_datetime(value):
        if isinstance(value, datetime):
            return format_user_datetime(value, user.timezone)
        return str(value or "")

    async with pool.acquire() as conn:
        # Un strategy_id ne doit jamais permettre de lire une stratégie d'un autre workspace.
        selected_row = None
        selected_actions_rows = []
        selected_calendar_rows = []
        selected_strategy_post_rows = []
        if strategy_id:
            try:
                selected_row = await conn.fetchrow(
                    """
                    SELECT s.id::text, s.title, s.status, s.objective_type, s.objective_label,
                           s.duration_days, s.form_data, s.network_snapshot, s.research_context,
                           s.strategy_data, s.current_version, s.last_analyzed_at,
                           s.created_at, s.updated_at, s.social_account_id::text,
                           a.provider AS platform, a.display_name AS account_name,
                           a.platform_account_name, a.external_username
                    FROM public.app_growth_strategies s
                    LEFT JOIN public.app_social_accounts a ON a.id = s.social_account_id
                    WHERE s.id = $2::uuid AND s.workspace_id = $1::uuid
                    LIMIT 1
                    """,
                    user.active_workspace_id,
                    strategy_id,
                )
            except Exception as exc:
                # asyncpg lève une erreur de cast si strategy_id n'est pas un UUID.
                if "uuid" in str(exc).lower() or "invalid" in str(exc).lower():
                    raise HTTPException(status_code=404, detail="Stratégie introuvable.") from exc
                raise

            if selected_row is None:
                raise HTTPException(status_code=404, detail="Stratégie introuvable dans ce workspace.")

            action_page = max(1, int(action_page or 1))
            post_page = max(1, int(post_page or 1))
            selected_actions_total = await conn.fetchval(
                "SELECT count(*)::int FROM public.app_growth_strategy_actions WHERE strategy_id=$1::uuid AND workspace_id=$2::uuid",
                strategy_id, user.active_workspace_id,
            )
            selected_actions_rows = await conn.fetch(
                """
                SELECT id::text, title, description, category, priority, status, due_day,
                       kpi, media_prefill, version_no, created_at, updated_at
                FROM public.app_growth_strategy_actions
                WHERE strategy_id = $1::uuid AND workspace_id = $2::uuid
                ORDER BY COALESCE(due_day, 1), created_at, id
                LIMIT 6 OFFSET $3
                """,
                strategy_id,
                user.active_workspace_id,
                (action_page - 1) * 6,
            )
            selected_calendar_rows = await conn.fetch(
                """
                SELECT c.id::text, c.action_id::text, c.request_id::text, c.planned_for,
                       c.status, c.payload, c.error_message, c.triggered_at,
                       c.created_at, c.updated_at,
                       a.title AS action_title, a.category AS action_category,
                       pr.subject AS request_subject, pr.status AS request_status,
                       linked_idea.idea_id, linked_idea.idea_title,
                       linked_idea.idea_status, linked_idea.post_text,
                       linked_idea.post_cta, linked_idea.media_url,
                       EXISTS (
                         SELECT 1
                         FROM public.post_requests linked_request
                         WHERE linked_request.id = c.request_id
                           AND linked_request.deleted_at IS NULL
                       ) AS active_request_exists
                FROM public.app_growth_strategy_action_calendar c
                LEFT JOIN public.app_growth_strategy_actions a ON a.id = c.action_id
                LEFT JOIN public.post_requests pr
                  ON pr.id = c.request_id AND pr.workspace_id = c.workspace_id
                 AND pr.deleted_at IS NULL
                LEFT JOIN LATERAL (
                  SELECT pi.id::text AS idea_id, pi.title AS idea_title,
                         pi.status AS idea_status, pv.post_text,
                         pv.cta AS post_cta,
                         (SELECT COALESCE(pm.public_url,pm.external_url)
                            FROM public.post_media pm
                           WHERE pm.idea_id=pi.id AND pm.workspace_id=pi.workspace_id
                             AND pm.status='ready'
                             AND COALESCE(pm.public_url,pm.external_url,'')<>''
                           ORDER BY (pm.media_role='cover') DESC, pm.created_at ASC
                           LIMIT 1) AS media_url
                  FROM public.post_ideas pi
                  LEFT JOIN public.post_versions pv ON pv.id=pi.current_version_id
                  WHERE pi.request_id = c.request_id
                    AND pi.workspace_id = c.workspace_id
                    AND pi.deleted_at IS NULL
                  ORDER BY pi.number ASC, pi.created_at ASC
                  LIMIT 1
                ) linked_idea ON true
                WHERE c.strategy_id = $1::uuid AND c.workspace_id = $2::uuid
                  -- Les checkpoints adaptatifs servent au pilotage interne de
                  -- la stratégie. Ce ne sont pas des tâches éditoriales et ils
                  -- ne doivent ni apparaître ni être comptés dans le calendrier.
                  AND COALESCE(c.payload->>'kind','') <> 'adaptive_checkpoint'
                ORDER BY c.planned_for ASC, c.created_at ASC
                """,
                strategy_id,
                user.active_workspace_id,
            )
            # Un même sujet/request peut recevoir plusieurs idées (bouton
            # « générer une nouvelle idée »). La vue calendrier reste à une
            # ligne par créneau, mais l'onglet Posts doit lire chaque idea_id.
            selected_posts_total = await conn.fetchval(
                """SELECT count(DISTINCT pi.id)::int
                     FROM public.app_growth_strategy_action_calendar c
                     JOIN public.post_requests pr ON pr.id=c.request_id AND pr.workspace_id=c.workspace_id AND pr.deleted_at IS NULL
                     JOIN public.post_ideas pi ON pi.request_id=pr.id AND pi.workspace_id=c.workspace_id AND pi.deleted_at IS NULL
                     WHERE c.strategy_id=$1::uuid AND c.workspace_id=$2::uuid""",
                strategy_id, user.active_workspace_id,
            )
            selected_strategy_post_rows = await conn.fetch(
                """
                SELECT DISTINCT ON (pi.id)
                       c.action_id::text, c.request_id::text, c.planned_for,
                       a.title AS action_title, pr.subject AS request_subject,
                       pi.id::text AS idea_id, pi.title AS idea_title,
                       pi.status AS idea_status, pv.post_text, pv.cta AS post_cta,
                       (SELECT pm.id::text
                          FROM public.post_media pm
                         WHERE pm.idea_id=pi.id AND pm.workspace_id=pi.workspace_id
                           AND pm.status='ready'
                           AND COALESCE(pm.public_url,pm.external_url,'')<>''
                         ORDER BY (pm.media_role='cover') DESC, pm.created_at ASC
                         LIMIT 1) AS media_id,
                       (SELECT COALESCE(pm.public_url,pm.external_url)
                          FROM public.post_media pm
                         WHERE pm.idea_id=pi.id AND pm.workspace_id=pi.workspace_id
                           AND pm.status='ready'
                           AND COALESCE(pm.public_url,pm.external_url,'')<>''
                         ORDER BY (pm.media_role='cover') DESC, pm.created_at ASC
                         LIMIT 1) AS media_url
                FROM public.app_growth_strategy_action_calendar c
                JOIN public.app_growth_strategy_actions a ON a.id=c.action_id
                JOIN public.post_requests pr
                  ON pr.id=c.request_id AND pr.workspace_id=c.workspace_id
                 AND pr.deleted_at IS NULL
                JOIN public.post_ideas pi
                  ON pi.request_id=pr.id AND pi.workspace_id=c.workspace_id
                 AND pi.deleted_at IS NULL
                LEFT JOIN public.post_versions pv ON pv.id=pi.current_version_id
                WHERE c.strategy_id=$1::uuid AND c.workspace_id=$2::uuid
                ORDER BY pi.id, c.created_at ASC
                LIMIT 6 OFFSET $3
                """,
                strategy_id,
                user.active_workspace_id,
                (post_page - 1) * 6,
            )

        page = max(1, int(page or 1))
        status = status if status in {"all", "active", "draft"} else "all"
        q = (q or "").strip()[:120]
        status_counts = await conn.fetchrow(
            """
            SELECT count(*)::int AS all_count,
                   count(*) FILTER (WHERE status='active')::int AS active_count,
                   count(*) FILTER (WHERE status='draft')::int AS draft_count
            FROM public.app_growth_strategies
            WHERE workspace_id=$1::uuid
            """,
            user.active_workspace_id,
        )
        list_where = """s.workspace_id=$1::uuid
            AND ($2::text = 'all' OR s.status = $2::text)
            AND ($3::text = '' OR concat_ws(' ', s.title, s.objective_label,
                 a.display_name, a.platform_account_name, a.provider) ILIKE '%' || $3::text || '%')"""
        strategies_total = await conn.fetchval(
            f"""SELECT count(*)::int FROM public.app_growth_strategies s
                LEFT JOIN public.app_social_accounts a ON a.id=s.social_account_id
                WHERE {list_where}""",
            user.active_workspace_id, status, q,
        )
        rows = await conn.fetch(
            """
            SELECT s.id::text, s.title, s.status, s.objective_label, s.current_version,
                   COALESCE(s.updated_at, s.created_at) AS updated_at,
                   a.provider AS platform, a.display_name AS account_name,
                   (SELECT count(*) FROM public.app_growth_strategy_actions ga WHERE ga.strategy_id = s.id) AS total_actions,
                   (SELECT count(*) FROM public.app_growth_strategy_actions ga
                     WHERE ga.strategy_id = s.id AND ga.status IN ('done','generated','completed')) AS done_actions
            FROM public.app_growth_strategies s
            LEFT JOIN public.app_social_accounts a ON a.id = s.social_account_id
            WHERE """ + list_where + """
            ORDER BY COALESCE(s.updated_at, s.created_at) DESC
            LIMIT 10 OFFSET $4
            """,
            user.active_workspace_id,
            status,
            q,
            (page - 1) * 10,
        )
        # La page de liste doit rester compatible avec une base mise à jour
        # progressivement. `revoked_at` est une colonne additive récente ; un
        # partage révoqué est déjà `is_active=false`, donc la lecture des comptes
        # actifs n'a pas besoin de dépendre de cette colonne.
        accounts_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (a.id)
                   a.id::text, a.provider, a.display_name, a.platform_account_name
            FROM public.app_social_accounts a
            LEFT JOIN public.app_social_account_workspaces saw
              ON saw.account_id=a.id AND saw.workspace_id=$1::uuid
            WHERE a.deleted_at IS NULL AND a.is_active=true
              AND (a.workspace_id=$1::uuid OR saw.account_id IS NOT NULL)
              AND (
                CASE WHEN saw.account_id IS NULL AND a.workspace_id=$1::uuid THEN true
                     ELSE COALESCE(saw.is_active,false) END
              ) = true
            ORDER BY a.id, a.display_name
            """,
            user.active_workspace_id,
        )

    strategies = []
    for r in rows:
        d = dict(r)
        total = int(d["total_actions"] or 0)
        done = int(d["done_actions"] or 0)
        d["progress_pct"] = round(done * 100 / total) if total else 0
        d["status_label"] = STRATEGY_STATUS_LABELS.get(d["status"], d["status"] or "—")
        d["platform_label"] = PLATFORM_LABELS.get(str(d["platform"] or ""), d["platform"] or "—")
        d["updated_label"] = format_datetime(d["updated_at"])
        strategies.append(d)

    accounts = [
        {"id": a["id"],
         "label": f"{a['display_name'] or a['platform_account_name'] or 'Compte'} · "
                   f"{PLATFORM_LABELS.get(a['provider'], a['provider'])}"}
        for a in accounts_rows
    ]

    if selected_row is not None:
        selected = dict(selected_row)
        selected["form_data"] = json_object(selected.get("form_data"))
        selected["network_snapshot"] = json_object(selected.get("network_snapshot"))
        selected["research_context"] = json_object(selected.get("research_context"))
        selected["strategy_data"] = json_object(selected.get("strategy_data"))
        selected["status_label"] = STRATEGY_STATUS_LABELS.get(selected.get("status"), selected.get("status") or "—")
        selected["platform_label"] = PLATFORM_LABELS.get(str(selected.get("platform") or ""), selected.get("platform") or "—")
        selected["analyzed_label"] = format_datetime(selected.get("last_analyzed_at"))
        selected["updated_label"] = format_datetime(selected.get("updated_at") or selected.get("created_at"))
        selected["account_label"] = selected.get("account_name") or selected.get("platform_account_name") or selected.get("external_username") or ""

        strategy_data = selected["strategy_data"]
        objective = strategy_data.get("objective") if isinstance(strategy_data.get("objective"), dict) else {}
        target_analysis = strategy_data.get("target_analysis") if isinstance(strategy_data.get("target_analysis"), dict) else {}
        selected["executive_summary"] = str(strategy_data.get("executive_summary") or "").strip()
        selected["objective"] = objective
        selected["target_analysis"] = target_analysis
        selected["diagnostic"] = strategy_data.get("diagnostic") if isinstance(strategy_data.get("diagnostic"), dict) else {}
        selected["positioning"] = strategy_data.get("positioning")
        selected["content_pillars"] = json_list(strategy_data.get("content_pillars"))
        selected["recommended_formats"] = json_list(strategy_data.get("recommended_formats"))
        selected["success_conditions"] = json_list(strategy_data.get("success_conditions"))

        actions = []
        for row in selected_actions_rows:
            action = dict(row)
            action["kpi"] = json_object(action.get("kpi"))
            action["media_prefill"] = json_object(action.get("media_prefill"))
            actions.append(action)

        calendar = []
        calendar_view_items = []
        for row in selected_calendar_rows:
            item = dict(row)
            item["payload"] = json_object(item.get("payload"))
            item["planned_label"] = format_datetime(item.get("planned_for"))
            planned_for = item.get("planned_for")
            local_planned = None
            if isinstance(planned_for, datetime):
                local_planned = to_user_datetime(planned_for, user.timezone)
                item["planned_iso"] = planned_for.isoformat()
                item["planned_day"] = local_planned.strftime("%Y-%m-%d") if local_planned else ""
                item["planned_hour"] = local_planned.hour if local_planned else 0
                item["planned_time"] = local_planned.strftime("%H:%M") if local_planned else ""
            else:
                item["planned_iso"] = str(planned_for or "")
                item["planned_day"] = ""
                item["planned_hour"] = 0
                item["planned_time"] = ""
            absolute_planned = planned_for if isinstance(planned_for, datetime) and planned_for.tzinfo else (planned_for.replace(tzinfo=timezone.utc) if isinstance(planned_for, datetime) else None)
            item["is_past"] = bool(absolute_planned is not None and absolute_planned.astimezone(timezone.utc) <= datetime.now(timezone.utc))
            calendar.append(item)
            payload = item["payload"]
            calendar_view_items.append({
                "id": item.get("id") or "",
                "action_id": item.get("action_id") or "",
                "request_id": item.get("request_id") or "",
                "planned_for": item.get("planned_iso") or "",
                "planned_day": item.get("planned_day") or "",
                "planned_hour": int(item.get("planned_hour") or 0),
                "planned_time": item.get("planned_time") or "",
                "planned_label": item.get("planned_label") or "",
                "status": item.get("status") or "scheduled",
                "title": item.get("action_title") or payload.get("action_title") or ((payload.get("action") or {}).get("title") if isinstance(payload.get("action"), dict) else "") or payload.get("subject") or payload.get("theme") or item.get("request_subject") or "Tâche planifiée",
                "category": item.get("action_category") or "",
                "error_message": item.get("error_message") or "",
                "kind": "checkpoint" if str(payload.get("kind") or "") == "adaptive_checkpoint" else "action",
                "active_request_exists": bool(item.get("active_request_exists")),
                # Comme dans le V90, processing/generating/pending_reschedule restent
                # replanifiables tant qu'aucun sujet actif n'est encore lié.
                "editable": str(item.get("status") or "scheduled").lower() not in (
                    "generated", "done", "success", "succeeded", "completed",
                    "published", "cancelled", "canceled", "obsolete", "skipped", "archived"
                ) and not bool(item.get("active_request_exists")),
            })

        posts_by_action: dict[str, list[dict]] = {}
        for calendar_row in selected_calendar_rows:
            calendar_post = dict(calendar_row)
            if not calendar_post.get("request_id") or not calendar_post.get("idea_id"):
                continue
            posts_by_action.setdefault(str(calendar_post.get("action_id") or ""), []).append({
                "request_id": str(calendar_post.get("request_id") or ""),
                "idea_id": str(calendar_post.get("idea_id") or ""),
                "title": calendar_post.get("idea_title") or calendar_post.get("request_subject") or "Post stratégique",
                "status": calendar_post.get("idea_status") or calendar_post.get("request_status") or "generated",
                "planned_label": format_datetime(calendar_post.get("planned_for")),
            })
        strategy_posts = []
        for row in selected_strategy_post_rows:
            post_row = dict(row)
            linked_post = {
                "request_id": str(post_row.get("request_id") or ""),
                "idea_id": str(post_row.get("idea_id") or ""),
                "title": post_row.get("idea_title") or post_row.get("request_subject") or "Post stratégique",
                "status": post_row.get("idea_status") or "generated",
                "planned_label": format_datetime(post_row.get("planned_for")),
                "post_text": str(post_row.get("post_text") or "").strip(),
                "post_cta": str(post_row.get("post_cta") or "").strip(),
                "media_url": str(post_row.get("media_url") or "").strip(),
                "media_id": str(post_row.get("media_id") or "").strip(),
                "action_title": post_row.get("action_title") or "",
            }
            action_links = posts_by_action.setdefault(str(post_row.get("action_id") or ""), [])
            if not any(item.get("idea_id") == linked_post["idea_id"] for item in action_links):
                action_links.append(linked_post)
            strategy_posts.append(linked_post)

        # État de planification par action — même logique de lecture que l'UI n8n :
        # un plan actif empêche un doublon; generation_required distingue
        # « Génération prévue » de « Exécution prévue ».
        active_plan_statuses = {"scheduled", "generating", "generated", "published", "approved", "completed", "success", "succeeded", "done"}
        planned_actions_total = len({
            str(item.get("action_id") or "") for item in calendar
            if item.get("action_id") and str(item.get("status") or "scheduled").lower() in active_plan_statuses
        })
        plans_by_action: dict[str, list[dict]] = {}
        clearable_calendar_count = 0
        for item in calendar:
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            status = str(item.get("status") or payload.get("status") or "scheduled").strip().lower()
            if status == "failed" or (status == "scheduled" and not item.get("request_id") and not item.get("triggered_at")):
                clearable_calendar_count += 1
            action_key = str(item.get("action_id") or ((payload.get("action") or {}).get("id") if isinstance(payload.get("action"), dict) else "") or "").strip()
            if action_key:
                plans_by_action.setdefault(action_key, []).append(item)

        for action_item in actions:
            kpi = action_item.get("kpi") if isinstance(action_item.get("kpi"), dict) else {}
            plan_cfg = kpi.get("calendar_plan") if isinstance(kpi.get("calendar_plan"), dict) else {}
            action_item["deliverable"] = str(kpi.get("deliverable") or "").strip()
            action_item["content_format"] = str(kpi.get("content_format") or kpi.get("format") or "").strip()
            action_item["requires_post_generation"] = bool(plan_cfg.get("generation_required") is True or plan_cfg.get("requires_post_generation") is True)
            rows_for_action = sorted(plans_by_action.get(str(action_item.get("id") or ""), []), key=lambda row: row.get("planned_for") or datetime.max.replace(tzinfo=timezone.utc))
            active_plan = next((row for row in rows_for_action if str(row.get("status") or "").lower() in active_plan_statuses), None)
            action_item["has_active_plan"] = active_plan is not None
            action_item["can_plan"] = active_plan is None
            if active_plan:
                active_payload = active_plan.get("payload") if isinstance(active_plan.get("payload"), dict) else {}
                ai_cal = active_payload.get("ai_calendar") if isinstance(active_payload.get("ai_calendar"), dict) else {}
                generation_raw = active_payload.get("generation_required", ai_cal.get("generation_required"))
                generation_required = strategy_calendar_n8n.explicit_boolean(generation_raw)
                if generation_required is None:
                    generation_required = str(ai_cal.get("schedule_kind") or "") == "publishable_content"
                action_item["plan_generation_required"] = bool(generation_required)
                action_item["plan_status"] = str(active_plan.get("status") or "scheduled")
                action_item["planned_label"] = active_plan.get("planned_label") or ""
                recommended = active_payload.get("recommended_publish_for") or ai_cal.get("recommended_publish_for")
                action_item["recommended_publish_for"] = format_datetime(recommended) if recommended else ""
            else:
                action_item["plan_generation_required"] = action_item["requires_post_generation"]
                action_item["plan_status"] = ""
                action_item["planned_label"] = ""
                action_item["recommended_publish_for"] = ""

            # La fiche stratégie devient la source de vérité du parcours :
            # chaque intervention expose directement les posts créés par ses
            # créneaux, sans obliger l'utilisateur à les retrouver dans la liste globale.
            action_item["linked_posts"] = posts_by_action.get(str(action_item.get("id") or ""), [])

        return templates.TemplateResponse(request, "strategies/detail.html", {
            "auth_user": user,
            "active_nav": "strategies",
            "selected": selected,
            "actions": actions,
            "calendar": calendar,
            "calendar_view_items": calendar_view_items,
            "clearable_calendar_count": clearable_calendar_count,
            "strategy_posts": strategy_posts,
            "actions_total": int(selected_actions_total or 0),
            "posts_total": int(selected_posts_total or 0),
            "planned_actions_total": planned_actions_total,
            "actions_pagination": page_meta(page=action_page, page_size=6,
                total=selected_actions_total, path="/app/strategies",
                query={"strategy_id": strategy_id, "post_page": post_page}, fragment="actions",
                page_param="action_page"),
            "posts_pagination": page_meta(page=post_page, page_size=6,
                total=selected_posts_total, path="/app/strategies",
                query={"strategy_id": strategy_id, "action_page": action_page}, fragment="posts",
                page_param="post_page"),
        })

    return templates.TemplateResponse(request, "strategies/list.html", {
        "auth_user": user, "active_nav": "strategies",
        "strategies": strategies, "accounts": accounts, "strategy_filter": status,
        "strategy_search": q, "strategy_counts": dict(status_counts),
        "pagination": page_meta(page=page, page_size=10, total=strategies_total,
                                path="/app/strategies", query={"status": status, "q": q}),
    })


@router.get("/strategies/new", response_class=HTMLResponse)
async def get_strategy_new(request: Request, user=Depends(require_auth)):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (a.id) a.id::text, a.provider, a.display_name, a.platform_account_name
            FROM public.app_social_accounts a
            LEFT JOIN public.app_social_account_workspaces saw
              ON saw.account_id=a.id AND saw.workspace_id=$1::uuid
            WHERE a.deleted_at IS NULL AND a.is_active=true
              AND (a.workspace_id=$1::uuid OR saw.account_id IS NOT NULL)
              AND (CASE WHEN saw.account_id IS NULL AND a.workspace_id=$1::uuid
                        THEN true ELSE COALESCE(saw.is_active,false) END)=true
            ORDER BY a.id, a.display_name
            """,
            user.active_workspace_id,
        )
    accounts = [{
        "id": row["id"],
        "label": f"{row['display_name'] or row['platform_account_name'] or 'Compte'} · "
                 f"{PLATFORM_LABELS.get(row['provider'], row['provider'])}",
    } for row in rows]
    return templates.TemplateResponse(request, "strategies/new.html", {
        "auth_user": user, "active_nav": "strategies", "accounts": accounts,
    })


async def _generate_strategy_in_background(payload: dict, user, strategy_id: str) -> None:
    try:
        response = await post_strategies_analyze(
            {**payload, "_background_strategy_id": strategy_id}, user
        )
        if int(getattr(response, "status_code", 500) or 500) < 400:
            return
        detail = bytes(getattr(response, "body", b"")).decode("utf-8", errors="replace")[:3500]
        raise RuntimeError(detail or "La génération de stratégie a échoué.")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Background strategy generation failed strategy_id=%s", strategy_id)
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE public.app_growth_strategies
                SET status='failed', strategy_data=COALESCE(strategy_data,'{}'::jsonb)
                    || jsonb_build_object('generation_error',$2::text), updated_at=now()
                WHERE id=$1::uuid
                """,
                strategy_id, str(exc)[:3500],
            )


@router.post("/strategies/generate")
async def post_strategy_generate(request: Request, payload: dict = Body(...), user=Depends(require_auth)):
    payload = dict(payload or {})
    language_by_locale = {"fr": "français", "en": "anglais", "ar": "arabe"}
    accepted_languages = set(language_by_locale.values())
    if str(payload.get("language") or "").strip().lower() not in accepted_languages:
        payload["language"] = language_by_locale.get(resolve_locale(request), "français")
    instructions = str(payload.get("instructions") or "").strip()
    try:
        duration_days = max(1, min(365, int(payload.get("duration_days") or 30)))
    except (TypeError, ValueError):
        duration_days = 30
    if not instructions:
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR", "message": "Instructions manquantes."}, status_code=422)
    social_account_id = str(payload.get("social_account_id") or "").strip() or None
    pool = get_pool()
    async with pool.acquire() as conn:
        if social_account_id:
            account = await fetch_accessible_account(
                conn, social_account_id, user.active_workspace_id, active_only=True
            )
            if account is None:
                return JSONResponse({
                    "success": False, "error": "NOT_FOUND",
                    "message": "Compte social introuvable dans ce workspace.",
                }, status_code=404)
        row = await conn.fetchrow(
            """
            INSERT INTO public.app_growth_strategies (
              workspace_id,social_account_id,created_by,title,objective_type,objective_label,
              status,duration_days,form_data,strategy_data,current_version
            ) VALUES ($1::uuid,$2::uuid,$3::uuid,$4,$5,$6,'generating',$7,$8,'{}'::jsonb,1)
            RETURNING id::text AS strategy_id
            """,
            user.active_workspace_id, social_account_id, user.id,
            instructions[:120], str(payload.get("objective_type") or "custom"),
            str(payload.get("objective_label") or instructions[:240]), duration_days,
            json.dumps(payload),
        )
    strategy_id = row["strategy_id"]
    return JSONResponse({"success": True, "async": True, "status": "generating", "data": {
        "strategy_id": strategy_id, "redirect_url": "/app/strategies",
    }}, status_code=202)


@router.post("/strategies/analyze")
async def post_strategies_analyze(payload: dict = Body(...), user=Depends(require_auth)):
    """Pipeline complet (Cahier technique §7.7) : profil + concurrence + IA + retry si actions vides.

    social_account_id est optionnel : si absent, l'analyse de compte est sautée et
    la stratégie est créée sans compte lié (mode hors-réseau).
    """
    background_strategy_id = str(payload.get("_background_strategy_id") or "").strip()
    payload = {key: value for key, value in payload.items() if key != "_background_strategy_id"}
    pool = get_pool()
    social_account_id = str(payload.get("social_account_id") or "").strip() or None

    account = None
    if social_account_id:
        async with pool.acquire() as conn:
            account = await fetch_accessible_account(
                conn, social_account_id, user.active_workspace_id, active_only=True
            )

    network_snapshot = {"profile_available": False, "biography_available": False, "recent_content": []}
    if account:
        try:
            access_token = decrypt_token(account["token_ciphertext"])
            metadata = json.loads(account["metadata"]) if isinstance(account["metadata"], str) else (account["metadata"] or {})
            provider = str(account["provider"] or "").lower()
            instagram_direct = provider == "instagram" and (
                metadata.get("instagram_direct") is True
                or str(metadata.get("connection_provider") or "").lower() == "meta_direct"
            )
            profile_result = await meta_client.read_strategy_profile(
                provider=provider,
                external_account_id=str(account["external_account_id"] or ""),
                access_token=access_token,
                instagram_direct=instagram_direct,
            )
            profile_body = profile_result.get("body") or {}
            profile_error = profile_body.get("error") if isinstance(profile_body, dict) else None
            profile = {} if profile_error else profile_body

            content_result = await meta_client.read_strategy_recent_content(
                provider=provider,
                external_account_id=str(account["external_account_id"] or ""),
                access_token=access_token,
                instagram_direct=instagram_direct,
                limit=20,
            )
            content_body = content_result.get("body") or {}
            content_error = content_body.get("error") if isinstance(content_body, dict) else None
            content_items = content_body.get("data") if isinstance(content_body, dict) else []
            recent_content = [] if content_error else list(content_items or [])[:20]

            biography_fields = ("biography", "about", "description")
            biography_available = bool(
                not profile_error
                and isinstance(profile_body, dict)
                and any(field in profile_body for field in biography_fields)
            )
            biography = str(
                next((profile.get(field) for field in biography_fields if field in profile), "") or ""
            ).strip() if isinstance(profile, dict) else ""
            network_snapshot = {
                "profile_available": bool(profile),
                # True signifie que Meta a réellement retourné le champ de bio,
                # même si sa valeur actuelle est vide. C'est différent de
                # « bio non récupérée », cas où l'IA ne doit rien conclure.
                "biography_available": biography_available,
                "profile": profile if isinstance(profile, dict) else {},
                "recent_content": recent_content,
                "profile_fetch_status": "success" if not profile_error else "unavailable",
                "content_fetch_status": "success" if not content_error else "unavailable",
                "profile_error": profile_error,
                "content_error": content_error,
                "account": {
                    "provider": provider,
                    "display_name": account["display_name"],
                    "external_username": account["external_username"],
                    "external_account_id": account["external_account_id"],
                    "token_expires_at": account["token_expires_at"].isoformat() if account["token_expires_at"] else None,
                    "connection_provider": metadata.get("connection_provider"),
                },
            }
        except Exception as exc:  # noqa: BLE001
            network_snapshot = {
                "profile_available": False,
                "biography_available": False,
                "recent_content": [],
                "profile_fetch_status": "unavailable",
                "content_fetch_status": "unavailable",
                "error": str(exc),
            }

    research_context = {}
    try:
        research_context = await serper_client.search(payload.get("target", payload.get("objective_label", "")))
    except Exception:  # noqa: BLE001
        research_context = {"should_use": False}

    profile = network_snapshot.get("profile") if isinstance(network_snapshot.get("profile"), dict) else {}
    profile_snapshot = {
        "source": "meta_api" if network_snapshot.get("profile_fetch_status") == "success" else "unavailable",
        "fetch_status": network_snapshot.get("profile_fetch_status", "unavailable"),
        "error": network_snapshot.get("profile_error") or network_snapshot.get("error"),
        "guidance": "",
        "profile": {
            "id": profile.get("id") or profile.get("user_id"),
            "username": profile.get("username") or (network_snapshot.get("account") or {}).get("external_username"),
            "name": profile.get("name") or profile.get("display_name"),
            "biography": str(next((profile.get(k) for k in ("biography", "about", "description") if k in profile), "") or "").strip(),
            "biography_available": bool(network_snapshot.get("biography_available")),
            "website": profile.get("website") or profile.get("link"),
            "followers_count": profile.get("followers_count") or profile.get("fan_count"),
            "follows_count": profile.get("follows_count"),
            "media_count": profile.get("media_count"),
            "category": profile.get("category") or profile.get("account_type"),
        },
    }
    account_snapshot = network_snapshot.get("account") if isinstance(network_snapshot.get("account"), dict) else {}
    context = {
        "platform": account_snapshot.get("provider") or "",
        "profile_goal": payload.get("profile_goal") or payload.get("instructions") or "",
        "growth_target": payload.get("growth_target") if isinstance(payload.get("growth_target"), dict) else {},
        "form_data": payload,
        "account_snapshot": account_snapshot,
        "meta_context": {
            "mode": "meta_direct",
            "provider": account_snapshot.get("provider") or "",
            "profile_fetch_status": network_snapshot.get("profile_fetch_status", "unavailable"),
            "content_fetch_status": network_snapshot.get("content_fetch_status", "unavailable"),
            "profile_error": network_snapshot.get("profile_error"),
            "content_error": network_snapshot.get("content_error"),
        },
        "profile_snapshot": profile_snapshot,
        "recent_network_content": {
            "source": "meta_api",
            "fetch_status": network_snapshot.get("content_fetch_status", "unavailable"),
            "error": network_snapshot.get("content_error"),
            "items": list(network_snapshot.get("recent_content") or [])[:8],
        },
        "publication_history": [],
        "public_pages": [],
        "serper_context": research_context,
        "existing_strategy_data": {},
        "reanalysis": bool(payload.get("strategy_id") or payload.get("regenerate")),
    }

    try:
        result = await ai.generate_strategy(context)
    except AIGenerationError as exc:
        logger.error("AI strategy generation failed (502): %s", exc)
        return JSONResponse({"success": False, "error": "AI_GENERATION_FAILED", "message": str(exc)}, status_code=502)
    except Exception as exc:
        logger.exception("Unexpected error during strategy analysis: %s", exc)
        return JSONResponse({"success": False, "error": "INTERNAL_ERROR", "message": str(exc)}, status_code=500)

    actions = result.parsed.get("actions", [])
    strategy_data = result.parsed.get("strategy", {})
    # Transaction : la stratégie et ses actions forment un tout. Une stratégie
    # enregistrée sans ses actions serait inexploitable (aucune planification possible).
    async with pool.acquire() as conn:
      async with conn.transaction():
        if background_strategy_id:
            strategy_row = await conn.fetchrow(
                """
                UPDATE public.app_growth_strategies
                SET social_account_id=$2::uuid, title=$4, objective_type=$5,
                    objective_label=$6, status='draft', duration_days=$7,
                    form_data=$8, network_snapshot=$9, research_context=$10,
                    strategy_data=$11, last_analyzed_at=now(), updated_at=now()
                WHERE id=$1::uuid AND workspace_id=$3::uuid
                RETURNING id::text AS strategy_id
                """,
                background_strategy_id, social_account_id, user.active_workspace_id,
                strategy_data.get("title", ""), payload.get("objective_type", ""),
                payload.get("objective_label", ""), payload.get("duration_days", 30),
                json.dumps(payload), json.dumps(network_snapshot), json.dumps(research_context),
                json.dumps(strategy_data),
            )
        else:
            strategy_row = await conn.fetchrow(
            """
            INSERT INTO public.app_growth_strategies (
                workspace_id, social_account_id, created_by, title, objective_type, objective_label,
                status, duration_days, form_data, network_snapshot, research_context, strategy_data,
                current_version, last_analyzed_at
            ) VALUES ($1::uuid,$2::uuid,$3::uuid,$4,$5,$6,'draft',$7,$8,$9,$10,$11,1,now())
            RETURNING id::text AS strategy_id
            """,
            user.active_workspace_id, social_account_id, user.id,
            strategy_data.get("title", ""), payload.get("objective_type", ""), payload.get("objective_label", ""),
            payload.get("duration_days", 30), json.dumps(payload), json.dumps(network_snapshot),
            json.dumps(research_context), json.dumps(strategy_data),
            )
        # Insertion en lot (executemany) plutôt qu'un aller-retour par action
        if actions:
            action_rows = []
            target_analysis = strategy_data.get("target_analysis") if isinstance(strategy_data.get("target_analysis"), dict) else {}
            for a in actions:
                # Parité n8n : deliverable/format et surtout calendar_plan sont
                # persistés dans kpi avant la planification. C'est calendar_plan
                # qui porte generation_required/requires_post_generation.
                kpi_payload, media_payload = strategy_calendar_n8n.canonical_action_payload(
                    a, target_analysis=target_analysis, timezone_name=user.timezone
                )
                action_rows.append((
                    strategy_row["strategy_id"], user.active_workspace_id,
                    a.get("title", ""), a.get("description", ""), a.get("category", ""),
                    a.get("priority", "medium"), int(a.get("due_day", 1) or 1),
                    json.dumps(kpi_payload), json.dumps(media_payload),
                ))
            await conn.executemany(
                """
                INSERT INTO public.app_growth_strategy_actions (
                    strategy_id, workspace_id, title, description, category, priority, status, due_day, kpi, media_prefill
                ) VALUES ($1::uuid,$2::uuid,$3,$4,$5,$6,'pending',$7,$8,$9)
                """,
                action_rows,
            )

    return JSONResponse({"success": True, "data": {"strategy_id": strategy_row["strategy_id"], "strategy": strategy_data, "actions": actions}})



@router.post("/strategies/action")
async def post_strategies_action(payload: dict = Body(...), user=Depends(require_auth)):
    """Applique une action stratégie selon le workflow n8n V90 fourni.

    Les actions canoniques sont celles du nœud « Préparer action stratégie » :
    schedule_action_posts / bulk_schedule_action_posts planifient uniquement les
    actions sélectionnées. La création du sujet reste du ressort du worker à
    l'échéance et uniquement lorsque generation_required=true.
    """
    pool = get_pool()
    raw_action = str(payload.get("action") or "").strip()
    strategy_id = str(payload.get("strategy_id") or "").strip()
    if not raw_action:
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR", "message": "Action manquante."}, status_code=422)
    if not strategy_calendar_n8n.is_uuid(strategy_id):
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR", "message": "strategy_id invalide."}, status_code=422)

    # Alias de compatibilité avec l'interface Python antérieure. L'interface V90
    # corrigée envoie directement les noms n8n ci-dessous.
    action = raw_action
    effective_payload = dict(payload)
    if raw_action == "validate":
        action = "set_strategy_status"
        effective_payload["status"] = "active"
    elif raw_action == "delete":
        action = "delete_strategy"
    elif raw_action == "reschedule":
        action = "update_calendar_task"
    elif raw_action == "schedule":
        action = "bulk_schedule_action_posts"

    allowed_actions = {
        "set_action_status", "bulk_set_action_status",
        "schedule_action_posts", "bulk_schedule_action_posts",
        "generate_action_posts", "bulk_generate_action_posts",
        "set_strategy_status", "update_strategy", "delete_strategy", "archive",
        "update_calendar_task", "clear_pending_calendar_tasks",
    }
    if action not in allowed_actions:
        return JSONResponse({"success": False, "error": "INVALID_ACTION", "message": "Action de stratégie non reconnue."}, status_code=400)

    action_id = str(effective_payload.get("action_id") or "").strip()
    action_ids = strategy_calendar_n8n.uuid_list(effective_payload.get("action_ids") or [])
    status = str(effective_payload.get("status") or "").strip().lower()
    if status == "doing":
        status = "in_progress"
    elif status == "cancelled":
        status = "skipped"

    single_actions = {"set_action_status", "generate_action_posts", "schedule_action_posts"}
    bulk_actions = {"bulk_set_action_status", "bulk_generate_action_posts", "bulk_schedule_action_posts"}
    if action in single_actions and not strategy_calendar_n8n.is_uuid(action_id):
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR", "message": "action_id invalide."}, status_code=422)
    if action in bulk_actions and not action_ids:
        # Compatibilité de l'ancien bouton global : récupère toutes les actions,
        # mais ce chemin n'est plus utilisé par l'UI V90.
        if raw_action == "schedule":
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id::text FROM public.app_growth_strategy_actions "
                    "WHERE strategy_id=$1::uuid AND workspace_id=$2::uuid "
                    "AND COALESCE(status,'pending') NOT IN ('done','skipped') ORDER BY due_day, created_at",
                    strategy_id, user.active_workspace_id,
                )
            action_ids = [row["id"] for row in rows]
        if not action_ids:
            return JSONResponse({"success": False, "error": "VALIDATION_ERROR", "message": "Aucune action sélectionnée."}, status_code=422)

    allowed_action_statuses = {"pending", "in_progress", "done", "skipped"}
    allowed_strategy_statuses = {"draft", "active", "paused", "completed"}
    if action in {"set_action_status", "bulk_set_action_status"} and status not in allowed_action_statuses:
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR", "message": "Statut d’action invalide."}, status_code=422)
    if action == "set_strategy_status" and status not in allowed_strategy_statuses:
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR", "message": "Statut de stratégie invalide."}, status_code=422)

    calendar_id = str(effective_payload.get("calendar_id") or effective_payload.get("calendar_task_id") or effective_payload.get("task_id") or "").strip()
    planned_for = str(effective_payload.get("planned_for") or effective_payload.get("planned_at") or effective_payload.get("scheduled_for") or "").strip()
    if action == "update_calendar_task":
        if not strategy_calendar_n8n.is_uuid(calendar_id):
            return JSONResponse({"success": False, "error": "VALIDATION_ERROR", "message": "calendar_id invalide."}, status_code=422)
        try:
            # Le n8n convertit le datetime local du navigateur en ISO avant SQL.
            planned_for = _parse_future_planned_for(planned_for, user.timezone).isoformat()
        except ValueError as exc:
            return JSONResponse({"success": False, "error": "VALIDATION_ERROR", "message": str(exc)}, status_code=422)
    elif action in {"schedule_action_posts", "generate_action_posts"} and planned_for:
        try:
            planned_for = _parse_future_planned_for(planned_for, user.timezone).isoformat()
        except ValueError as exc:
            return JSONResponse({"success": False, "error": "VALIDATION_ERROR", "message": str(exc)}, status_code=422)

    update_fields = {
        "strategy_title": str(effective_payload.get("title") or effective_payload.get("strategy_title") or "").strip()[:180],
        "strategy_objective_label": str(effective_payload.get("objective_label") or effective_payload.get("strategy_objective") or effective_payload.get("objective") or "").strip()[:260],
        "strategy_executive_summary": str(effective_payload.get("executive_summary") or effective_payload.get("summary") or effective_payload.get("strategy_summary") or "").strip()[:1200],
        "strategy_primary_target": str(effective_payload.get("primary_target") or effective_payload.get("target_audience") or effective_payload.get("strategy_target") or "").strip()[:500],
        "strategy_notes": str(effective_payload.get("notes") or effective_payload.get("manual_notes") or effective_payload.get("strategy_notes") or "").strip()[:1200],
    }
    if action == "update_strategy" and not any(update_fields.values()):
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR", "message": "Aucune modification de stratégie fournie."}, status_code=422)

    effective_status = "in_progress" if action in {
        "generate_action_posts", "bulk_generate_action_posts",
        "schedule_action_posts", "bulk_schedule_action_posts",
    } else (status or "pending")

    async with pool.acquire() as conn:
      async with conn.transaction():
        # Les heures IA du SQL n8n (9h, 10h, etc.) sont des heures locales.
        # On exécute donc le SQL dans le fuseau de l'utilisateur, sans dépendre
        # du fuseau PostgreSQL/serveur. Les timestamptz persistés restent absolus.
        await conn.execute("SELECT set_config('TimeZone',$1::text,true)", user.timezone)
        if action in {"schedule_action_posts", "bulk_schedule_action_posts", "generate_action_posts", "bulk_generate_action_posts"}:
            selected_ids = [action_id] if action in {"schedule_action_posts", "generate_action_posts"} else action_ids
            if selected_ids:
                await conn.execute(
                    """
                    UPDATE public.app_growth_strategy_actions
                    SET kpi=jsonb_set(
                          COALESCE(kpi,'{}'::jsonb),
                          '{calendar_plan,audience_timezone}',to_jsonb($4::text),true
                        ), updated_at=now()
                    WHERE strategy_id=$1::uuid AND workspace_id=$2::uuid
                      AND id=ANY($3::uuid[])
                    """,
                    strategy_id, user.active_workspace_id, selected_ids, user.timezone,
                )
        row = await conn.fetchrow(
            strategy_calendar_n8n.APPLY_ACTION_SQL_USER_TZ,
            str(user.active_workspace_id or ""), strategy_id, action_id, action,
            effective_status, "true", "", json.dumps(action_ids), str(user.id or ""),
            update_fields["strategy_title"], update_fields["strategy_objective_label"],
            update_fields["strategy_executive_summary"], update_fields["strategy_primary_target"],
            update_fields["strategy_notes"], calendar_id, planned_for,
        )

    if row is None:
        return JSONResponse({"success": False, "error": "ACTION_FAILED", "message": "Planification impossible."}, status_code=404)
    data = dict(row)
    ok = data.get("success") is True or str(data.get("success") or "").lower() == "true"
    response = {
        "success": ok,
        "status": str(data.get("status") or ""),
        "message": str(data.get("message") or ("Planification IA effectuée." if ok else "Planification impossible.")),
        "action": str(data.get("action") or action),
        "strategy_id": str(data.get("strategy_id") or strategy_id),
        "action_id": str(data.get("action_id") or action_id),
        "selected_count": int(data.get("selected_count") or 0),
        "updated_count": int(data.get("updated_count") or 0),
        "calendar_count": int(data.get("calendar_count") or 0),
        "checkpoint_count": int(data.get("checkpoint_count") or 0),
        "already_planned_count": int(data.get("already_planned_count") or 0),
        "duplicate_skipped_count": int(data.get("duplicate_skipped_count") or 0),
        "obsolete_skipped_count": int(data.get("obsolete_skipped_count") or 0),
        "calendar_task_updated_count": int(data.get("calendar_task_updated_count") or 0),
        "cleared_calendar_count": int(data.get("cleared_calendar_count") or 0),
        "cleared_action_count": int(data.get("cleared_action_count") or 0),
        "deleted_strategy_calendar_count": int(data.get("deleted_strategy_calendar_count") or 0),
        "deleted_strategy_action_count": int(data.get("deleted_strategy_action_count") or 0),
        "deleted_strategy_version_count": int(data.get("deleted_strategy_version_count") or 0),
        "deleted_strategy_empty_request_count": int(data.get("deleted_strategy_empty_request_count") or 0),
        "preserved_strategy_request_count": int(data.get("preserved_strategy_request_count") or 0),
        "calendar_task_update_debug": data.get("calendar_task_update_debug"),
        "first_planned_for": str(data.get("first_planned_for") or ""),
        "last_planned_for": str(data.get("last_planned_for") or ""),
        "generation_status": "scheduled" if int(data.get("calendar_count") or 0) > 0 else "",
        "redirect_url": "/strategies" if action == "delete_strategy" else "",
    }
    return JSONResponse(response, status_code=200 if ok else 404)


@router.post("/strategies/calendar/reschedule")
@router.put("/strategies/calendar/reschedule")
@router.patch("/strategies/calendar/reschedule")
async def reschedule_strategy_calendar_task(payload: dict = Body(...), user=Depends(require_auth)):
    """Endpoint dédié à la modale calendrier.

    POST est la méthode canonique. PUT/PATCH restent acceptées pour compatibilité
    avec une ancienne version du front/proxy et évitent un 405 Method Not Allowed.
    """
    strategy_id = str(payload.get("strategy_id") or "").strip()
    calendar_id = str(payload.get("calendar_id") or "").strip()
    planned_for = payload.get("planned_for")
    if not strategy_id or not calendar_id or not planned_for:
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR",
                             "message": "Stratégie, tâche et créneau sont obligatoires."}, status_code=422)
    pool = get_pool()
    async with pool.acquire() as conn:
        owned = await conn.fetchval(
            "SELECT 1 FROM public.app_growth_strategies "
            "WHERE id=$1::uuid AND workspace_id=$2::uuid AND COALESCE(status,'draft') <> 'archived'",
            strategy_id, user.active_workspace_id)
        if not owned:
            return JSONResponse({"success": False, "error": "NOT_FOUND",
                                 "message": "Stratégie introuvable ou archivée."}, status_code=404)
        outcome = await _reschedule_calendar_task(
            conn, calendar_id=calendar_id, strategy_id=strategy_id,
            workspace_id=user.active_workspace_id, planned_for=planned_for, timezone_name=user.timezone)
    return JSONResponse({k: v for k, v in outcome.items() if k != "status_code"},
                        status_code=int(outcome.get("status_code") or 200))


@router.post("/strategies/overdue/retry")
async def post_strategies_overdue_retry(payload: dict = Body(...), user=Depends(require_auth)):
    """Nettoie les tâches orphelines et remet en file les tâches relançables."""
    strategy_id = str(payload.get("strategy_id") or "").strip() or None
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            WITH orphaned AS (
              UPDATE public.app_growth_strategy_action_calendar c
              SET status='skipped', updated_at=now(),
                  error_message='Tâche orpheline nettoyée : stratégie absente ou archivée.'
              WHERE c.workspace_id=$1::uuid
                AND ($2::uuid IS NULL OR c.strategy_id=$2::uuid)
                AND c.status NOT IN ('done','generated','skipped','cancelled')
                AND NOT EXISTS (
                  SELECT 1 FROM public.app_growth_strategies s
                  WHERE s.id=c.strategy_id AND s.workspace_id=$1::uuid
                    AND COALESCE(s.status,'draft') <> 'archived'
                )
              RETURNING c.id
            ), reset_failed AS (
              UPDATE public.app_growth_strategy_action_calendar c
              SET status='scheduled', error_message=NULL, updated_at=now(),
                  request_id=NULL, triggered_at=NULL,
                  payload=COALESCE(c.payload,'{}'::jsonb)
                    - 'clean_worker_lock_until' - 'clean_worker_attempt_count'
                    || jsonb_build_object('generation_stage','waiting_retry')
              WHERE c.workspace_id=$1::uuid
                AND ($2::uuid IS NULL OR c.strategy_id=$2::uuid)
                AND c.status='failed'
                AND EXISTS (
                  SELECT 1 FROM public.app_growth_strategies s
                  WHERE s.id=c.strategy_id AND s.workspace_id=$1::uuid
                    AND COALESCE(s.status,'draft') <> 'archived'
                )
              RETURNING c.id
            ), reset_stale AS (
              UPDATE public.app_growth_strategy_action_calendar c
              SET status='scheduled', error_message=NULL, updated_at=now(),
                  triggered_at=NULL,
                  payload=COALESCE(c.payload,'{}'::jsonb)
                    - 'clean_worker_lock_until' - 'clean_worker_attempt_count'
                    || jsonb_build_object('generation_stage','waiting_retry')
              WHERE c.workspace_id=$1::uuid
                AND ($2::uuid IS NULL OR c.strategy_id=$2::uuid)
                AND c.status IN ('generating','processing')
                AND c.request_id IS NULL
                AND c.updated_at < now() - interval '10 minutes'
                AND EXISTS (
                  SELECT 1 FROM public.app_growth_strategies s
                  WHERE s.id=c.strategy_id AND s.workspace_id=$1::uuid
                    AND COALESCE(s.status,'draft') <> 'archived'
                )
              RETURNING c.id
            )
            SELECT
              (SELECT count(*) FROM orphaned)::int AS cleaned_count,
              (SELECT count(*) FROM reset_failed)::int AS failed_requeued,
              (SELECT count(*) FROM reset_stale)::int AS stale_requeued,
              (SELECT count(*)::int
               FROM public.app_growth_strategy_action_calendar c
               WHERE c.workspace_id=$1::uuid
                 AND ($2::uuid IS NULL OR c.strategy_id=$2::uuid)
                 AND c.status IN ('scheduled','retry')
                 AND c.planned_for <= now()) AS due_count
            """,
            user.active_workspace_id, strategy_id,
        )
    cleaned = int(row["cleaned_count"] or 0)
    requeued = int(row["failed_requeued"] or 0) + int(row["stale_requeued"] or 0)
    due_count = int(row["due_count"] or 0)
    queued_count = max(requeued, due_count)
    if queued_count > 0:
        # Lance un cycle immédiatement ; les verrous SQL du worker empêchent les doublons
        # si le scheduler démarre au même instant.
        asyncio.create_task(run_cycle())
    message = (
        f"Vérification terminée : {cleaned} tâche(s) orpheline(s) nettoyée(s), "
        f"{requeued} tâche(s) remise(s) en file, {due_count} tâche(s) due(s)."
    )
    return JSONResponse({
        "success": True, "message": message, "queued_count": queued_count,
        "data": {"cleaned_count": cleaned, "requeued_count": requeued, "due_count": due_count},
    })


@router.post("/strategies/instructions/generate")
async def post_generate_instructions(payload: dict = Body(...), user=Depends(require_auth)):
    """
    Bouton « Générer avec l'IA » de la modale de création : produit une
    instruction complète à partir de la phrase saisie, de la durée et,
    lorsqu'il est présent, du compte social choisi.
    """
    pool = get_pool()
    account_id = str(payload.get("social_account_id") or "").strip() or None
    duration_days = payload.get("duration_days") or 30
    language = payload.get("language", "français")
    seed_instructions = str(payload.get("instructions") or payload.get("prompt") or "").strip()
    if not seed_instructions:
        return JSONResponse({
            "success": False, "error": "VALIDATION_ERROR",
            "message": "Saisissez une phrase de départ avant de générer avec l’IA.",
        }, status_code=422)

    account = None
    if account_id:
        async with pool.acquire() as conn:
            account = await fetch_accessible_account(
                conn, account_id, user.active_workspace_id, active_only=True
            )
        if account is None:
            return JSONResponse({"success": False, "error": "NOT_FOUND",
                                  "message": "Compte social introuvable."}, status_code=404)

    if account:
        subject = (f"Stratégie de croissance {account['provider']} pour "
                   f"{account['display_name'] or account['platform_account_name'] or 'le compte'} : "
                   f"{seed_instructions}")
    else:
        subject = seed_instructions

    context = {
        "subject": subject,
        "prompt": seed_instructions,
        "prompt_mode": "improve",
        "language": language,
        "commercial_objective": f"croissance organique sur {duration_days} jours",
        "target_sector": "",
        "constraints": "Conserve fidèlement l'intention de la phrase saisie. Rédige une instruction "
                       "de stratégie contenant une section Problématique et une section Objectif "
                       "quantifiable, adaptée au réseau s'il est connu et à la durée.",
    }
    try:
        result = await ai.reformulate_prompt(context)
    except AIGenerationError as exc:
        return JSONResponse({"success": False, "error": "AI_GENERATION_FAILED",
                              "message": str(exc)}, status_code=502)

    return JSONResponse({"success": True, "data": {"instructions": result.parsed.get("prompt", "")}})
