"""
Client Meta Graph API (Facebook + Instagram) — CORRIGÉ suite à ré-analyse
du nœud "Finaliser configuration publication réseau" (endpoints/payloads
exacts, différents de ma première approximation) :

- Base API à deux variantes selon le type de connexion Instagram :
    * "Instagram direct" (Instagram Login natif)  -> https://graph.instagram.com/{version}
    * Instagram via Page Facebook liée            -> https://graph.facebook.com/{version}
  Facebook utilise toujours graph.facebook.com/{version}.

- Facebook photo  : POST {base}/{page_id}/photos
    payload EXACT: {access_token, url, caption, published:true}   <- PAS "message" !
- Facebook vidéo native (hors Reel) : POST {base}/{page_id}/videos
    payload EXACT: {access_token, file_url, description}
- Facebook texte seul : POST {base}/{page_id}/feed
    payload EXACT: {access_token, message}
- Facebook Reel : upload resumable en 3 étapes (video_reels) — inchangé, cf. §5.2 Addendum.
- Instagram : modèle container (media -> status poll -> media_publish) — inchangé.
  Pour Instagram, si le média vidéo n'est pas encore sur un stockage public,
  l'original bascule sur un "proxy vidéo" applicatif :
  {public_origin}/app/posts/media-video.mp4?media_id=...&request_id=...&meta_fetch=1
  (voir `build_instagram_video_proxy_url` ci-dessous).
"""
from __future__ import annotations

import httpx

from app.config import get_settings
from app.services.settings_service import get_meta_settings, PROVIDER_META_FACEBOOK, PROVIDER_META_INSTAGRAM

DEFAULT_GRAPH_VERSION = "v25.0"  # CORRIGÉ — confirmé par le nœud "Instagram - Lire identité canonique"


async def graph_base(*, instagram_direct: bool = False) -> str:
    provider = PROVIDER_META_INSTAGRAM if instagram_direct else PROVIDER_META_FACEBOOK
    settings = await get_meta_settings(provider)
    version = (settings.graph_version if settings else None) or DEFAULT_GRAPH_VERSION
    host = "graph.instagram.com" if instagram_direct else "graph.facebook.com"
    return f"https://{host}/{version}"


async def _client(*, instagram_direct: bool = False, timeout: float = 120.0) -> httpx.AsyncClient:
    base = await graph_base(instagram_direct=instagram_direct)
    return httpx.AsyncClient(base_url=base, timeout=timeout)


def build_instagram_video_proxy_url(*, media_id: str, request_id: str | None = None) -> str:
    """Port exact du fallback proxy vidéo pour Instagram (cf. docstring module)."""
    app_base_url = get_settings().app_base_url.rstrip("/")
    url = f"{app_base_url}/app/posts/media-video.mp4?media_id={media_id}&meta_fetch=1"
    if request_id:
        url += f"&request_id={request_id}"
    return url


# --- OAuth --------------------------------------------------------------

async def exchange_code_for_token(code: str, redirect_uri: str) -> dict:
    settings = await get_meta_settings(PROVIDER_META_FACEBOOK)
    async with await _client() as client:
        resp = await client.get("/oauth/access_token", params={
            "client_id": settings.app_id, "client_secret": settings.app_secret,
            "redirect_uri": redirect_uri, "code": code,
        })
        return resp.json()


async def exchange_for_long_lived_token(short_lived_token: str) -> dict:
    settings = await get_meta_settings(PROVIDER_META_FACEBOOK)
    async with await _client() as client:
        resp = await client.get("/oauth/access_token", params={
            "grant_type": "fb_exchange_token", "client_id": settings.app_id,
            "client_secret": settings.app_secret, "fb_exchange_token": short_lived_token,
        })
        return resp.json()


