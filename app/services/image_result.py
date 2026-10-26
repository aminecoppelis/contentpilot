"""Normalisation/persistance des résultats image OpenRouter, partagée HTTP/worker."""
from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
import re
import httpx
from PIL import Image, ImageOps


import logging
import time

from app.config import get_settings

logger = logging.getLogger("app.image_result")

BADGE_PATH = Path(__file__).resolve().parents[2] / "static" / "branding" / "coppelis-solutions-ia-badge.png"
BADGE_WIDTH_RATIO = 0.22
BADGE_MARGIN_RATIO = 0.025
MAX_BADGE_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_BADGE_DIMENSION = 8192

VALID_POSITIONS = {"bottom-right", "bottom-left", "top-right", "top-left", "center"}


def parse_boolean(value, default: bool = False) -> bool:
    """Interprète les booléens HTML/JSON sans convertir la chaîne 'false' en True."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "on", "yes"}


def calculate_macaron_position(
    canvas_w: int,
    canvas_h: int,
    badge_w: int,
    badge_h: int,
    position: str = "bottom-right",
    margin_ratio: float = BADGE_MARGIN_RATIO,
) -> tuple[int, int]:
    """Calcule les coordonnées (x, y) du macaron selon la position demandée."""
    margin = max(4, round(min(canvas_w, canvas_h) * margin_ratio))
    pos = str(position or "bottom-right").strip().lower().replace("_", "-")

    if pos in ("top-left", "haut-gauche"):
        x = margin
        y = margin
    elif pos in ("top-right", "haut-droite"):
        x = canvas_w - badge_w - margin
        y = margin
    elif pos in ("bottom-left", "bas-gauche"):
        x = margin
        y = canvas_h - badge_h - margin
    elif pos in ("center", "centre", "middle"):
        x = (canvas_w - badge_w) // 2
        y = (canvas_h - badge_h) // 2
    else:  # bottom-right / bas-droite / défaut
        x = canvas_w - badge_w - margin
        y = canvas_h - badge_h - margin

    x = max(0, min(x, max(0, canvas_w - badge_w)))
    y = max(0, min(y, max(0, canvas_h - badge_h)))
    return x, y


def _open_image_with_highest_frame(data_or_fp) -> Image.Image:
    """Ouvre une image et sélectionne le frame de résolution maximale (utile pour les fichiers .ico multi-tailles)."""
    img = Image.open(data_or_fp)
    if getattr(img, "n_frames", 1) > 1:
        best_frame = 0
        best_area = 0
        for frame in range(img.n_frames):
            try:
                img.seek(frame)
                area = img.width * img.height
                if area > best_area:
                    best_area = area
                    best_frame = frame
            except Exception:
                break
        try:
            img.seek(best_frame)
        except Exception:
            pass
    return img


def resolve_badge_image(badge_source: bytes | str | Path | None = None) -> Image.Image:
    """Résout et convertit en RGBA le macaron (source personnalisée ou officielle)."""
    if badge_source:
        try:
            if isinstance(badge_source, bytes):
                img = _open_image_with_highest_frame(BytesIO(badge_source))
                return img.convert("RGBA")
            if isinstance(badge_source, Path):
                if badge_source.is_file():
                    with _open_image_with_highest_frame(badge_source) as img:
                        return img.convert("RGBA")
            elif isinstance(badge_source, str):
                text = badge_source.strip()
                if text.startswith("data:image/"):
                    _, encoded = text.split(",", 1)
                    raw_bytes = base64.b64decode(encoded)
                    img = _open_image_with_highest_frame(BytesIO(raw_bytes))
                    return img.convert("RGBA")

                # Enlève l'éventuel query string (ex: ?v=123)
                clean_path = text.split("?", 1)[0]
                if clean_path.startswith("/public-media/"):
                    rel = clean_path.removeprefix("/public-media/").lstrip("/\\")
                    local = get_settings().media_storage_path / rel
                    if local.is_file():
                        with _open_image_with_highest_frame(local) as img:
                            return img.convert("RGBA")
                elif clean_path.startswith("/static/"):
                    rel = clean_path.removeprefix("/static/").lstrip("/\\")
                    local = Path(__file__).resolve().parents[2] / "static" / rel
                    if local.is_file():
                        with _open_image_with_highest_frame(local) as img:
                            return img.convert("RGBA")
                elif Path(clean_path).is_file():
                    with _open_image_with_highest_frame(clean_path) as img:
                        return img.convert("RGBA")
                elif text.startswith(("http://", "https://")):
                    with httpx.Client(timeout=10, follow_redirects=True) as client:
                        resp = client.get(text)
                        resp.raise_for_status()
                        img = _open_image_with_highest_frame(BytesIO(resp.content))
                        return img.convert("RGBA")
        except Exception as exc:
            logger.warning("Échec de chargement du macaron personnalisé (%s), repli sur le macaron officiel : %s", badge_source, exc)

    if not BADGE_PATH.is_file():
        raise FileNotFoundError(f"Macaron de marque introuvable : {BADGE_PATH}")
    with Image.open(BADGE_PATH) as default_source:
        return default_source.convert("RGBA")


def process_and_save_macaron(user_id: str, data: bytes) -> tuple[str, str]:
    """Valide et enregistre un macaron importé (PNG, ICO, WEBP, JPG, BMP...).

    Normalise en PNG RGBA pour préserver la transparence et assurer un affichage
    universel dans tous les navigateurs. Retourne (public_url, file_path).
    """
    if not data:
        raise ValueError("Le fichier de macaron est vide.")
    if len(data) > MAX_BADGE_UPLOAD_BYTES:
        raise ValueError("Le fichier dépasse la taille maximale de 10 Mo.")

    try:
        img = _open_image_with_highest_frame(BytesIO(data))
        if img.width > MAX_BADGE_DIMENSION or img.height > MAX_BADGE_DIMENSION:
            raise ValueError("L'image dépasse la dimension maximale de 8192 px.")
        canvas = ImageOps.exif_transpose(img).convert("RGBA")
    except Exception as exc:
        raise ValueError(f"Fichier image invalide ou non supporté : {exc}") from exc

    output = BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    png_bytes = output.getvalue()

    macaron_dir = get_settings().media_storage_path / "macarons"
    macaron_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"macaron_user_{user_id}.png"
    target_path = macaron_dir / file_name
    target_path.write_bytes(png_bytes)

    timestamp = int(time.time())
    public_url = f"/public-media/macarons/{file_name}?v={timestamp}"
    return public_url, str(target_path)


def apply_brand_badge(
    data: bytes,
    suffix: str = ".png",
    *,
    badge_source: bytes | str | Path | None = None,
    position: str = "bottom-right",
    width_ratio: float = BADGE_WIDTH_RATIO,
    margin_ratio: float = BADGE_MARGIN_RATIO,
) -> tuple[bytes, str, str]:
    """Ajoute le macaron (personnalisé ou officiel) à une image avant sa persistance.

    La position est personnalisable (bottom-right, bottom-left, top-right, top-left, center).
    Le compositing serveur garantit une marque identique quelle que soit la
    réponse du fournisseur d'images. La taille et la marge sont relatives afin
    de fonctionner sur tous les ratios pris en charge.
    """
    with Image.open(BytesIO(data)) as source:
        canvas = ImageOps.exif_transpose(source).convert("RGBA")
    badge = resolve_badge_image(badge_source)

    target_width = max(72, round(canvas.width * width_ratio))
    target_width = min(target_width, max(1, canvas.width - 2))
    target_height = max(1, round(badge.height * target_width / badge.width))
    if target_height >= canvas.height:
        target_height = max(1, canvas.height - 2)
        target_width = max(1, round(badge.width * target_height / badge.height))
    badge = badge.resize((target_width, target_height), Image.Resampling.LANCZOS)

    x, y = calculate_macaron_position(canvas.width, canvas.height, target_width, target_height, position, margin_ratio)
    canvas.alpha_composite(badge, (x, y))

    normalized_suffix = str(suffix or ".png").lower()
    output = BytesIO()
    if normalized_suffix in {".jpg", ".jpeg"}:
        canvas.convert("RGB").save(output, format="JPEG", quality=95, optimize=True)
        return output.getvalue(), ".jpg", "image/jpeg"
    if normalized_suffix == ".webp":
        canvas.save(output, format="WEBP", quality=95, method=6)
        return output.getvalue(), ".webp", "image/webp"
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue(), ".png", "image/png"


def normalize_image_source(value) -> str:
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


def find_image_source(value, seen: set[int] | None = None) -> str:
    direct = normalize_image_source(value)
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
            found = find_image_source(item, seen)
            if found:
                return found
        return ""
    for key in ("url", "image_url", "imageUrl", "image", "b64_json", "base64", "data_url"):
        candidate = value.get(key)
        if isinstance(candidate, dict) and key in {"image_url", "imageUrl", "image"}:
            candidate = candidate.get("url") or candidate.get("data") or candidate
        found = normalize_image_source(candidate)
        if found:
            return found
    for key in ("images", "image", "output", "content", "message", "result", "data", "artifacts", "choices", "generations"):
        if key in value:
            found = find_image_source(value.get(key), seen)
            if found:
                return found
    for candidate in value.values():
        found = find_image_source(candidate, seen)
        if found:
            return found
    return ""


async def image_bytes(source: str) -> tuple[bytes, str, str]:
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
    if mime == "image/webp" or (data.startswith(b"RIFF") and b"WEBP" in data[:16]):
        return data, ".webp", "image/webp"
    return data, ".jpg", "image/jpeg"


async def branded_image_bytes(
    source: str,
    *,
    use_macaron: bool = True,
    badge_source: bytes | str | Path | None = None,
    position: str = "bottom-right",
) -> tuple[bytes, str, str]:
    """Télécharge/décode une image IA puis lui applique le macaron si demandé."""
    data, suffix, mime = await image_bytes(source)
    if not use_macaron:
        return data, suffix, mime
    return apply_brand_badge(data, suffix, badge_source=badge_source, position=position)
