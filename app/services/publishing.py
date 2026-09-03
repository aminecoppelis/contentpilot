"""Publication sociale partagée par la route HTTP et le worker planifié."""
from __future__ import annotations

import asyncio
import json
import re
import unicodedata

from app.services import buffer as buffer_client
from app.services import meta as meta_client
from app.services.crypto import decrypt_token


CTA_VERB_RE = re.compile(
    r"^(commentez|commenter|envoyez|ecrivez|contactez|demandez|telechargez|repondez|"
    r"cliquez|inscrivez|decouvrez|reserve[zr]?|planifiez|testez|essayez|partagez|appelez)\b"
)


def _normalize_cta_text(value: str) -> str:
    value = unicodedata.normalize("NFD", (value or "").lower())
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    value = re.sub(r'''[«»"'`]''', "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return re.sub(r"[.!?。]+$", "", value)


def _is_cta_paragraph(paragraph: str, action: str) -> bool:
    p, a = _normalize_cta_text(paragraph), _normalize_cta_text(action)
    if not p:
        return False
    if a and (p == a or a in p or p in a):
        return True
    return bool(CTA_VERB_RE.match(p))


def ensure_cta_separated(text: str, action: str) -> str:
    text, action = (text or "").strip(), (action or "").strip()
    if not action:
        return text
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    while paragraphs and _is_cta_paragraph(paragraphs[-1], action):
        paragraphs.pop()
    body = "\n\n".join(paragraphs).strip()
    return "\n\n".join(p for p in (body, action) if p).strip()


def _is_hashtag_paragraph(value: str) -> bool:
    tokens = [t for t in re.split(r"\s+", str(value or "").strip()) if t]
    return bool(tokens) and all(t.startswith("#") and len(t) > 1 for t in tokens)


def _is_url_only_paragraph(value: str) -> bool:
    return bool(re.fullmatch(r"https?://\S+", str(value or "").strip(), flags=re.I))


def final_post_text(raw_idea: dict, *, version_text: str, cta: str, hashtags) -> str:
    """Retourne le texte social final sans doubler CTA/hashtags.

    La vue V90 enregistre le bloc prêt à copier complet (titre, CTA, site, tags).
    Cette normalisation conserve donc le site avant les hashtags et garantit un
    seul bloc de hashtags au moment de l'envoi réseau.
    """
    idea = dict(raw_idea or {})
    ready = dict(idea.get("ready_post") or {})
    ready["text"] = version_text or ready.get("text") or ""
    ready["simple_action"] = cta or ready.get("simple_action") or idea.get("call_to_action", "")
    idea["ready_post"] = ready
    action = str(ready.get("simple_action") or idea.get("call_to_action", "") or "").strip()
    text = str(ready.get("text") or "\n\n".join(filter(None, [idea.get("hook", ""), idea.get("summary", "")]))).strip()

    tags = hashtags
    if isinstance(tags, str):
        try:
            parsed = json.loads(tags)
            tags = parsed if isinstance(parsed, list) else [tags]
        except json.JSONDecodeError:
            tags = re.split(r"[\s,;]+", tags)
    if not tags:
        tags = ready.get("tags") or idea.get("hashtags") or []
    canonical_tags = []
    seen_tags = set()
    for tag in (tags or []):
        clean = str(tag or "").strip()
        if not clean or clean.casefold() in seen_tags:
            continue
        seen_tags.add(clean.casefold())
        canonical_tags.append(clean)

    # Supprime tout ancien bloc final de hashtags : le bloc canonique sera ajouté
    # une seule fois à la fin. Le lien HTTPS reste donc juste avant les tags.
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    paragraphs = [p for p in paragraphs if not _is_hashtag_paragraph(p)]

    if action and not any(_is_cta_paragraph(p, action) for p in paragraphs):
        insert_at = len(paragraphs)
        if paragraphs and _is_url_only_paragraph(paragraphs[-1]):
            insert_at -= 1
        paragraphs.insert(insert_at, action)

    if canonical_tags:
        paragraphs.append(" ".join(canonical_tags))
    return "\n\n".join(paragraphs).strip()


def media_kind(media_row) -> str:
    if not media_row:
        return "none"
    value = str(media_row["media_type"] or "").lower()
    return value if value in ("image", "video") else "none"


def _metadata(account) -> dict:
    try:
        value = account["metadata"] if account is not None else {}
    except (KeyError, TypeError):
        value = {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


async def publish_facebook(account, media_type: str, media_url: str | None, text: str) -> dict:
    access_token = decrypt_token(account["token_ciphertext"])
    page_id = account["external_account_id"]
    if media_type == "image":
        if not media_url:
            return {"error": "Une URL HTTPS publique est nécessaire pour publier une image Facebook via Meta."}
        resp = await meta_client.publish_facebook_photo(page_id, access_token, media_url, text)
    elif media_type == "video":
        if not media_url:
            return {"error": "Une URL HTTPS publique est nécessaire pour publier une vidéo Facebook via Meta."}
        resp = await meta_client.publish_facebook_video(page_id, access_token, media_url, text)
    else:
        resp = await meta_client.publish_facebook_text(page_id, access_token, text)
    return {"status_code": resp.status_code, "body": resp.json()}


async def publish_instagram(account, media_type: str, media_url: str | None, text: str,
                            publish_content_type: str = "standard") -> dict:
    if media_type not in ("image", "video") or not media_url:
        return {"error": "Instagram exige un média image ou vidéo accessible publiquement en HTTPS."}
    access_token = decrypt_token(account["token_ciphertext"])
    ig_user_id = account["external_account_id"]
    metadata = _metadata(account)
    instagram_direct = bool(metadata.get("instagram_direct")) or str(metadata.get("connection_provider") or "") == "meta_direct"
    content_type = str(publish_content_type or "standard").strip().lower()
    is_story = "story" in content_type
    is_reel = "reel" in content_type or (media_type == "video" and not is_story)
    create_resp = await meta_client.create_instagram_container(
        ig_user_id, access_token,
        image_url=media_url if media_type == "image" else None,
        video_url=media_url if media_type == "video" else None,
        caption=text, instagram_direct=instagram_direct,
        media_type="STORIES" if is_story else ("REELS" if is_reel else None),
        share_to_feed=True if is_reel else None,
    )
    container = create_resp.json()
    if create_resp.status_code >= 400:
        error = container.get("error") if isinstance(container, dict) else None
        message = error.get("message") if isinstance(error, dict) else str(error or "Création du container Instagram impossible.")
        return {"error": message, "status_code": create_resp.status_code, "body": container}
    container_id = str(container.get("id") or "")
    if not container_id:
        return {"error": "Échec de création du container Instagram.", "raw": container}

    # Parité n8n V90 : le workflow laisse Meta ingérer le média AVANT
    # chaque lecture de statut. L'intervalle de base est de 5 s pour une
    # image et 50 s pour une vidéo, puis les trois attentes valent 1x, 2x
    # et 3x cet intervalle (30 s cumulées pour une image, 5 min pour une vidéo).
    poll_interval = 5 if media_type == "image" else 50
    poll_delays = (poll_interval, poll_interval * 2, poll_interval * 3)
    finished = False
    last_status: dict = {}
    for delay in poll_delays:
        await asyncio.sleep(delay)
        status_resp = await meta_client.get_instagram_container_status(
            container_id, access_token, instagram_direct=instagram_direct)
        status_data = status_resp.json()
        last_status = status_data if isinstance(status_data, dict) else {}
        status_code = str(last_status.get("status_code") or last_status.get("status") or "").strip().upper()
        meta_error = last_status.get("error") if isinstance(last_status.get("error"), dict) else None
        if status_code == "FINISHED":
            finished = True
            break
        if status_code in ("ERROR", "EXPIRED") or meta_error:
            detail = (meta_error or {}).get("message") or last_status.get("error_message") or (
                f"Container Instagram {status_code or 'en erreur'}"
            )
            return {
                "error": f"Traitement du container Instagram : {detail}",
                "body": last_status,
            }

    if not finished:
        final_status = str(last_status.get("status_code") or last_status.get("status") or "inconnu").strip() or "inconnu"
        return {
            "error": (
                "Le container Instagram n’est pas prêt après les vérifications successives "
                f"(statut : {final_status}). Relance la publication ; le média reste disponible."
            ),
            "body": last_status,
        }

    publish_resp = await meta_client.publish_instagram_container(
        ig_user_id, access_token, container_id, instagram_direct=instagram_direct)
    body = publish_resp.json()
    if publish_resp.status_code >= 400:
        error = body.get("error") if isinstance(body, dict) else None
        message = error.get("message") if isinstance(error, dict) else str(error or "Publication Instagram impossible.")
        return {"error": message, "status_code": publish_resp.status_code, "body": body}
    return {"status_code": publish_resp.status_code, "body": body}


async def publish_buffer(account, platform: str, media_type: str, media_url: str | None, text: str,
                         publish_content_type: str = "standard", *, is_scheduled: bool = False,
                         scheduled_at: str | None = None) -> dict:
    api_key = decrypt_token(account["token_ciphertext"])
    channel_id = account["external_account_id"]
    resp = await buffer_client.create_post(
        api_key, text=text, channel_id=channel_id, platform=platform,
        media_url=media_url, media_kind=media_type,
        publish_content_type=publish_content_type,
        is_scheduled=is_scheduled, scheduled_at=scheduled_at,
    )
    body = resp.json()
    if resp.status_code >= 400:
        return {"error": f"Buffer HTTP {resp.status_code}", "status_code": resp.status_code, "body": body}
    if isinstance(body, dict) and body.get("errors"):
        first = body["errors"][0] if body["errors"] else {}
        return {"error": first.get("message") or "Buffer a refusé la publication.", "body": body}
    # GraphQL peut retourner une MutationError dans data.createPost sans HTTP 4xx.
    create_post = ((body.get("data") or {}).get("createPost") or {}) if isinstance(body, dict) else {}
    if isinstance(create_post, dict) and create_post.get("message") and not create_post.get("post"):
        return {"error": str(create_post.get("message")), "body": body}
    return {"status_code": resp.status_code, "body": body}


async def publish_to_account(account, *, platform: str, media_type: str, media_url: str | None,
                             text: str, publish_content_type: str = "standard",
                             buffer_schedule: bool = False, scheduled_at: str | None = None) -> dict:
    provider = str(account["provider"] or "").lower()
    if provider == "facebook":
        return await publish_facebook(account, media_type, media_url, text)
    if provider == "instagram":
        return await publish_instagram(account, media_type, media_url, text, publish_content_type)
    if provider == "buffer":
        return await publish_buffer(
            account, platform, media_type, media_url, text, publish_content_type,
            is_scheduled=buffer_schedule, scheduled_at=scheduled_at,
        )
    return {"error": f"Fournisseur de connexion non pris en charge : {provider or 'inconnu'}."}


def outcome_error(outcome: dict) -> str | None:
    error = outcome.get("error") if isinstance(outcome, dict) else None
    if error:
        return str(error)
    body = outcome.get("body") if isinstance(outcome, dict) else None
    if isinstance(body, dict) and body.get("error"):
        value = body["error"]
        return str(value.get("message") if isinstance(value, dict) else value)
    return None
