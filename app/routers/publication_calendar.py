"""Publication calendar: historical events and safe rescheduling of queued sends."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.database import get_pool
from app.dependencies.auth import require_auth
from app.user_timezone import parse_user_datetime

router = APIRouter(tags=["Publication calendar"])
EVENT_TIME = "CASE WHEN pp.status='published' THEN COALESCE(pp.published_at,pp.scheduled_at,pp.created_at) ELSE COALESCE(pp.scheduled_at,pp.created_at) END"
STATUSES = {"all", "scheduled", "published", "failed", "pending", "processing", "cancelled"}


@router.get("/publication-calendar")
async def legacy_calendar(strategy_id: UUID | None = None, user=Depends(require_auth)):
    return RedirectResponse(f"/app/strategies?strategy_id={strategy_id}#calendar" if strategy_id else "/app/strategies", status_code=302)


@router.get("/publication-calendar/events")
async def calendar_events(start: AwareDatetime, end: AwareDatetime, strategy_id: UUID,
                          status: str = "all", platform: str = Query("all", max_length=32),
                          user=Depends(require_auth)):
    if end <= start or end - start > timedelta(days=100) or status not in STATUSES:
        raise HTTPException(status_code=422, detail="Invalid calendar range or status")
    async with get_pool().acquire() as conn:
        exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM public.app_growth_strategies WHERE id=$1::uuid AND workspace_id=$2::uuid)",
            strategy_id, user.active_workspace_id,
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Strategy not found")
        rows = await conn.fetch(
            f"""SELECT pp.id::text AS id, pp.status, pp.platform, pp.publish_mode,
                       pp.scheduled_at, COALESCE(pp.updated_at,pp.created_at) AS revision,
                       {EVENT_TIME} AS event_time, pi.title, pi.id::text AS idea_id,
                       pr.id::text AS request_id,
                       (pi.deleted_at IS NULL AND pr.deleted_at IS NULL AND pr.id IS NOT NULL) AS can_open,
                       COALESCE(a.display_name,a.platform_account_name,'') AS account
                FROM public.post_publications pp
                LEFT JOIN public.post_ideas pi ON pi.id=pp.idea_id AND pi.workspace_id=pp.workspace_id
                LEFT JOIN public.post_requests pr ON pr.id=pi.request_id AND pr.workspace_id=pp.workspace_id
                LEFT JOIN public.app_social_accounts a ON a.id::text=pp.response->>'social_account_id'
                WHERE pp.workspace_id=$1::uuid AND ({EVENT_TIME}) >= $2::timestamptz
                  AND ({EVENT_TIME}) < $3::timestamptz
                  AND ($4='all' OR pp.status=$4) AND ($5='all' OR pp.platform=$5)
                  AND EXISTS (SELECT 1 FROM public.app_growth_strategy_action_calendar c
                    WHERE c.strategy_id=$6::uuid AND c.workspace_id=pp.workspace_id AND c.request_id=pi.request_id)
                ORDER BY event_time, pp.id""",
            user.active_workspace_id, start, end, status, platform, strategy_id,
        )
    events = []
    for r in rows:
        events.append({
            "Id": r["id"], "Subject": r["title"] or "", "StartTime": r["event_time"],
            "EndTime": r["event_time"] + timedelta(minutes=30),
            "IsReadonly": r["status"] != "scheduled" or r["publish_mode"] != "scheduled" or not r["can_open"],
            "Status": r["status"], "Platform": r["platform"], "Account": r["account"],
            "Revision": r["revision"], "ScheduledAt": r["scheduled_at"],
            "PostUrl": f"/app/posts/view?request_id={r['request_id']}&idea_id={r['idea_id']}" if r["can_open"] else "/app/published",
        })
    return {"success": True, "data": events}


@router.get("/strategy-calendar/actions")
async def action_events(start: AwareDatetime, end: AwareDatetime, strategy_id: UUID,
                        user=Depends(require_auth)):
    if end <= start or end - start > timedelta(days=100):
        raise HTTPException(status_code=422, detail="Invalid calendar range")
    async with get_pool().acquire() as conn:
        exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM public.app_growth_strategies WHERE id=$1::uuid AND workspace_id=$2::uuid)",
            strategy_id, user.active_workspace_id)
        if not exists:
            raise HTTPException(status_code=404, detail="Strategy not found")
        rows = await conn.fetch(
            """SELECT c.id::text, c.planned_for, c.status, c.request_id::text,
                      COALESCE(a.title,c.payload->>'action_title','') AS title,
                      EXISTS(SELECT 1 FROM public.post_requests pr
                        WHERE pr.id=c.request_id AND pr.workspace_id=c.workspace_id
                          AND pr.deleted_at IS NULL) AS active_request_exists
               FROM public.app_growth_strategy_action_calendar c
               LEFT JOIN public.app_growth_strategy_actions a ON a.id=c.action_id AND a.workspace_id=c.workspace_id
               WHERE c.workspace_id=$1::uuid AND c.strategy_id=$2::uuid
                 AND c.planned_for >= $3 AND c.planned_for < $4
                 AND COALESCE(c.payload->>'kind','') <> 'adaptive_checkpoint'
               ORDER BY c.planned_for,c.id""",
            user.active_workspace_id, strategy_id, start, end)
    terminal = {"generated", "done", "success", "succeeded", "completed", "published",
                "cancelled", "canceled", "obsolete", "skipped", "archived", "processing", "generating", "running"}
    return {"success": True, "data": [{
        "Id": "action:" + r["id"], "ActionId": r["id"], "Kind": "action",
        "Subject": r["title"], "StartTime": r["planned_for"],
        "EndTime": r["planned_for"] + timedelta(minutes=30), "Status": r["status"],
        "IsReadonly": r["status"].lower() in terminal or r["active_request_exists"],
        "Platform": "", "Account": "",
        "PostUrl": f"/app/posts/view?request_id={r['request_id']}" if r["active_request_exists"] else "",
    } for r in rows]}


class ReschedulePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheduled_at: str = Field(min_length=10, max_length=50)
    expected_updated_at: AwareDatetime
    strategy_id: UUID


@router.put("/publication-calendar/{publication_id}")
async def reschedule_publication(publication_id: UUID, payload: ReschedulePayload,
                                 user=Depends(require_auth)):
    try:
        instant = parse_user_datetime(payload.scheduled_at, user.timezone)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid publication date") from None
    if instant <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Publication date must be in the future")
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """UPDATE public.post_publications pp
                   SET scheduled_at=$3::timestamptz, updated_at=now()
                   WHERE pp.id=$1::uuid AND pp.workspace_id=$2::uuid
                     AND pp.status='scheduled' AND pp.publish_mode='scheduled'
                     AND COALESCE(pp.updated_at,pp.created_at)=$4::timestamptz AND $3>now()
                     AND EXISTS (
                       SELECT 1 FROM public.post_ideas pi JOIN public.post_requests pr
                         ON pr.id=pi.request_id AND pr.workspace_id=pi.workspace_id
                       WHERE pi.id=pp.idea_id AND pi.workspace_id=pp.workspace_id
                         AND pi.deleted_at IS NULL AND pr.deleted_at IS NULL)
                     AND EXISTS (SELECT 1 FROM public.app_growth_strategy_action_calendar c
                       JOIN public.post_ideas pi ON pi.request_id=c.request_id AND pi.workspace_id=c.workspace_id
                       WHERE c.strategy_id=$5::uuid AND c.workspace_id=pp.workspace_id AND pi.id=pp.idea_id)
                   RETURNING pp.idea_id, pp.scheduled_at, pp.updated_at""",
                publication_id, user.active_workspace_id, instant, payload.expected_updated_at, payload.strategy_id,
            )
            if row is None:
                raise HTTPException(status_code=409, detail="Publication is no longer editable or has changed")
            await conn.execute(
                """INSERT INTO public.post_activity_logs (workspace_id,entity_type,entity_id,action,details)
                   VALUES ($1::uuid,'post_publication',$2::uuid,'rescheduled',$3::jsonb)""",
                user.active_workspace_id, publication_id,
                json.dumps({"scheduled_at": instant.isoformat(), "changed_by": user.id}),
            )
    return {"success": True, "data": {"scheduled_at": row["scheduled_at"], "updated_at": row["updated_at"]}}
