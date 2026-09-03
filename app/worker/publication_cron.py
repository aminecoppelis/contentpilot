"""Exécution des publications programmées enregistrées par l'interface.

Le clic « Programmer » ne doit jamais appeler Meta/Buffer immédiatement. La
route crée une ligne ``post_publications.status = scheduled`` et ce worker la
prend en charge une fois ``scheduled_at <= now()``.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.database import get_pool
from app.services.publishing import outcome_error, publish_to_account
from app.services.social_accounts import fetch_accessible_account

logger = logging.getLogger("worker.publication")


def _as_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _media_type_from_row(row) -> str:
    value = str((row["media_type"] if row and "media_type" in row else "") or "").lower()
    return value if value in ("image", "video") else "none"


async def _claim_batch(limit: int = 5) -> list[dict]:
    """Réserve atomiquement les publications arrivées à échéance."""
    pool = get_pool()
    async with pool.acquire() as conn:
      async with conn.transaction():
        rows = await conn.fetch(
            """
            SELECT pp.id::text AS publication_id, pp.idea_id::text, pp.workspace_id::text,
                   pp.version_id::text, pp.media_id::text, pp.platform, pp.publication_type,
                   pp.post_text_snapshot, pp.media_url_snapshot, pp.response, pp.scheduled_at,
                   pm.media_type
            FROM public.post_publications pp
            JOIN public.post_ideas pi
              ON pi.id=pp.idea_id AND pi.workspace_id=pp.workspace_id AND pi.deleted_at IS NULL
            JOIN public.post_requests pr
              ON pr.id=pi.request_id AND pr.workspace_id=pp.workspace_id AND pr.deleted_at IS NULL
            LEFT JOIN public.post_media pm
              ON pm.id=pp.media_id AND pm.workspace_id=pp.workspace_id AND pm.idea_id=pp.idea_id
            WHERE pp.status='scheduled'
              AND pp.publish_mode='scheduled'
              AND pp.scheduled_at IS NOT NULL
              AND pp.scheduled_at <= now()
            ORDER BY pp.scheduled_at ASC, pp.created_at ASC, pp.id ASC
            LIMIT $1
            FOR UPDATE OF pp SKIP LOCKED
            """,
            limit,
        )
        ids = [r["publication_id"] for r in rows]
        if ids:
            await conn.execute(
                """
                UPDATE public.post_publications
                SET status='processing', updated_at=now(),
                    response=COALESCE(response,'{}'::jsonb)
                      || jsonb_build_object('worker_claimed_at',now()::text)
                WHERE id = ANY($1::uuid[]) AND status='scheduled'
                """,
                ids,
            )
        return [dict(r) for r in rows]


async def _restore_idea_status(conn, idea_id: str, workspace_id: str) -> None:
    """Après un échec, évite de laisser l'idée bloquée artificiellement en scheduled."""
    still_pending = await conn.fetchval(
        """
        SELECT EXISTS(
          SELECT 1 FROM public.post_publications
          WHERE idea_id=$1::uuid AND workspace_id=$2::uuid
            AND status IN ('scheduled','processing')
        )
        """,
        idea_id, workspace_id,
    )
    if still_pending:
        return
    any_published = await conn.fetchval(
        """
        SELECT EXISTS(
          SELECT 1 FROM public.post_publications
          WHERE idea_id=$1::uuid AND workspace_id=$2::uuid AND status='published'
        )
        """,
        idea_id, workspace_id,
    )
    await conn.execute(
        """
        UPDATE public.post_ideas
        SET status=$3, updated_at=now()
        WHERE id=$1::uuid AND workspace_id=$2::uuid AND deleted_at IS NULL
        """,
        idea_id, workspace_id, "published" if any_published else "approved",
    )


