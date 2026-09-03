"""Composition du bloc "Sujet prêt à copier-coller" conforme au rendu n8n V90."""
from __future__ import annotations

import json
import re

def _safe_tags_list(value) -> list[str]:
    """Port du safeTagsList n8n utilisé par la vue de consultation V90."""
    if value is None:
        return []
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            value = parsed
        else:
            value = re.split(r"[\s,;]+", raw)
    if not isinstance(value, (list, tuple)):
        return []

    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, (list, tuple)):
            candidates = item
        else:
            candidates = [item]
        for candidate in candidates:
            clean = str(candidate or "").strip().strip(",;")
            if not clean:
                continue
            if clean.startswith("#"):
                match = re.match(r"^#[A-Za-z0-9_éèêëàâäùûüôöîïçÉÈÊËÀÂÄÙÛÜÔÖÎÏÇ-]+", clean)
                clean = match.group(0) if match else ""
            if not clean:
                continue
            key = clean.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(clean)
    return result


def _normalize_copy_website(value: str | None) -> str:
    website = str(value or "").strip().rstrip("/")
    if not website:
        return ""
    if re.match(r"^https?://", website, flags=re.I):
        return website
    if re.match(r"^[a-z0-9][a-z0-9.-]+\.[a-z]{2,}(?:/.*)?$", website, flags=re.I):
        return "https://" + website
    return ""


def _paragraph_key(value: str) -> str:
    return re.sub(r"[^a-z0-9à-ÿ]+", " ", str(value or "").casefold()).strip()


def _is_hashtag_paragraph(value: str) -> bool:
    words = [word for word in re.split(r"\s+", str(value or "").strip()) if word]
    return bool(words) and all(word.startswith("#") and len(word) > 1 for word in words)


def _strip_website_paragraphs(text: str, website: str) -> str:
    if not website:
        return str(text or "").strip()
    bare = re.sub(r"^https?://", "", website, flags=re.I).rstrip("/")
    variants = {website.rstrip("/").casefold(), bare.casefold()}
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", str(text or "")) if p.strip()]
    kept = []
    for paragraph in paragraphs:
        candidate = paragraph.strip().rstrip("/")
        candidate_bare = re.sub(r"^https?://", "", candidate, flags=re.I).casefold()
        if candidate.casefold() in variants or candidate_bare in variants:
            continue
        kept.append(paragraph)
    return "\n\n".join(kept).strip()


def build_copy_ready_text(
    raw_idea: dict,
    version_text: str | None,
    *,
    version_hashtags=None,
    version_cta: str | None = None,
    website: str | None = None,
    title: str | None = None,
) -> str:
    """Construit le texte réellement prêt à copier comme `fullPostText()` dans n8n V90.

    Le titre, le site du sujet et les hashtags sont reconstruits depuis les champs
    autoritaires afin que les anciennes versions dont `post_text` ne contenait que
    le corps restent complètes à l'affichage.
    """
    idea = raw_idea or {}
    ready = idea.get("ready_post") or {}
    post_title = str(title or ready.get("title") or idea.get("title") or "Post prêt à publier").strip()
    body = str(version_text or ready.get("text") or "").strip()
    if not body:
        body = "\n\n".join(part for part in (idea.get("hook"), idea.get("summary")) if str(part or "").strip()).strip()

    tags = _safe_tags_list(version_hashtags) or _safe_tags_list(ready.get("tags") or idea.get("hashtags"))
    action = str(version_cta or ready.get("simple_action") or idea.get("call_to_action") or "").strip()
    site_link = _normalize_copy_website(website)

    # Le n8n retire du corps le titre et les blocs hashtags existants, puis les
    # remet une seule fois dans la structure finale.
    title_key = _paragraph_key(post_title)
    body_parts = []
    seen = set()
    for paragraph in [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]:
        key = _paragraph_key(paragraph)
        if title_key and key == title_key:
            continue
        if _is_hashtag_paragraph(paragraph):
            continue
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        body_parts.append(paragraph)
    body = "\n\n".join(body_parts).strip()
    body = _strip_website_paragraphs(body, site_link)

    if action:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        action_key = _paragraph_key(action)
        paragraphs = [p for p in paragraphs if _paragraph_key(p) != action_key]
        body = "\n\n".join([*paragraphs, action]).strip()

    parts = [post_title, body]
    if site_link:
        parts.append(site_link)
    if tags:
        parts.append(" ".join(tags))
    return "\n\n".join(part for part in parts if str(part or "").strip()).strip()

