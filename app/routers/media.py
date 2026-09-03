"""
Routes de génération et gestion des médias — Cahier technique §6.3, §7.5.
Utilise app/services/media_generation.py (port exact des payloads
OpenRouter réels découverts dans le workflow source : modèles
x-ai/grok-imagine-image-quality / openai/gpt-5-image-mini pour l'image,
x-ai/grok-imagine-video pour la vidéo).
"""
from __future__ import annotations

import base64
import json
import re

import httpx

from fastapi import APIRouter, Depends, Body
from fastapi.responses import JSONResponse

from app.database import get_pool
from app.dependencies.auth import require_auth
from app.services import media_generation as media_gen
from app.services.media_storage import public_url as _public_url, write_media as _write_media, persist_video_download

router = APIRouter(tags=["Media"])


async def _idea_exists(idea_id: str, workspace_id: str) -> bool:
    if not idea_id or not workspace_id:
        return False
    pool = get_pool()
    async with pool.acquire() as conn:
        return bool(await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM public.post_ideas WHERE id=$1::uuid AND workspace_id=$2::uuid AND deleted_at IS NULL)",
            idea_id, workspace_id,
        ))


def _normalize_image_source(value) -> str:
    """Normalise les formes image retournées par OpenRouter comme le parser V90."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text:
        return ""
    if text.lower().startswith("data:image/") or text.startswith(("https://", "http://")):
        return text
    compact = re.sub(r"\s+", "", text)
    if len(compact) > 500 and re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", compact):
        return "data:image/png;base64," + compact
    return ""


def _find_image_source(value, seen: set[int] | None = None) -> str:
    """Recherche récursivement URL/data/base64 dans les réponses /images et /chat/completions."""
    direct = _normalize_image_source(value)
    if direct:
        return direct
    if not isinstance(value, (dict, list, tuple)):
        return ""
    if seen is None:
        seen = set()
    marker = id(value)
    if marker in seen:
        return ""
    seen.add(marker)
    if isinstance(value, (list, tuple)):
        for item in value:
            found = _find_image_source(item, seen)
            if found:
                return found
        return ""
    for key in ("url", "image_url", "imageUrl", "image", "b64_json", "base64", "data_url"):
        candidate = value.get(key)
        if isinstance(candidate, dict) and key in {"image_url", "imageUrl", "image"}:
            candidate = candidate.get("url") or candidate.get("data") or candidate
        found = _normalize_image_source(candidate)
        if found:
            return found
    if isinstance(value.get("data"), str):
        found = _normalize_image_source(value.get("data"))
        if found:
            return found
    for key in ("images", "image", "output", "content", "message", "result", "data",
                "artifacts", "choices", "generations"):
        if key in value:
            found = _find_image_source(value.get(key), seen)
            if found:
                return found
    # Dernier recours : certains fournisseurs changent le nom du conteneur.
    for candidate in value.values():
        found = _find_image_source(candidate, seen)
        if found:
            return found
    return ""


async def _image_bytes(source: str) -> tuple[bytes, str, str]:
    source = str(source or "").strip()
    if source.startswith("data:image/"):
        header, encoded = source.split(",", 1)
        mime = header.split(";", 1)[0].split(":", 1)[1]
        data = base64.b64decode(encoded)
    elif source.startswith(("https://", "http://")):
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
            response = await client.get(source)
            response.raise_for_status()
            data = response.content
            mime = (response.headers.get("content-type") or "image/jpeg").split(";", 1)[0].strip().lower()
    else:
        raise ValueError("L'IA n'a retourné aucune image exploitable.")
    if mime == "image/png" or data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data, ".png", "image/png"
    if mime in ("image/webp",) or data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return data, ".webp", "image/webp"
    return data, ".jpg", "image/jpeg"



@router.post("/post-ideas-media-assist")
async def post_ideas_media_assist(payload: dict = Body(...), user=Depends(require_auth)):
    """Bouton « Générer avec l'IA » du modal média, contextualisé avec l'idée courante."""
    idea_id = str(payload.get("idea_id") or "").strip()
    if not idea_id:
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR", "message": "Idée manquante."}, status_code=422)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT pi.title, pi.hook, pi.summary, pi.raw_idea, pv.post_text
            FROM public.post_ideas pi
            LEFT JOIN public.post_versions pv ON pv.id=pi.current_version_id
            WHERE pi.id=$1::uuid AND pi.workspace_id=$2::uuid AND pi.deleted_at IS NULL
            """, idea_id, user.active_workspace_id,
        )
    if row is None:
        return JSONResponse({"success": False, "error": "NOT_FOUND", "message": "Idée introuvable."}, status_code=404)
    raw = row["raw_idea"]
    raw = json.loads(raw) if isinstance(raw, str) else (raw or {})
    context = "\n\n".join(str(v).strip() for v in [
        row["title"], row["hook"], row["summary"], row["post_text"],
        raw.get("business_problem_solved"), raw.get("ai_or_software_solution"),
        raw.get("concrete_application_example"),
    ] if str(v or "").strip())
    media_type = "video" if str(payload.get("media_type") or "").lower() == "video" else "image"
    try:
        instructions = await media_gen.generate_media_instructions(
            media_type=media_type, context=context,
            aspect_ratio=str(payload.get("aspect_ratio") or ("9:16" if media_type == "video" else "4:5")),
            styles=payload.get("styles") if isinstance(payload.get("styles"), list) else [],
            current_instructions=str(payload.get("current_instructions") or ""),
            duration=int(payload.get("duration") or 6),
        )
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:800] if exc.response is not None else str(exc)
        return JSONResponse({"success": False, "error": "AI_ASSIST_FAILED", "message": f"OpenRouter a refusé l'aide média : {detail}"}, status_code=502)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"success": False, "error": "AI_ASSIST_FAILED", "message": str(exc)}, status_code=502)
    return JSONResponse({"success": True, "data": {"instructions": instructions, "media_type": media_type}})


