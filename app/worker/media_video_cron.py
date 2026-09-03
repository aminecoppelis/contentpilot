"""Polling fiable des vidéos IA asynchrones.

La route de création rend immédiatement la main au navigateur. Ce job reprend
les lignes ``queued/running`` après un reload ou un redémarrage et persiste le
MP4 dans ``public-media/`` dès que le fournisseur fournit l'URL de téléchargement.
"""
from __future__ import annotations

import json
import logging

from app.database import get_pool
from app.services import media_generation as media_gen
from app.services.media_storage import persist_video_download

logger = logging.getLogger("worker.media_video")
TERMINAL_FAILURES = {"failed", "error", "cancelled", "canceled", "rejected"}


def _as_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


async def _claim_batch(limit: int = 3) -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
      async with conn.transaction():
        rows = await conn.fetch(
            """
            SELECT id::text, metadata
            FROM public.post_media
            WHERE media_type='video'
              AND status IN ('pending','processing')
              AND generation_status IN ('queued','running')
              AND COALESCE(metadata->>'polling_url',metadata->>'job_id',metadata->>'openrouter_job_id','') <> ''
            ORDER BY updated_at ASC, created_at ASC
            LIMIT $1
            FOR UPDATE SKIP LOCKED
            """,
            limit,
        )
        ids = [r["id"] for r in rows]
        if ids:
            await conn.execute(
                """
                UPDATE public.post_media
                SET generation_status='running', updated_at=now()
                WHERE id = ANY($1::uuid[])
                """,
                ids,
            )
        return [{"id": r["id"], "metadata": _as_dict(r["metadata"])} for r in rows]


async def run_video_poll_cycle(limit: int = 3) -> dict:
    jobs = await _claim_batch(limit=limit)
    if not jobs:
        return {"stage": "idle", "processed": 0}

    pool = get_pool()
    completed = 0
    failed = 0
    pending = 0
    for job in jobs:
        media_id = job["id"]
        metadata = job["metadata"]
        polling_url = media_gen.normalize_video_polling_url(metadata.get("polling_url") or "")
        if not polling_url:
            fallback_id = str(metadata.get("job_id") or metadata.get("openrouter_job_id") or "").strip()
            polling_url = media_gen.video_job_reference({"id": fallback_id})["polling_url"] if fallback_id else ""
        if not polling_url:
            continue
        try:
            result = await media_gen.poll_video_status(polling_url)
            result = result if isinstance(result, dict) else {}
            fallback_job_id = str(
                metadata.get("job_id") or metadata.get("openrouter_job_id")
                or ((metadata.get("raw_create_response") or {}).get("id") if isinstance(metadata.get("raw_create_response"), dict) else "")
                or ""
            ).strip()
            info = media_gen.video_status_info(result, fallback_job_id=fallback_job_id)
            download_url = info["download_url"]
            status = info["status"]

            if download_url:
                await persist_video_download(media_id, download_url)
                completed += 1
                continue

            explicit_error = info["error"]
            if status in TERMINAL_FAILURES or explicit_error:
                message = explicit_error.get("message") if isinstance(explicit_error, dict) else str(explicit_error or status)
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE public.post_media
                        SET status='error', generation_status='error', error_message=$2,
                            metadata=COALESCE(metadata,'{}'::jsonb) || jsonb_build_object('last_poll',$3::jsonb),
                            updated_at=now()
                        WHERE id=$1::uuid
                        """,
                        media_id, message[:1800], json.dumps(result),
                    )
                failed += 1
                continue

            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE public.post_media
                    SET status='pending', generation_status='running',
                        metadata=COALESCE(metadata,'{}'::jsonb) || jsonb_build_object('last_poll',$2::jsonb),
                        updated_at=now()
                    WHERE id=$1::uuid
                    """,
                    media_id, json.dumps(result),
                )
            pending += 1
        except Exception as exc:  # noqa: BLE001
            # Une erreur réseau temporaire ne doit pas perdre le rendu : on garde
            # la tâche en running pour le cycle suivant.
            logger.warning("Polling vidéo %s impossible: %s", media_id, exc)
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE public.post_media
                    SET generation_status='running',
                        metadata=COALESCE(metadata,'{}'::jsonb) || jsonb_build_object('last_poll_error',$2::text),
                        updated_at=now()
                    WHERE id=$1::uuid
                    """,
                    media_id, str(exc)[:1200],
                )
            pending += 1

    return {"stage": "processed", "processed": len(jobs), "completed": completed,
            "failed": failed, "pending": pending}
