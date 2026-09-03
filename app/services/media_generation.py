"""
Génération d'images et de vidéos IA — port EXACT des payloads OpenRouter
découverts dans les nœuds originaux (corrige/complète le squelette
générique précédent) :

- Image : "OpenRouter - Générer visuel"
    - Modèle 'x-ai/grok-imagine-image-quality' -> POST /v1/images
      payload: {model, prompt, n:1, resolution:'1K'|'2K', aspect_ratio, input_references?}
    - Tout autre modèle (défaut 'openai/gpt-5-image-mini') -> POST /v1/chat/completions
      payload: {model, messages:[{role:'user', content:[...]}], modalities:['image','text'],
                image_config:{aspect_ratio, quality}, stream:false}

- Vidéo : "Préparer payload vidéo robuste" + "OpenRouter - Créer vidéo"
    - Modèle 'x-ai/grok-imagine-video' -> POST /v1/videos
      payload: {model, prompt, aspect_ratio, duration, resolution:'480p'|'720p',
                temperature:0.4, generate_audio?, frame_images?}
    - Réponse asynchrone : contient `polling_url` (à interroger périodiquement)
      puis `video_content_download_url` une fois prêt (voir §3 pour le polling).

Toutes les limites de prompt (GROK_PROMPT_MAX=6200 pour l'image,
GROK_VIDEO_PROMPT_MAX=3600 pour la vidéo) et la température fixe (0.4 pour
la vidéo) sont reprises telles quelles depuis le code source.
"""
from __future__ import annotations

import asyncio
import re

import httpx

from app.config import get_settings

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

IMAGE_MODEL_DEFAULT = "openai/gpt-5-image-mini"
IMAGE_MODEL_GROK = "x-ai/grok-imagine-image-quality"
VIDEO_MODEL_DEFAULT = "x-ai/grok-imagine-video"

GROK_IMAGE_PROMPT_MAX = 6200
GROK_VIDEO_PROMPT_MAX = 3600
GROK_VIDEO_TEMPERATURE = 0.4

ALLOWED_ASPECT_RATIOS = {
    "auto", "1:1", "4:5", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3",
    "2:1", "1:2", "19.5:9", "9:19.5", "20:9", "9:20",
}
ASPECT_ALIASES = {"5:4": "4:3"}


def _headers() -> dict:
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Title": "n8n-post-ideas-media",
    }


def _normalize_aspect(value: str) -> str:
    v = ASPECT_ALIASES.get(value, value)
    return v if v in ALLOWED_ASPECT_RATIOS else "auto"


# ---------------------------------------------------------------------------
# Image
# ---------------------------------------------------------------------------

async def generate_image(
    *, prompt: str, model: str = IMAGE_MODEL_DEFAULT, aspect_ratio: str = "4:5",
    quality: str = "standard", image_refs: list[str] | None = None,
) -> dict:
    is_grok = model == IMAGE_MODEL_GROK
    image_refs = image_refs or []

    if is_grok:
        payload = {
            "model": model,
            "prompt": prompt[:GROK_IMAGE_PROMPT_MAX],
            "n": 1,
            "resolution": "2K" if quality == "haute" else "1K",
            "aspect_ratio": _normalize_aspect(aspect_ratio),
        }
        if image_refs:
            payload["input_references"] = [
                {"type": "image_url", "image_url": {"url": url}} for url in image_refs[:3]
            ]
        endpoint = "/images"
    else:
        content = prompt
        if image_refs:
            content = [{"type": "text", "text": prompt}] + [
                {"type": "image_url", "image_url": {"url": url}} for url in image_refs
            ]
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "modalities": ["image", "text"],
            "image_config": {
                "aspect_ratio": aspect_ratio,
                "quality": "high" if quality == "haute" else "medium",
            },
            "stream": False,
        }
        endpoint = "/chat/completions"

    # Parité n8n : le nœud OpenRouter image avait retryOnFail=true,
    # maxTries=2 et waitBetweenTries=2500 ms. Ne pas transformer une
    # erreur transport temporaire en faux média disponible.
    last_error: Exception | None = None
    async with httpx.AsyncClient(base_url=OPENROUTER_BASE, timeout=180) as client:
        for attempt in range(2):
            try:
                resp = await client.post(endpoint, headers=_headers(), json=payload)
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict):
                    raise ValueError("Réponse OpenRouter image invalide.")
                return data
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt == 0:
                    await asyncio.sleep(2.5)
                    continue
                raise
    raise RuntimeError(str(last_error or "Génération image impossible."))



