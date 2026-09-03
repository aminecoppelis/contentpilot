"""Persistance locale des médias générés/importés.

Le stockage physique est toujours résolu par ``Settings.media_storage_path``
(<projet>/public-media par défaut). Les workers et les routes utilisent ce
module commun pour éviter des divergences de chemins/URL.
"""
from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.database import get_pool
from app.services import media_generation as media_gen


def media_dir() -> Path:
    path = get_settings().media_storage_path
    path.mkdir(parents=True, exist_ok=True)
    return path


def public_url(file_name: str) -> str:
    return f"{get_settings().media_public_base_url.rstrip('/')}/{file_name}"


def write_media(media_id: str, data: bytes, suffix: str) -> tuple[str, str, int]:
    if not data:
        raise ValueError("Le fournisseur a retourné un média vide.")
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    file_name = f"{media_id}{suffix.lower()}"
    final_path = media_dir() / file_name
    temp_path = final_path.with_suffix(final_path.suffix + ".tmp")
    temp_path.write_bytes(data)
    temp_path.replace(final_path)
    return str(final_path), file_name, len(data)


async def persist_video_download(media_id: str, download_url: str) -> dict:
    """Télécharge un rendu vidéo terminé et le rend publiquement accessible."""
    video_bytes = await media_gen.download_video(download_url)
    file_path, file_name, size_bytes = write_media(media_id, video_bytes, ".mp4")
    url = public_url(file_name)
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE public.post_media
            SET external_url=$2, public_url=$3, file_path=$4, file_name=$5,
                mime_type='video/mp4', size_bytes=$6, status='ready',
                generation_status='done', error_message=NULL, updated_at=now()
            WHERE id=$1::uuid
            """,
            media_id, download_url, url, file_path, file_name, size_bytes,
        )
    return {"media_id": media_id, "url": url, "size_bytes": size_bytes, "status": "done"}