async def exchange_instagram_code(code: str, redirect_uri: str) -> dict:
    """
    Instagram Login direct : l'échange du code se fait sur
    api.instagram.com/oauth/access_token en POST form-urlencoded — un endpoint
    et un hôte différents de ceux de Facebook. Retourne un jeton COURT.
    """
    settings = await get_meta_settings(PROVIDER_META_INSTAGRAM)
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.instagram.com/oauth/access_token",
            data={
                "client_id": settings.app_id,
                "client_secret": settings.app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        return resp.json()


async def exchange_instagram_long_lived(short_token: str) -> dict:
    """Jeton court -> jeton longue durée (60 jours) sur graph.instagram.com."""
    settings = await get_meta_settings(PROVIDER_META_INSTAGRAM)
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            "https://graph.instagram.com/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": settings.app_secret,
                "access_token": short_token,
            },
            headers={"Accept": "application/json"},
        )
        return resp.json()


async def list_facebook_pages(user_access_token: str) -> dict:
    async with await _client() as client:
        resp = await client.get("/me/accounts", params={"access_token": user_access_token})
        return resp.json()


# --- Facebook : publication (endpoints/payloads EXACTS) --------------------

async def publish_facebook_text(page_id: str, page_access_token: str, message: str) -> httpx.Response:
    async with await _client() as client:
        return await client.post(f"/{page_id}/feed", json={"access_token": page_access_token, "message": message})


async def publish_facebook_photo(page_id: str, page_access_token: str, image_url: str, caption: str) -> httpx.Response:
    async with await _client() as client:
        return await client.post(f"/{page_id}/photos", json={
            "access_token": page_access_token, "url": image_url, "caption": caption, "published": True,
        })


async def publish_facebook_video(page_id: str, page_access_token: str, video_url: str, description: str) -> httpx.Response:
    """Upload vidéo natif (hors Reel) — endpoint /videos, distinct de /video_reels."""
    async with await _client() as client:
        return await client.post(f"/{page_id}/videos", json={
            "access_token": page_access_token, "file_url": video_url, "description": description,
        })


# --- Facebook Reel : upload resumable en 3 étapes --------------------------

async def start_facebook_reel_upload(page_id: str, page_access_token: str) -> dict:
    async with await _client() as client:
        resp = await client.post(f"/{page_id}/video_reels", json={
            "upload_phase": "start", "access_token": page_access_token,
        })
        return resp.json()


async def upload_facebook_reel_binary(upload_url: str, page_access_token: str, media_public_url: str) -> httpx.Response:
    async with httpx.AsyncClient(timeout=120) as client:
        return await client.post(upload_url, headers={
            "Authorization": f"OAuth {page_access_token}", "file_url": media_public_url,
        })


async def finish_facebook_reel_upload(
    page_id: str, page_access_token: str, video_id: str, description: str, title: str,
) -> httpx.Response:
    async with await _client() as client:
        return await client.post(f"/{page_id}/video_reels", json={
            "access_token": page_access_token, "upload_phase": "finish", "video_id": video_id,
            "video_state": "PUBLISHED", "description": description, "title": title,
        })


# --- Instagram : modèle container -------------------------------------------

async def create_instagram_container(
    ig_user_id: str, access_token: str, *, image_url: str | None = None,
    video_url: str | None = None, caption: str, instagram_direct: bool = False,
    media_type: str | None = None, share_to_feed: bool | None = None,
) -> httpx.Response:
    body = {"access_token": access_token, "caption": caption}
    if image_url:
        body["image_url"] = image_url
    if video_url:
        body["video_url"] = video_url
    if media_type:
        body["media_type"] = media_type
    if share_to_feed is not None:
        body["share_to_feed"] = "true" if share_to_feed else "false"
    async with await _client(instagram_direct=instagram_direct) as client:
        return await client.post(
            f"/{ig_user_id}/media",
            headers={"Accept": "application/json", "User-Agent": "PostGenerator/1.0 MetaInstagramPublisher"},
            data=body,
        )


async def get_instagram_container_status(container_id: str, access_token: str, *, instagram_direct: bool = False) -> httpx.Response:
    async with await _client(instagram_direct=instagram_direct, timeout=60.0) as client:
        return await client.get(f"/{container_id}", params={
            "fields": "status_code,status", "access_token": access_token,
        }, headers={"Accept": "application/json"})


