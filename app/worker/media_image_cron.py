"""Worker persistant des images IA, parité du branchement asynchrone n8n V90."""
from __future__ import annotations

import asyncio
import json
import logging

from app.database import get_pool
from app.services import media_generation as media_gen
from app.services.image_result import find_image_source, image_bytes
from app.services.media_storage import public_url, write_media

logger = logging.getLogger("worker.media_image")
MAX_ATTEMPTS = 3


async def _claim(media_id: str | None = None):
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                WITH candidate AS (
                  SELECT id
                  FROM public.post_media
                  WHERE media_type='image' AND source='ai_generated' AND status='pending'
                    AND ($1::uuid IS NULL OR id=$1::uuid)
                    AND (
                      generation_status IN ('queued','retry')
                      OR (generation_status='running' AND COALESCE(NULLIF(metadata->>'image_lock_until','')::timestamptz,now()-interval '1 second') < now())
                    )
                    AND COALESCE(NULLIF(metadata->>'image_attempt_count','')::int,0) < $2
                  ORDER BY created_at ASC
                  LIMIT 1 FOR UPDATE SKIP LOCKED
                )
                UPDATE public.post_media pm
                SET generation_status='running', updated_at=now(),
                    metadata=COALESCE(pm.metadata,'{}'::jsonb) || jsonb_build_object(
                      'image_attempt_count',COALESCE(NULLIF(pm.metadata->>'image_attempt_count','')::int,0)+1,
                      'image_lock_until',(now()+interval '10 minutes')::text,
                      'image_last_attempt_at',now()::text
                    )
                FROM candidate c WHERE pm.id=c.id
                RETURNING pm.*
                """, media_id, MAX_ATTEMPTS)
    return row


async def run_image_generation_cycle(media_id: str | None = None) -> dict:
    row = await _claim(media_id)
    if row is None:
        return {"stage": "idle"}
    mid = str(row["id"])
    metadata = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
    job = metadata.get("image_job") if isinstance(metadata.get("image_job"), dict) else {}
    attempt = int(metadata.get("image_attempt_count") or 1)
    try:
        result = await media_gen.generate_image(
            prompt=str(row["prompt"] or job.get("prompt") or "Visuel professionnel B2B"),
            model=str(job.get("image_model") or media_gen.IMAGE_MODEL_DEFAULT),
            aspect_ratio=str(job.get("aspect_ratio") or "4:5"),
            quality=str(job.get("quality") or "standard"),
            image_refs=[str(v) for v in (job.get("image_refs") or []) if str(v).strip()],
        )
        source = find_image_source(result)
        if not source:
            finish = ""
            try:
                finish = str((result.get("choices") or [{}])[0].get("finish_reason") or "")
            except Exception:
                finish = ""
            raise ValueError("Aucune image exploitable n'a été renvoyée par OpenRouter" + (f" (finish_reason={finish})" if finish else "") + ".")
        data, suffix, mime = await image_bytes(source)
        file_path, file_name, size_bytes = write_media(mid, data, suffix)
        url = public_url(file_name)
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE public.post_media SET external_url=$2,public_url=$3,file_path=$4,file_name=$5,
                  mime_type=$6,size_bytes=$7,status='ready',generation_status='done',error_message=NULL,
                  metadata=(COALESCE(metadata,'{}'::jsonb)-'image_lock_until') || $8::jsonb,updated_at=now()
                WHERE id=$1::uuid
                """, mid, source if source.startswith(("http://","https://")) else None, url, file_path, file_name,
                mime, size_bytes, json.dumps({"image_provider_response_saved": True}))
        return {"stage":"done","media_id":mid,"url":url}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Image generation failed media_id=%s", mid)
        final = attempt >= MAX_ATTEMPTS
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE public.post_media SET status=$2,generation_status=$3,error_message=$4,
                  metadata=(COALESCE(metadata,'{}'::jsonb)-'image_lock_until'),updated_at=now()
                WHERE id=$1::uuid
                """, mid, "error" if final else "pending", "error" if final else "retry", str(exc)[:3000])
        return {"stage":"failed" if final else "retry","media_id":mid,"detail":str(exc)}


def kick_image_generation(media_id: str) -> None:
    asyncio.create_task(run_image_generation_cycle(media_id))
