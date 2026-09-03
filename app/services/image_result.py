"""Normalisation/persistance des résultats image OpenRouter, partagée HTTP/worker."""
from __future__ import annotations

import base64
import re
import httpx


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