async def publish_instagram_container(ig_user_id: str, access_token: str, creation_id: str, *, instagram_direct: bool = False) -> httpx.Response:
    async with await _client(instagram_direct=instagram_direct) as client:
        return await client.post(
            f"/{ig_user_id}/media_publish",
            headers={"Accept": "application/json", "User-Agent": "PostGenerator/1.0 MetaInstagramPublisher"},
            data={"creation_id": creation_id, "access_token": access_token},
        )


async def get_instagram_canonical_identity(short_access_token: str, *, graph_version: str | None = None) -> dict:
    """
    Port exact de "Instagram - Lire identité canonique" :
    GET https://graph.instagram.com/{version}/me?fields=user_id,username&access_token=...
    Utilisé juste après l'échange OAuth pour résoudre l'identité stable du
    compte Instagram professionnel (Instagram Login natif).
    """
    version = graph_version or DEFAULT_GRAPH_VERSION
    async with httpx.AsyncClient(base_url=f"https://graph.instagram.com/{version}", timeout=60) as client:
        resp = await client.get("/me", params={"fields": "user_id,username", "access_token": short_access_token},
                                 headers={"Accept": "application/json", "Cache-Control": "no-cache"})
        return resp.json()


async def refresh_instagram_long_lived_token(current_token: str) -> tuple[str, "datetime"]:
    """
    Rafraîchissement du jeton longue durée Instagram.
    L'URL est SANS numéro de version : https://graph.instagram.com/refresh_access_token
    (contrairement aux appels de publication qui, eux, sont versionnés).
    """
    from datetime import datetime, timedelta, timezone
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            "https://graph.instagram.com/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": current_token},
            headers={"Accept": "application/json"},
        )
        data = resp.json()
    new_token = data.get("access_token", current_token)
    expires_in = int(data.get("expires_in", 60 * 60 * 24 * 60))
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    return new_token, expires_at

# --- Lecture profil / contenus pour les stratégies --------------------------

async def read_strategy_profile(
    *, provider: str, external_account_id: str, access_token: str,
    instagram_direct: bool = False,
) -> dict:
    """Lit le profil social avec les mêmes champs que le V90.

    Instagram Login direct utilise graph.instagram.com/{version}/me ;
    Facebook et les anciennes connexions Instagram via Page utilisent
    graph.facebook.com/{version}/{external_account_id}.
    """
    provider = str(provider or "").lower()
    if provider == "instagram":
        fields = (
            "user_id,username,name,biography,website,followers_count,follows_count,"
            "media_count,profile_picture_url"
            if instagram_direct else
            "id,username,name,biography,website,followers_count,follows_count,"
            "media_count,profile_picture_url"
        )
    else:
        fields = "id,name,about,description,website,fan_count,followers_count,category,link,picture{url}"
    target = "me" if provider == "instagram" and instagram_direct else external_account_id
    async with await _client(instagram_direct=(provider == "instagram" and instagram_direct), timeout=30.0) as client:
        resp = await client.get(f"/{target}", params={"fields": fields, "access_token": access_token},
                                headers={"Accept": "application/json"})
        return {"status_code": resp.status_code, "body": resp.json()}


async def read_strategy_recent_content(
    *, provider: str, external_account_id: str, access_token: str,
    instagram_direct: bool = False, limit: int = 20,
) -> dict:
    """Lit jusqu'à 20 contenus récents avec les champs utilisés dans le V90."""
    provider = str(provider or "").lower()
    if provider == "instagram":
        fields = "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count"
        target = "me" if instagram_direct else external_account_id
        edge = "media"
    else:
        fields = "id,message,created_time,permalink_url,shares,reactions.limit(0).summary(true),comments.limit(0).summary(true)"
        target = external_account_id
        edge = "posts"
    async with await _client(instagram_direct=(provider == "instagram" and instagram_direct), timeout=30.0) as client:
        resp = await client.get(f"/{target}/{edge}", params={
            "fields": fields, "limit": max(1, min(20, int(limit))), "access_token": access_token,
        }, headers={"Accept": "application/json"})
        return {"status_code": resp.status_code, "body": resp.json()}
