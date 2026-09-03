"""
Client Buffer API — CORRECTION majeure suite à ré-analyse du workflow source
(nœud "Finaliser configuration publication réseau") : Buffer n'utilise PAS
un simple endpoint REST comme initialement documenté, mais l'API **GraphQL**
de Buffer (mutation `createPost`), avec échappement manuel des chaînes
(escGraphql) construit directement en template string dans l'original.

Endpoint unique : POST https://api.buffer.com (GraphQL)
Authentification : Bearer token (clé API utilisateur, stockée chiffrée).
"""
from __future__ import annotations

import httpx

BUFFER_GRAPHQL_URL = "https://api.buffer.com"


def _esc_graphql(value: str) -> str:
    """Port exact de la fonction escGraphql() originale."""
    return (
        (value or "")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )


def _buffer_post_type(publish_content_type: str) -> str:
    t = (publish_content_type or "standard").lower()
    if t == "story":
        return "story"
    if t == "reel":
        return "reel"
    return "post"


def _build_assets(media_url: str | None, media_kind: str) -> str:
    if not media_url or media_kind == "none":
        return ""
    if media_kind == "image":
        return f'\n          assets: [{{ image: {{ url: "{_esc_graphql(media_url)}" }} }}]'
    if media_kind == "video":
        return f'\n          assets: [{{ video: {{ url: "{_esc_graphql(media_url)}" }} }}]'
    return ""


def _build_metadata(platform: str, publish_content_type: str) -> str:
    post_type = _buffer_post_type(publish_content_type)
    if platform == "instagram":
        share_to_feed = "false" if post_type == "story" else "true"
        return (
            f"\n          metadata: {{ instagram: {{ type: {post_type}, "
            f"shouldShareToFeed: {share_to_feed}, isAiGenerated: false }} }}"
        )
    if platform == "facebook" and post_type == "reel":
        return "\n          metadata: { facebook: { type: reel } }"
    return ""


def build_create_post_mutation(
    *, text: str, channel_id: str, platform: str, media_url: str | None = None,
    media_kind: str = "none", publish_content_type: str = "standard",
    is_scheduled: bool = False, scheduled_at: str | None = None,
) -> str:
    """
    Port exact de la construction de `buffer_query` (mutation GraphQL) telle
    qu'assemblée dans le workflow original (template string + escGraphql).
    """
    mode = "customScheduled" if is_scheduled else "shareNow"
    due_at = f'\n          dueAt: "{_esc_graphql(scheduled_at)}"' if (is_scheduled and scheduled_at) else ""
    assets = _build_assets(media_url, media_kind)
    metadata = _build_metadata(platform, publish_content_type)

    return (
        "mutation CreatePost { createPost(input: { "
        f'text: "{_esc_graphql(text)}" '
        f'channelId: "{_esc_graphql(channel_id)}" '
        f"schedulingType: automatic mode: {mode}{due_at}{metadata}{assets} "
        'source: "n8n-post-generator-v0-matrix-v8" '
        "}) { ... on PostActionSuccess { post { id text dueAt status shareMode "
        "assets { id type mimeType source } } } ... on MutationError { message } } }"
    )


async def buffer_graphql_request(api_key: str, query: str) -> httpx.Response:
    async with httpx.AsyncClient(base_url=BUFFER_GRAPHQL_URL, timeout=120) as client:
        return await client.post(
            "/",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"query": query},
        )


async def create_post(
    api_key: str, *, text: str, channel_id: str, platform: str, media_url: str | None = None,
    media_kind: str = "none", publish_content_type: str = "standard",
    is_scheduled: bool = False, scheduled_at: str | None = None,
) -> httpx.Response:
    mutation = build_create_post_mutation(
        text=text, channel_id=channel_id, platform=platform, media_url=media_url,
        media_kind=media_kind, publish_content_type=publish_content_type,
        is_scheduled=is_scheduled, scheduled_at=scheduled_at,
    )
    return await buffer_graphql_request(api_key, mutation)


async def test_user_access(api_key: str) -> httpx.Response:
    """Vérification d'accès (introspection simple)."""
    return await buffer_graphql_request(api_key, "{ __typename }")


async def get_channel(api_key: str, channel_id: str) -> httpx.Response:
    """Fetch one Buffer channel with the GraphQL input shape used by Buffer/n8n."""
    query = (
        'query GetChannel { channel(input: { id: "' + _esc_graphql(channel_id) + '" }) '
        '{ id name displayName service organizationId isQueuePaused isLocked isDisconnected } }'
    )
    return await buffer_graphql_request(api_key, query)


async def get_queue(api_key: str, channel_id: str) -> httpx.Response:
    """Read Buffer posting limits/queue metadata using the n8n V90 query shape."""
    escaped = _esc_graphql(channel_id)
    query = (
        'query NetworkQuota { '
        'dailyPostingLimits(input: { channelIds: ["' + escaped + '"] }) '
        '{ channelId sent scheduled limit isAtLimit } '
        'channel(input: { id: "' + escaped + '" }) '
        '{ id organizationId isQueuePaused isLocked } '
        'account { organizations { id limits { scheduledPosts } } } '
        '}'
    )
    return await buffer_graphql_request(api_key, query)


async def get_scheduled_queue(
    api_key: str, *, channel_id: str, organization_id: str, page_size: int,
) -> httpx.Response:
    """Read Buffer scheduled posts exactly like the n8n V90 quota flow."""
    size = max(1, min(5000, int(page_size or 1)))
    channel = _esc_graphql(channel_id)
    organization = _esc_graphql(organization_id)
    query = (
        f'query NetworkQueueCapacity {{ posts(first: {size}, input: {{ '
        f'organizationId: "{organization}", '
        'sort: [{ field: dueAt, direction: asc }, { field: createdAt, direction: desc }], '
        f'filter: {{ status: [scheduled], channelIds: ["{channel}"] }} '
        '}) { edges { node { id channelId status } cursor } '
        'pageInfo { endCursor hasNextPage } } }'
    )
    return await buffer_graphql_request(api_key, query)