async def generate_media_instructions(
    *, media_type: str, context: str, aspect_ratio: str, styles: list[str] | None = None,
    current_instructions: str = "", duration: int = 6,
) -> str:
    """Aide IA du modal V90 : génère uniquement l'instruction média, jamais le média lui-même."""
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY manquante")
    kind = "vidéo" if str(media_type).lower() == "video" else "image"
    limit = 3300 if kind == "vidéo" else 1100
    style_text = ", ".join(str(v).strip() for v in (styles or []) if str(v).strip())
    if kind == "vidéo":
        system = (
            "Tu es un directeur créatif B2B. Rédige uniquement des instructions de génération vidéo en français, "
            "sans markdown ni préambule. Le scénario doit être concret, visuel, cohérent et directement exploitable "
            "par Grok Imagine Video. N'invente aucun chiffre ni preuve. Garde le sujet visible entièrement dans le cadre."
        )
        user = f"""Post et contexte :\n{context[:6000]}\n\nFormat : {aspect_ratio}. Durée : {duration} secondes. Style(s) : {style_text or 'à proposer'}.\nInstructions existantes à améliorer si présentes : {current_instructions[:2500]}\n\nProduis une instruction/scénario de moins de {limit} caractères. Les 0 à 2 premières secondes doivent avoir un hook visuel clair, puis montrer le problème, la solution en action et le résultat."""
    else:
        system = (
            "Tu es un directeur artistique B2B. Rédige uniquement une instruction de génération d'image en français, "
            "sans markdown ni préambule. Elle doit être concrète, cohérente, directement exploitable par un modèle image, "
            "sans inventer de chiffres ni de preuves et sans texte visible inutile."
        )
        user = f"""Post et contexte :\n{context[:6000]}\n\nFormat : {aspect_ratio}. Style(s) : {style_text or 'à proposer'}.\nInstructions existantes à améliorer si présentes : {current_instructions[:900]}\n\nProduis une instruction de moins de {limit} caractères. Prévoir une composition professionnelle, le sujet entièrement visible et des marges de sécurité."""
    payload = {
        "model": str(settings.openrouter_model or "openai/gpt-4.1-mini"),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.35,
        "max_tokens": 1100 if kind == "vidéo" else 500,
    }
    async with httpx.AsyncClient(base_url=OPENROUTER_BASE, timeout=120) as client:
        resp = await client.post("/chat/completions", headers=_headers(), json=payload)
        resp.raise_for_status()
        data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(str(v.get("text") or "") if isinstance(v, dict) else str(v) for v in content)
        text = str(content or "").strip().strip("`")
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Réponse IA d'aide média invalide.") from exc
    if not text:
        raise ValueError("L'IA n'a retourné aucune instruction média.")
    return text[:limit].strip()

# ---------------------------------------------------------------------------
# Vidéo (asynchrone : create -> poll -> download)
# ---------------------------------------------------------------------------



def _nested_dicts(value):
    """Parcourt les enveloppes JSON courantes renvoyées par OpenRouter."""
    if isinstance(value, dict):
        yield value
        for key in ("data", "result", "output", "video", "job"):
            child = value.get(key)
            if isinstance(child, dict):
                yield from _nested_dicts(child)


def normalize_video_polling_url(value: str) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    if url.startswith("/"):
        return "https://openrouter.ai" + url
    return url