@router.post("/post-ideas-image")
async def post_ideas_image(payload: dict = Body(...), user=Depends(require_auth)):
    idea_id = str(payload.get("idea_id") or "").strip()
    if not await _idea_exists(idea_id, user.active_workspace_id):
        return JSONResponse({"success": False, "error": "NOT_FOUND", "message": "Idée introuvable."}, status_code=404)
    prompt = payload.get("prompt") or "Visuel professionnel B2B, style illustration_b2b, cohérent avec le post."
    model = str(payload.get("image_model") or media_gen.IMAGE_MODEL_DEFAULT).strip()
    if model not in {media_gen.IMAGE_MODEL_DEFAULT, media_gen.IMAGE_MODEL_GROK}:
        model = media_gen.IMAGE_MODEL_DEFAULT
    aspect_ratio = str(payload.get("aspect_ratio") or "4:5").strip()
    quality = "haute" if str(payload.get("quality") or "standard").lower() == "haute" else "standard"
    image_refs = [str(v).strip() for v in (payload.get("image_refs") or []) if str(v).strip()]
    pool = get_pool()

    async with pool.acquire() as conn:
        media_row = await conn.fetchrow(
            """
            INSERT INTO public.post_media (idea_id, workspace_id, media_type, source, status, generation_status, prompt)
            VALUES ($1::uuid,$2::uuid,'image','ai_generated','pending','running',$3)
            RETURNING id::text AS media_id
            """,
            idea_id, user.active_workspace_id, prompt,
        )
    try:
        result = await media_gen.generate_image(
            prompt=prompt, model=model, aspect_ratio=aspect_ratio, quality=quality, image_refs=image_refs,
        )
        image_url = _find_image_source(result)
        if not image_url:
            finish_reason = ""
            try:
                finish_reason = str((result.get("choices") or [{}])[0].get("finish_reason") or "").strip()
            except (AttributeError, IndexError, TypeError):
                finish_reason = ""
            suffix_reason = f" (finish_reason={finish_reason})" if finish_reason else ""
            raise ValueError("Aucune image exploitable n'a été renvoyée par OpenRouter" + suffix_reason + ".")
        image_data, suffix, mime_type = await _image_bytes(image_url)
        file_path, file_name, size_bytes = _write_media(media_row["media_id"], image_data, suffix)
        public_url = _public_url(file_name)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE public.post_media
                SET external_url=$2, public_url=$3, file_path=$4, file_name=$5,
                    mime_type=$6, size_bytes=$7, status='ready', generation_status='done',
                    metadata=COALESCE(metadata,'{}'::jsonb) || $8::jsonb, updated_at=now()
                WHERE id=$1::uuid
                """,
                media_row["media_id"], image_url if image_url.startswith(("http://", "https://")) else None,
                public_url, file_path, file_name, mime_type, size_bytes,
                json.dumps({"image_model": model, "quality": quality, "aspect_ratio": aspect_ratio,
                            "visual_style": payload.get("visual_style") or payload.get("image_style") or "",
                            "user_instructions": str(payload.get("user_instructions") or "").strip(),
                            "edit_source_media_id": str(payload.get("edit_source_media_id") or "").strip() or None,
                            "inspiration_used": bool(image_refs)}),
            )
        return JSONResponse({"success": True, "data": {"media_id": media_row["media_id"], "url": public_url,
                                                         "media_type": "image", "status": "ready"}})
    except Exception as exc:  # noqa: BLE001
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE public.post_media SET status='error', generation_status='error', error_message=$2 WHERE id=$1::uuid",
                media_row["media_id"], str(exc),
            )
        return JSONResponse({"success": False, "error": "MEDIA_GENERATION_FAILED", "message": str(exc)}, status_code=502)


@router.post("/post-ideas-video")
async def post_ideas_video(payload: dict = Body(...), user=Depends(require_auth)):
    """
    Lance la création vidéo (asynchrone côté fournisseur). Répond 202
    immédiatement ; le polling doit être délégué à un worker dédié
    (recommandation Addendum §8) qui appelle ensuite
    media_generation.poll_video_status() puis download_video().
    """
    idea_id = str(payload.get("idea_id") or "").strip()
    if not await _idea_exists(idea_id, user.active_workspace_id):
        return JSONResponse({"success": False, "error": "NOT_FOUND", "message": "Idée introuvable."}, status_code=404)
    prompt = str(payload.get("prompt") or payload.get("scenario") or "").strip()
    if not prompt:
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR",
                              "message": "Le post ne contient pas assez de contenu pour préparer la vidéo."}, status_code=422)
    try:
        duration = int(payload.get("duration", 6) or 6)
    except (TypeError, ValueError):
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR",
                             "message": "Durée vidéo invalide."}, status_code=422)
    duration = max(1, min(60, duration))

    pool = get_pool()
    async with pool.acquire() as conn:
        media_row = await conn.fetchrow(
            """
            INSERT INTO public.post_media (idea_id, workspace_id, media_type, source, status, generation_status, prompt)
            VALUES ($1::uuid,$2::uuid,'video','ai_generated','pending','queued',$3)
            RETURNING id::text AS media_id
            """,
            idea_id, user.active_workspace_id, prompt,
        )

    try:
        result = await media_gen.create_video(
            prompt=prompt,
            aspect_ratio=str(payload.get("aspect_ratio") or "9:16"),
            duration=duration,
            quality="haute" if str(payload.get("quality") or "standard").lower() == "haute" else "standard",
            model=media_gen.VIDEO_MODEL_DEFAULT,
            generate_audio=bool(payload.get("generate_audio", False)),
            frame_image_url=payload.get("first_frame_url"),
        )
        if not isinstance(result, dict):
            raise ValueError("Réponse OpenRouter vidéo invalide.")
        reference = media_gen.video_job_reference(result)
        polling_url = reference["polling_url"]
        job_id = reference["job_id"]
        if not polling_url:
            error = result.get("error")
            if isinstance(error, dict):
                error = error.get("message") or error.get("code")
            raise ValueError(str(error or "OpenRouter n'a retourné ni polling_url ni identifiant de job vidéo."))
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE public.post_media SET metadata=$2, scenario_text=$3, updated_at=now() WHERE id=$1::uuid",
                media_row["media_id"], json.dumps({
                    "polling_url": polling_url, "job_id": job_id or None, "openrouter_job_id": job_id or None,
                    "raw_create_response": result,
                    "video_model": media_gen.VIDEO_MODEL_DEFAULT,
                    "quality": "haute" if str(payload.get("quality") or "standard").lower() == "haute" else "standard",
                    "aspect_ratio": str(payload.get("aspect_ratio") or "9:16"),
                    "duration": duration,
                    "visual_style": str(payload.get("visual_style") or payload.get("video_style") or "").strip(),
                    "user_instructions": str(payload.get("scenario") or payload.get("user_instructions") or "").strip(),
                    "first_frame_url": str(payload.get("first_frame_url") or "").strip() or None,
                    "edit_source_media_id": str(payload.get("edit_source_media_id") or "").strip() or None,
                }), str(payload.get("scenario") or "").strip() or None,
            )
        return JSONResponse(
            {"success": True, "data": {"media_id": media_row["media_id"], "status": "queued", "polling_url": polling_url, "job_id": job_id or None}},
            status_code=202,
        )
    except Exception as exc:  # noqa: BLE001
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE public.post_media SET status='error', generation_status='error', error_message=$2 WHERE id=$1::uuid",
                media_row["media_id"], str(exc),
            )
        return JSONResponse({"success": False, "error": "MEDIA_GENERATION_FAILED", "message": str(exc)}, status_code=502)


@router.get("/post-ideas-video/status")
async def get_video_status(media_id: str, user=Depends(require_auth)):
    """Interroge le statut d'un rendu vidéo en cours (polling)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        media = await conn.fetchrow(
            "SELECT metadata,status,generation_status,public_url,external_url FROM public.post_media "
            "WHERE id=$1::uuid AND workspace_id=$2::uuid",
            media_id, user.active_workspace_id,
        )
    if not media:
        return JSONResponse({"success": False, "error": "NOT_FOUND"}, status_code=404)
    if str(media["status"] or "").lower() == "ready" and str(media["public_url"] or "").strip():
        return JSONResponse({"success": True, "data": {
            "media_id": media_id, "status": "done", "url": str(media["public_url"]),
        }})
    metadata = json.loads(media["metadata"]) if isinstance(media["metadata"], str) else (media["metadata"] or {})
    if not isinstance(metadata, dict):
        metadata = {}
    polling_url = media_gen.normalize_video_polling_url(metadata.get("polling_url", ""))
    if not polling_url:
        ref = media_gen.video_job_reference(metadata.get("raw_create_response") if isinstance(metadata.get("raw_create_response"), dict) else {})
        polling_url = ref["polling_url"]
    if not polling_url:
        return JSONResponse({"success": False, "error": "NO_POLLING_URL"}, status_code=422)

    try:
        status_result = await media_gen.poll_video_status(polling_url)
        if not isinstance(status_result, dict):
            raise ValueError("Réponse de statut vidéo invalide.")
        fallback_job_id = str(
            metadata.get("job_id") or metadata.get("openrouter_job_id")
            or ((metadata.get("raw_create_response") or {}).get("id") if isinstance(metadata.get("raw_create_response"), dict) else "")
            or ""
        ).strip()
        info = media_gen.video_status_info(status_result, fallback_job_id=fallback_job_id)
        download_url = info["download_url"]

        if download_url:
            persisted = await persist_video_download(media_id, download_url)
            persisted["job_id"] = info["job_id"] or fallback_job_id or None
            return JSONResponse({"success": True, "data": persisted})

        error = info["error"]
        status = info["status"]
        if error or status in {"failed", "error", "cancelled", "canceled", "rejected"}:
            message = error.get("message") if isinstance(error, dict) else str(error or status)
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE public.post_media SET status='error', generation_status='error', "
                    "error_message=$2, updated_at=now() WHERE id=$1::uuid AND workspace_id=$3::uuid",
                    media_id, message[:1800], user.active_workspace_id,
                )
            return JSONResponse({"success": False, "error": "VIDEO_GENERATION_FAILED",
                                 "message": message}, status_code=422)

        return JSONResponse({"success": True, "data": {"status": status or "running"}})
    except httpx.HTTPError as exc:
        return JSONResponse({"success": False, "error": "VIDEO_STATUS_FAILED",
                             "message": f"Statut vidéo indisponible : {exc}"}, status_code=502)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"success": False, "error": "VIDEO_STATUS_FAILED",
                             "message": str(exc) or "Lecture du statut vidéo impossible."}, status_code=502)


