"""YouTube OAuth routes; accounts and publications use the shared workflow."""
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.database import get_pool
from app.dependencies.auth import require_auth
from app.security import new_oauth_state, oauth_state_hash, session_token_hash
from app.services import youtube
from app.services.crypto import encrypt_token
from app.services.social_accounts import ensure_local_workspace_link

router = APIRouter(tags=['YouTube'])


def notice(error=None):
    params = {'oauth_provider': 'youtube', 'oauth_error': error} if error else {'oauth_provider': 'youtube', 'connected': '1'}
    return RedirectResponse('/app/networks?' + urlencode(params), status_code=303)


def session_hash(request):
    token = request.cookies.get(youtube.get_settings().session_cookie_name, '')
    return session_token_hash(token) if token else ''


@router.get('/networks/youtube/connect')
async def connect(request: Request, user=Depends(require_auth)):
    try:
        settings = youtube.configured()
        uri = youtube.redirect_uri()
    except youtube.YouTubeError as exc:
        return notice(str(exc))
    if not session_hash(request):
        return notice('Une session navigateur est requise pour connecter YouTube.')
    state = new_oauth_state()
    async with get_pool().acquire() as conn:
        await conn.execute('''INSERT INTO public.app_social_oauth_states
            (user_id, workspace_id, state_hash, redirect_uri, provider, expires_at, session_hash)
            VALUES ($1::uuid,$2::uuid,$3,$4,'youtube',now()+interval '10 minutes',$5)''',
            user.id, user.active_workspace_id, oauth_state_hash(state), uri, session_hash(request))
    return RedirectResponse('https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
        'client_id': settings.google_client_id, 'redirect_uri': uri, 'response_type': 'code',
        'scope': ' '.join(youtube.SCOPES), 'state': state, 'access_type': 'offline',
        'prompt': 'consent select_account',
    }), status_code=302)


@router.get('/networks/youtube/callback')
async def callback(request: Request, state: str = '', code: str = '', error: str = '', user=Depends(require_auth)):
    if not state or not session_hash(request):
        return notice('État OAuth absent ou session expirée.')
    # Atomic consumption binds state to the user, active company AND browser.
    async with get_pool().acquire() as conn:
        saved = await conn.fetchrow('''DELETE FROM public.app_social_oauth_states
            WHERE state_hash=$1 AND provider='youtube' AND user_id=$2::uuid AND workspace_id=$3::uuid
              AND session_hash=$4 AND expires_at>now() RETURNING redirect_uri''',
            oauth_state_hash(state), user.id, user.active_workspace_id, session_hash(request))
    if not saved:
        return notice('État OAuth invalide, expiré ou déjà utilisé. Recommencez la connexion.')
    if error or not code:
        return notice('Autorisation Google annulée ou refusée.')
    try:
        tokens, channel = await youtube.exchange_code(code, saved['redirect_uri'])
        snippet = channel.get('snippet') or {}
        if not channel.get('id'):
            raise youtube.YouTubeError('Chaîne YouTube introuvable.')
        async with get_pool().acquire() as conn:
          async with conn.transaction():
            account = await conn.fetchrow('''INSERT INTO public.app_social_accounts
                (user_id, workspace_id, provider, external_account_id, display_name, platform_account_name,
                 external_username, token_ciphertext, token_expires_at, scopes, metadata)
                VALUES ($1::uuid,$2::uuid,'youtube',$3,$4,$4,$5,$6,$7,$8::jsonb,$9::jsonb)
                ON CONFLICT (workspace_id, external_account_id) WHERE provider='youtube' AND deleted_at IS NULL
                DO UPDATE SET user_id=EXCLUDED.user_id, display_name=EXCLUDED.display_name,
                    platform_account_name=EXCLUDED.platform_account_name, external_username=EXCLUDED.external_username,
                    token_ciphertext=EXCLUDED.token_ciphertext, token_expires_at=EXCLUDED.token_expires_at,
                    scopes=EXCLUDED.scopes, metadata=EXCLUDED.metadata, is_active=true, updated_at=now()
                RETURNING id::text''', user.id, user.active_workspace_id, channel['id'], snippet.get('title') or 'YouTube',
                snippet.get('customUrl') or '', encrypt_token(json.dumps({
                    'access_token': tokens['access_token'], 'refresh_token': tokens['refresh_token']})),
                datetime.now(timezone.utc) + timedelta(seconds=int(tokens.get('expires_in', 3600))),
                json.dumps(youtube.SCOPES), json.dumps({'connection_provider': 'google', 'service': 'youtube'}))
            await ensure_local_workspace_link(conn, account['id'], user.active_workspace_id, user.id)
    except (youtube.YouTubeError, httpx.HTTPError) as exc:
        return notice(str(exc) if isinstance(exc, youtube.YouTubeError) else 'Connexion Google indisponible. Réessayez.')
    return notice()


@router.get('/posts/publication-progress/{publication_id}')
async def progress(publication_id: UUID, user=Depends(require_auth)):
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow('''SELECT status, upload_bytes, upload_total_bytes, error_message,
            response->'provider_response'->>'url' AS video_url,
            response->'provider_response'->>'privacy' AS video_privacy,
            response->'provider_response'->>'id' AS video_id
            FROM public.post_publications WHERE id=$1::uuid AND workspace_id=$2::uuid''',
            str(publication_id), user.active_workspace_id)
    if not row:
        return JSONResponse({'success': False}, status_code=404)
    return JSONResponse({'success': True, 'data': dict(row)}, headers={'Cache-Control': 'no-store'})