def video_job_reference(payload: dict | None) -> dict:
    """Extrait id + polling_url comme le workflow V90.

    OpenRouter peut retourner uniquement ``id``. Dans ce cas le V90 construit
    ``/api/v1/videos/{id}`` et poursuit le polling au lieu de considérer la
    création comme invalide.
    """
    payload = payload if isinstance(payload, dict) else {}
    job_id = ""
    polling_url = ""
    for obj in _nested_dicts(payload):
        if not job_id:
            job_id = str(
                obj.get("job_id") or obj.get("id") or obj.get("jobId")
                or obj.get("generation_id") or ""
            ).strip()
        if not polling_url:
            polling_url = str(obj.get("polling_url") or obj.get("status_url") or "").strip()
    polling_url = normalize_video_polling_url(polling_url)
    if not job_id and polling_url:
        match = re.search(r"/videos/([^/?#]+)", polling_url)
        if match:
            job_id = match.group(1)
    if not polling_url and job_id:
        polling_url = f"https://openrouter.ai/api/v1/videos/{job_id}"
    return {"job_id": job_id, "polling_url": polling_url}


def video_content_url(job_id: str, index: int = 0) -> str:
    job_id = str(job_id or "").strip()
    if not job_id:
        return ""
    return f"https://openrouter.ai/api/v1/videos/{job_id}/content?index={int(index)}"


def video_status_info(payload: dict | None, *, fallback_job_id: str = "") -> dict:
    """Normalise le statut OpenRouter, y compris le cas ``completed`` sans URL.

    Le V90 télécharge alors explicitement ``/videos/{id}/content?index=0``.
    """
    payload = payload if isinstance(payload, dict) else {}
    reference = video_job_reference(payload)
    job_id = reference["job_id"] or str(fallback_job_id or "").strip()
    status = ""
    download_url = ""
    error = None
    for obj in _nested_dicts(payload):
        if not status:
            status = str(obj.get("status") or obj.get("state") or "").strip().lower()
        if not download_url:
            download_url = str(
                obj.get("video_content_download_url") or obj.get("download_url")
                or obj.get("content_url") or obj.get("video_url") or ""
            ).strip()
        if error is None and obj.get("error"):
            error = obj.get("error")
    completed = status in {"completed", "complete", "succeeded", "success", "done", "ready"}
    if completed and not download_url and job_id:
        download_url = video_content_url(job_id)
    return {
        "status": status or "running",
        "job_id": job_id,
        "polling_url": reference["polling_url"],
        "download_url": download_url,
        "completed": completed,
        "error": error,
    }

ALLOWED_VIDEO_DURATIONS = [4, 6, 8, 10, 12, 15]


def _closest_duration(value: int) -> int:
    return min(ALLOWED_VIDEO_DURATIONS, key=lambda d: abs(d - value))


async def create_video(
    *, prompt: str, aspect_ratio: str = "9:16", duration: int = 6,
    quality: str = "standard", model: str = VIDEO_MODEL_DEFAULT,
    generate_audio: bool = False, frame_image_url: str | None = None,
) -> dict:
    resolution = "720p" if quality == "haute" else "480p"
    payload = {
        "model": model,
        "prompt": prompt[:GROK_VIDEO_PROMPT_MAX],
        "aspect_ratio": aspect_ratio,
        "duration": _closest_duration(duration),
        "resolution": resolution,
        "temperature": GROK_VIDEO_TEMPERATURE,
    }
    if generate_audio:
        payload["generate_audio"] = True
    if frame_image_url and frame_image_url.startswith(("https://", "data:image/")):
        payload["frame_images"] = [{
            "type": "image_url", "image_url": {"url": frame_image_url}, "frame_type": "first_frame",
        }]

    async with httpx.AsyncClient(base_url=OPENROUTER_BASE, timeout=120) as client:
        resp = await client.post("/videos", headers=_headers(), json=payload)
        resp.raise_for_status()
        return resp.json()  # contient normalement `polling_url`


async def poll_video_status(polling_url: str) -> dict:
    polling_url = normalize_video_polling_url(polling_url)
    if not polling_url:
        raise ValueError("URL de suivi vidéo OpenRouter manquante.")
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(polling_url, headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def download_video(download_url: str) -> bytes:
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.get(download_url, headers={
            **_headers(), "Accept": "video/mp4, application/octet-stream, */*",
        })
        resp.raise_for_status()
        return resp.content