async def run_publication_cycle(limit: int = 5) -> dict:
    jobs = await _claim_batch(limit=limit)
    if not jobs:
        return {"stage": "idle", "processed": 0}

    pool = get_pool()
    published = 0
    failed = 0
    for job in jobs:
        publication_id = job["publication_id"]
        idea_id = job["idea_id"]
        workspace_id = job["workspace_id"]
        base_response = _as_dict(job.get("response"))
        account_id = str(base_response.get("social_account_id") or "").strip()
        published_by_user_id = str(base_response.get("published_by_user_id") or "").strip() or None
        platform = str(job.get("platform") or base_response.get("platform") or "").strip().lower()
        publication_type = str(job.get("publication_type") or base_response.get("publish_content_type") or "standard").strip().lower()
        media_url = str(job.get("media_url_snapshot") or "").strip() or None
        media_type = _media_type_from_row(job)
        text = str(job.get("post_text_snapshot") or "")

        error_message: str | None = None
        outcome: dict = {}
        try:
            async with pool.acquire() as conn:
                still_active = await conn.fetchval(
                    """
                    SELECT EXISTS(
                      SELECT 1
                      FROM public.post_publications pp
                      JOIN public.post_ideas pi
                        ON pi.id=pp.idea_id AND pi.workspace_id=pp.workspace_id AND pi.deleted_at IS NULL
                      JOIN public.post_requests pr
                        ON pr.id=pi.request_id AND pr.workspace_id=pp.workspace_id AND pr.deleted_at IS NULL
                      WHERE pp.id=$1::uuid AND pp.workspace_id=$2::uuid AND pp.status='processing'
                    )
                    """,
                    publication_id, workspace_id,
                )
                if not still_active:
                    continue
                account = await fetch_accessible_account(
                    conn, account_id, workspace_id, active_only=True
                ) if account_id else None
            if account is None:
                error_message = "Le compte social programmé n'est plus actif ou accessible dans ce workspace."
            else:
                outcome = await publish_to_account(
                    account,
                    platform=platform,
                    media_type=media_type,
                    media_url=media_url,
                    text=text,
                    publish_content_type=publication_type,
                    # La date est gérée par notre worker : Buffer doit publier maintenant.
                    buffer_schedule=False,
                )
                error_message = outcome_error(outcome)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Publication programmée %s impossible", publication_id)
            error_message = str(exc)
            outcome = {"error": error_message}

        status = "failed" if error_message else "published"
        response_payload = {**base_response, "provider_response": outcome, "worker_executed": True}
        async with pool.acquire() as conn:
          async with conn.transaction():
            await conn.execute(
                """
                UPDATE public.post_publications
                SET status=$2, response=$3::jsonb, error_message=$4,
                    published_by=CASE
                      WHEN $2='published' AND NULLIF($5::text,'') IS NOT NULL THEN $5::uuid
                      ELSE published_by
                    END,
                    published_at=CASE WHEN $2='published' THEN now() ELSE published_at END,
                    updated_at=now()
                WHERE id=$1::uuid AND workspace_id=$6::uuid
                """,
                publication_id, status, json.dumps(response_payload),
                (error_message or "")[:1800] or None, published_by_user_id, workspace_id,
            )
            if status == "published":
                await conn.execute(
                    """
                    UPDATE public.post_ideas
                    SET status='published', updated_at=now()
                    WHERE id=$1::uuid AND workspace_id=$2::uuid AND deleted_at IS NULL
                    """,
                    idea_id, workspace_id,
                )
            else:
                await _restore_idea_status(conn, idea_id, workspace_id)
            await conn.execute(
                """
                INSERT INTO public.post_activity_logs
                    (workspace_id, entity_type, entity_id, action, details)
                VALUES ($1::uuid,'post_publication',$2::uuid,$3,
                        jsonb_build_object('platform',$4::text,'error',$5::text,'scheduled',true))
                """,
                workspace_id, publication_id, status, platform, error_message or "",
            )
        if status == "published":
            published += 1
        else:
            failed += 1

    return {"stage": "processed", "processed": len(jobs), "published": published, "failed": failed}