@router.post("/post-ideas-media-import")
async def post_ideas_media_import(payload: dict = Body(...), user=Depends(require_auth)):
    idea_id = str(payload.get("idea_id") or "").strip()
    if not await _idea_exists(idea_id, user.active_workspace_id):
        return JSONResponse({"success": False, "error": "NOT_FOUND", "message": "Idée introuvable."}, status_code=404)
    image_url = str(payload.get("image_url") or "").strip()
    if not image_url:
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR",
                             "message": "URL ou image à importer manquante."}, status_code=422)
    if not image_url.startswith(("https://", "http://", "data:image/")):
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR",
                             "message": "Le média importé doit être une URL HTTP(S) ou une image data/base64."}, status_code=422)
    pool = get_pool()
    async with pool.acquire() as conn:
        media_row = await conn.fetchrow(
            """
            INSERT INTO public.post_media (idea_id, workspace_id, media_type, source, status, generation_status, external_url)
            VALUES ($1::uuid,$2::uuid,'image','imported','pending','running',$3)
            RETURNING id::text AS media_id
            """,
            idea_id, user.active_workspace_id, image_url,
        )
    try:
        image_data, suffix, mime_type = await _image_bytes(image_url)
        file_path, file_name, size_bytes = _write_media(media_row["media_id"], image_data, suffix)
        public_url = _public_url(file_name)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE public.post_media
                SET public_url=$2, file_path=$3, file_name=$4, mime_type=$5, size_bytes=$6,
                    status='ready', generation_status='done', updated_at=now()
                WHERE id=$1::uuid
                """,
                media_row["media_id"], public_url, file_path, file_name, mime_type, size_bytes,
            )
        return JSONResponse({"success": True, "data": {"media_id": media_row["media_id"], "url": public_url}})
    except Exception as exc:  # noqa: BLE001
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE public.post_media SET status='error', generation_status='error', error_message=$2, updated_at=now() WHERE id=$1::uuid",
                media_row["media_id"], str(exc),
            )
        return JSONResponse({"success": False, "error": "MEDIA_IMPORT_FAILED", "message": str(exc)}, status_code=422)


@router.post("/media-select")
async def post_media_select(payload: dict = Body(...), user=Depends(require_auth)):
    media_id = str(payload.get("media_id") or "").strip()
    idea_id = str(payload.get("idea_id") or "").strip()
    if not media_id or not idea_id:
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR",
                             "message": "Média ou idée manquant."}, status_code=422)
    pool = get_pool()
    async with pool.acquire() as conn:
      async with conn.transaction():
        selected = await conn.fetchrow(
            """
            SELECT id::text FROM public.post_media
            WHERE id=$1::uuid AND idea_id=$2::uuid AND workspace_id=$3::uuid
              AND status='ready'
            FOR UPDATE
            """,
            media_id, idea_id, user.active_workspace_id,
        )
        if selected is None:
            return JSONResponse({"success": False, "error": "NOT_FOUND",
                                 "message": "Média prêt introuvable pour cette idée."}, status_code=404)
        await conn.execute(
            """
            UPDATE public.post_media
            SET media_role=NULL, updated_at=now()
            WHERE idea_id=$1::uuid AND workspace_id=$2::uuid AND media_role='cover'
            """,
            idea_id, user.active_workspace_id,
        )
        await conn.execute(
            "UPDATE public.post_media SET media_role='cover', updated_at=now() "
            "WHERE id=$1::uuid AND workspace_id=$2::uuid",
            media_id, user.active_workspace_id,
        )
    return JSONResponse({"success": True, "data": {"media_id": media_id, "idea_id": idea_id}})


@router.post("/media-delete")
async def post_media_delete(payload: dict = Body(...), user=Depends(require_auth)):
    media_id = str(payload.get("media_id") or "").strip()
    if not media_id:
        return JSONResponse({"success": False, "error": "VALIDATION_ERROR", "message": "Média manquant."}, status_code=422)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM public.post_media WHERE id=$1::uuid AND workspace_id=$2::uuid RETURNING file_path",
            media_id, user.active_workspace_id,
        )
    if row is None:
        return JSONResponse({"success": False, "error": "NOT_FOUND", "message": "Média introuvable."}, status_code=404)
    file_path = str(row["file_path"] or "").strip()
    if file_path:
        try:
            from pathlib import Path
            path = Path(file_path)
            if path.is_file():
                path.unlink()
        except OSError:
            pass
    return JSONResponse({"success": True, "message": "Média supprimé."})


@router.get("/posts/idea-media-json")
async def get_idea_media_json(idea_id: str, user=Depends(require_auth)):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id::text, media_type, status, generation_status, public_url, external_url, media_role, "
            "COALESCE(public_url, external_url) AS url, file_name, mime_type, prompt, scenario_text, metadata "
            "FROM public.post_media WHERE idea_id=$1::uuid AND workspace_id=$2::uuid "
            "AND status='ready' AND COALESCE(public_url, external_url,'')<>'' ORDER BY created_at",
            idea_id, user.active_workspace_id,
        )
    return JSONResponse({"success": True, "data": [dict(r) for r in rows], "count": len(rows)})
