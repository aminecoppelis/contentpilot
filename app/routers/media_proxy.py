"""
Proxys de médias — port des endpoints de service de fichiers du workflow
("GET V0 Média image Instagram JPEG", "...Buffer", "...media-video.mp4",
"...video-content-grok-imagine").

Rôle : exposer les médias sous une URL HTTPS publique consommable par Meta
et Buffer, qui ne savent pas lire un stockage local (cf. Addendum §3.3).
Ces routes sont volontairement NON authentifiées : Meta/Buffer les appellent
depuis leurs propres serveurs, sans cookie de session. La protection repose
sur l'imprévisibilité de l'UUID du média, exactement comme dans l'original
(validation stricte du format UUID avant tout accès disque).

Validations portées à l'identique :
  - `media_id` doit être un UUID valide (regex identique) ;
  - le binaire servi doit avoir une signature de fichier cohérente
    (JPEG : FF D8 FF) sinon une erreur explicite est renvoyée ;
  - un fichier vide est traité comme une erreur distincte.
"""
from __future__ import annotations

import re
from pathlib import Path

import httpx
from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse, StreamingResponse

from app.database import get_pool
from app.config import get_settings

router = APIRouter(tags=["MediaProxy"])

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)

# Répertoire de stockage local des médias : <projet>/public-media/ par défaut.
MEDIA_DIR = get_settings().media_storage_path

JPEG_SIGNATURE = b"\xff\xd8\xff"
MP4_SIGNATURES = (b"ftyp",)  # présent aux offsets 4-8 d'un MP4


def _invalid(message: str, status: int = 404) -> JSONResponse:
    return JSONResponse({"success": False, "error": "MEDIA_PROXY_ERROR", "message": message}, status_code=status)


async def _fetch_media_row(media_id: str):
    pool = get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT id::text, media_type, file_path, public_url, external_url, mime_type "
            "FROM public.post_media WHERE id = $1::uuid",
            media_id,
        )


async def _load_bytes(row, expected_prefix: bytes | None) -> tuple[bytes | None, str]:
    """Lit le média depuis le disque local ou, à défaut, depuis l'URL du fournisseur."""
    data: bytes | None = None

    if row["file_path"]:
        path = Path(row["file_path"])
        if not path.is_absolute():
            path = MEDIA_DIR / path.name
        if path.exists():
            data = path.read_bytes()

    if data is None:
        source = row["public_url"] or row["external_url"]
        if not source:
            return None, "Aucune source disponible pour ce média."
        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                resp = await client.get(source)
                resp.raise_for_status()
                data = resp.content
        except Exception as exc:  # noqa: BLE001
            return None, f"Téléchargement du média impossible : {exc}"

    if not data:
        return None, "Le fichier média est vide."
    if expected_prefix and not data.startswith(expected_prefix):
        return None, "La signature du fichier ne correspond pas au format attendu."
    return data, ""


async def _serve_image(media_id: str, filename_prefix: str) -> Response:
    if not UUID_RE.match(media_id or ""):
        return _invalid("media_id UUID invalide ou manquant.", status=400)
    row = await _fetch_media_row(media_id)
    if row is None:
        return _invalid("Média introuvable.")

    data, error = await _load_bytes(row, JPEG_SIGNATURE if row["mime_type"] == "image/jpeg" else None)
    if data is None:
        return _invalid(error)

    return Response(
        content=data, media_type="image/jpeg",
        headers={
            "Content-Disposition": f'inline; filename="{filename_prefix}-{media_id}.jpg"',
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/posts/media-image.jpg")
async def get_media_image_instagram(media_id: str = ""):
    """Proxy image au format attendu par l'API Graph Instagram."""
    return await _serve_image(media_id, "instagram")


@router.get("/posts/media-image-buffer.jpg")
async def get_media_image_buffer(media_id: str = ""):
    """Proxy image au format attendu par Buffer."""
    return await _serve_image(media_id, "buffer")


@router.get("/posts/media-video.mp4")
async def get_media_video(media_id: str = "", meta_fetch: int = 0, request_id: str = ""):
    """
    Proxy vidéo MP4. Le paramètre `meta_fetch=1` est utilisé quand c'est Meta
    qui vient chercher le fichier (cf. build_instagram_video_proxy_url).
    """
    if not UUID_RE.match(media_id or ""):
        return _invalid("media_id UUID invalide ou manquant.", status=400)
    row = await _fetch_media_row(media_id)
    if row is None:
        return _invalid("Média introuvable.")

    data, error = await _load_bytes(row, None)
    if data is None:
        return _invalid(error)
    if len(data) > 8 and not any(sig in data[:16] for sig in MP4_SIGNATURES):
        return _invalid("La signature du fichier ne correspond pas à un MP4.")

    return Response(
        content=data, media_type="video/mp4",
        headers={
            "Content-Disposition": f'inline; filename="video-{media_id}.mp4"',
            "Accept-Ranges": "bytes",
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/posts/media-inline")
async def get_media_inline(media_id: str = ""):
    """Prévisualisation inline (image ou vidéo) dans l'interface."""
    if not UUID_RE.match(media_id or ""):
        return _invalid("media_id UUID invalide ou manquant.", status=400)
    row = await _fetch_media_row(media_id)
    if row is None:
        return _invalid("Média introuvable.")
    data, error = await _load_bytes(row, None)
    if data is None:
        return _invalid(error)
    mime = row["mime_type"] or ("video/mp4" if row["media_type"] == "video" else "image/jpeg")
    return Response(content=data, media_type=mime, headers={"Cache-Control": "private, max-age=600"})


async def _stream_provider_video(media_id: str) -> Response:
    """
    Proxy du contenu vidéo encore hébergé chez le fournisseur IA
    (routes /posts/video-content-grok-imagine[.mp4] de l'original) :
    le fichier est relayé en streaming, sans transiter par le disque.
    """
    if not UUID_RE.match(media_id or ""):
        return _invalid("media_id UUID invalide ou manquant.", status=400)
    row = await _fetch_media_row(media_id)
    if row is None:
        return _invalid("Média introuvable.")
    source = row["external_url"] or row["public_url"]
    if not source:
        return _invalid("Aucune source distante pour ce média.")

    async def iterator():
        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
            async with client.stream("GET", source) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    yield chunk

    return StreamingResponse(iterator(), media_type="video/mp4", headers={
        "Content-Disposition": f'inline; filename="video-{media_id}.mp4"',
        "Cache-Control": "no-store",
    })


@router.get("/posts/video-content-grok-imagine")
async def get_video_content_provider(media_id: str = ""):
    return await _stream_provider_video(media_id)


@router.get("/posts/video-content-grok-imagine.mp4")
async def get_video_content_provider_mp4(media_id: str = ""):
    return await _stream_provider_video(media_id)
