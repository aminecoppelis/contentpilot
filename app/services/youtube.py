"""Google OAuth and durable, chunked YouTube uploads. No credentials in UI data."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings
from app.database import get_pool
from app.services.crypto import decrypt_token, encrypt_token

UPLOAD_SCOPE = 'https://www.googleapis.com/auth/youtube.upload'
# channels.list(mine=true) requires channel read access in addition to upload.
READ_SCOPE = 'https://www.googleapis.com/auth/youtube.readonly'
SCOPES = [UPLOAD_SCOPE, READ_SCOPE]
TOKEN_URL = 'https://oauth2.googleapis.com/token'
API = 'https://www.googleapis.com/youtube/v3'
UPLOAD_URL = 'https://www.googleapis.com/upload/youtube/v3/videos'


class YouTubeError(ValueError):
    pass


class UploadInterrupted(YouTubeError):
    """Retry the same saved session; never create a second upload automatically."""


def configured():
    settings = get_settings()
    if not (settings.google_client_id and settings.google_client_secret and settings.token_encryption_key):
        raise YouTubeError('Configure GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET et TOKEN_ENCRYPTION_KEY.')
    try:
        Fernet(settings.token_encryption_key.encode())
    except (ValueError, TypeError):
        raise YouTubeError('TOKEN_ENCRYPTION_KEY doit être une clé Fernet valide.') from None
    return settings


def redirect_uri():
    s = configured()
    return s.google_redirect_uri or s.app_base_url.rstrip('/') + '/app/networks/youtube/callback'


def checked(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code >= 400:
        err = body.get('error') or {}
        reason = ((err.get('errors') or [{}])[0].get('reason') if isinstance(err, dict) else err)
        if response.status_code == 401 or reason == 'invalid_grant':
            raise YouTubeError('Autorisation Google expirée ou révoquée. Reconnectez la chaîne YouTube.')
        if reason in ('quotaExceeded', 'dailyLimitExceeded', 'uploadLimitExceeded'):
            raise YouTubeError('Quota YouTube atteint. Réessayez après son renouvellement.')
        # Do not leak HTTP request URLs, authorization headers or provider bodies.
        raise YouTubeError(f'YouTube a refusé la demande (HTTP {response.status_code}, {str(reason or "API_ERROR")[:80]}).')
    return body


async def exchange_code(code: str, uri: str):
    s = configured()
    async with httpx.AsyncClient(timeout=60) as client:
        data = checked(await client.post(TOKEN_URL, data={
            'client_id': s.google_client_id, 'client_secret': s.google_client_secret,
            'code': code, 'redirect_uri': uri, 'grant_type': 'authorization_code',
        }))
        if not data.get('access_token') or not data.get('refresh_token'):
            raise YouTubeError('Google n’a pas fourni les jetons hors ligne. Reconnectez avec le consentement Google.')
        if not set(SCOPES).issubset(set(str(data.get('scope') or '').split())):
            raise YouTubeError('Les autorisations de publication et de lecture de la chaîne sont requises.')
        channels = checked(await client.get(API + '/channels', params={'part': 'snippet', 'mine': 'true'},
                                            headers={'Authorization': 'Bearer ' + data['access_token']}))
    items = channels.get('items') or []
    if len(items) != 1:
        raise YouTubeError('Sélectionnez un compte Google associé à une seule chaîne YouTube lors du consentement.')
    return data, items[0]


async def revoke(account):
    tokens = json.loads(decrypt_token(account['token_ciphertext'])) if account['token_ciphertext'] else {}
    token = tokens.get('refresh_token') or tokens.get('access_token')
    if not token:
        return
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post('https://oauth2.googleapis.com/revoke', data={'token': token})
        # invalid_token means authorization has already been revoked.
        if response.status_code == 400 and response.json().get('error') == 'invalid_token':
            return
        checked(response)
    except (httpx.HTTPError, ValueError):
        raise YouTubeError('Révocation Google non confirmée. Réessayez la déconnexion.') from None


async def access_token(account_id: str, workspace_id: str, *, force=False) -> str:
    """Lock refreshes across processes and enforce owner workspace, even for shares."""
    s = configured()
    async with get_pool().acquire() as conn:
      async with conn.transaction():
        row = await conn.fetchrow('''SELECT token_ciphertext, token_expires_at FROM public.app_social_accounts
            WHERE id=$1::uuid AND workspace_id=$2::uuid AND provider='youtube'
              AND is_active=true AND deleted_at IS NULL FOR UPDATE''', account_id, workspace_id)
        if not row:
            raise YouTubeError('Chaîne YouTube inactive ou inaccessible dans cette entreprise.')
        try:
            tokens = json.loads(decrypt_token(row['token_ciphertext']))
        except (InvalidToken, ValueError, TypeError):
            raise YouTubeError('Jetons Google illisibles. Vérifiez la clé de chiffrement ou reconnectez la chaîne.') from None
        if not force and row['token_expires_at'] and row['token_expires_at'] > datetime.now(timezone.utc) + timedelta(minutes=2):
            return tokens['access_token']
        async with httpx.AsyncClient(timeout=60) as client:
            data = checked(await client.post(TOKEN_URL, data={
                'client_id': s.google_client_id, 'client_secret': s.google_client_secret,
                'refresh_token': tokens['refresh_token'], 'grant_type': 'refresh_token',
            }))
        if not data.get('access_token'):
            raise YouTubeError('Renouvellement du jeton Google impossible. Reconnectez YouTube.')
        tokens['access_token'] = data['access_token']
        tokens['refresh_token'] = data.get('refresh_token') or tokens['refresh_token']
        await conn.execute('''UPDATE public.app_social_accounts SET token_ciphertext=$3,
            token_expires_at=$4, updated_at=now() WHERE id=$1::uuid AND workspace_id=$2::uuid''',
            account_id, workspace_id, encrypt_token(json.dumps(tokens)),
            datetime.now(timezone.utc) + timedelta(seconds=int(data.get('expires_in', 3600))))
        return tokens['access_token']


def video_options(value: dict) -> dict:
    if not isinstance(value, dict):
        raise YouTubeError('Renseignez les informations de la vidéo YouTube.')
    title = str(value.get('title') or '').strip()
    description = str(value.get('description') or '').strip()
    tags = value.get('tags') or []
    privacy = value.get('privacy', 'private')
    if not title or len(title) > 100 or '<' in title or '>' in title:
        raise YouTubeError('Le titre YouTube est requis (100 caractères maximum, sans chevrons).')
    if len(description.encode('utf-8')) > 5000 or '<' in description or '>' in description:
        raise YouTubeError('Description YouTube invalide (5 000 octets maximum, sans chevrons).')
    if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
        raise YouTubeError('Les tags YouTube doivent être une liste de textes.')
    tags = list(dict.fromkeys(t.strip() for t in tags if t.strip()))
    if sum(len(t) + (2 if ' ' in t else 0) for t in tags) + max(0, len(tags)-1) > 500:
        raise YouTubeError('Les tags YouTube dépassent la limite de 500 caractères.')
    if privacy not in ('public', 'private', 'unlisted'):
        raise YouTubeError('Visibilité YouTube invalide.')
    if not isinstance(value.get('made_for_kids'), bool):
        raise YouTubeError('Indiquez si la vidéo est conçue pour les enfants.')
    return {'title': title, 'description': description, 'tags': tags, 'privacy': privacy,
            'made_for_kids': value['made_for_kids']}


def session_url(value: str) -> str:
    url = urlsplit(value)
    if url.scheme != 'https' or url.hostname != 'www.googleapis.com' or url.port not in (None, 443) or url.username or url.path != '/upload/youtube/v3/videos':
        raise YouTubeError('URL de session YouTube invalide.')
    return value


def confirmed_offset(response, total):
    value = response.headers.get('Range', '')
    if not value:
        return 0
    match = re.fullmatch(r'bytes=0-(\d+)', value)
    if not match or int(match[1]) >= total:
        raise YouTubeError('Progression YouTube incohérente.')
    return int(match[1]) + 1


async def upload(account, publication_id: str, workspace_id: str, options: dict) -> dict:
    """Uses only the local, workspace-scoped selected file; bounded memory."""
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow('''SELECT pm.file_path, pm.mime_type, pp.youtube_upload_ciphertext
            FROM public.post_publications pp JOIN public.post_media pm
              ON pm.id=pp.media_id AND pm.workspace_id=pp.workspace_id AND pm.idea_id=pp.idea_id
            WHERE pp.id=$1::uuid AND pp.workspace_id=$2::uuid AND pm.media_type='video' AND pm.status='ready' ''',
            publication_id, workspace_id)
    if not row or not row['file_path']:
        raise YouTubeError('La vidéo doit être enregistrée localement avant son envoi YouTube.')
    path = Path(row['file_path'])
    path = (get_settings().media_storage_path / path.name if not path.is_absolute() else path).resolve()
    if not path.is_relative_to(get_settings().media_storage_path) or not path.is_file():
        raise YouTubeError('Fichier vidéo indisponible sur ce serveur.')
    size = path.stat().st_size
    if size <= 0:
        raise YouTubeError('Le fichier vidéo est vide.')
    state = json.loads(decrypt_token(row['youtube_upload_ciphertext'])) if row['youtube_upload_ciphertext'] else {}
    if state.get('result'):
        return state['result']
    if state and (state.get('size') != size or state.get('mtime') != path.stat().st_mtime_ns):
        raise YouTubeError('Le fichier a changé pendant l’envoi. La reprise a été arrêtée.')
    token = await access_token(str(account['id']), workspace_id)
    async def save(offset):
        async with get_pool().acquire() as conn:
            await conn.execute('''UPDATE public.post_publications SET youtube_upload_ciphertext=$3,
                upload_bytes=$4, upload_total_bytes=$5, updated_at=now()
                WHERE id=$1::uuid AND workspace_id=$2::uuid AND status='processing' ''',
                publication_id, workspace_id, encrypt_token(json.dumps(state)), offset, size)

    async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
        async def request(method, url, **kwargs):
            nonlocal token
            headers = kwargs.pop('headers', {})
            response = await client.request(method, url, headers={'Authorization': 'Bearer ' + token, **headers}, **kwargs)
            if response.status_code == 401:
                token = await access_token(str(account['id']), workspace_id, force=True)
                response = await client.request(method, url, headers={'Authorization': 'Bearer ' + token, **headers}, **kwargs)
            return response

        options = video_options(options)
        if not state:
            response = await request('POST', UPLOAD_URL, params={'uploadType': 'resumable', 'part': 'snippet,status'},
                headers={'X-Upload-Content-Length': str(size), 'X-Upload-Content-Type': row['mime_type'] or 'video/mp4'},
                json={'snippet': {'title': options['title'], 'description': options['description'], 'tags': options['tags'], 'categoryId': '22'},
                      'status': {'privacyStatus': options['privacy'], 'selfDeclaredMadeForKids': options['made_for_kids']}})
            checked(response)
            state = {'url': session_url(response.headers.get('Location', '')), 'size': size, 'mtime': path.stat().st_mtime_ns}
            await save(0)
        url = session_url(state['url'])
        chunk_size = min(32 * 1024 * 1024, max(256 * 1024, int(get_settings().youtube_chunk_bytes) // (256 * 1024) * (256 * 1024)))
        failures = 0
        # Always query Google's committed offset, including after a process restart.
        probe = True
        offset = 0
        with path.open('rb') as video:
            while True:
                try:
                    if probe:
                        response = await request('PUT', url, content=b'', headers={'Content-Length': '0', 'Content-Range': f'bytes */{size}'})
                    else:
                        video.seek(offset)
                        data = video.read(chunk_size)
                        if not data:
                            raise UploadInterrupted('Confirmation finale YouTube en attente ; la session sera reprise.')
                        response = await request('PUT', url, content=data, headers={
                            'Content-Type': row['mime_type'] or 'video/mp4', 'Content-Length': str(len(data)),
                            'Content-Range': f'bytes {offset}-{offset+len(data)-1}/{size}'})
                    if response.status_code in (200, 201):
                        body = checked(response)
                        if not re.fullmatch(r'[A-Za-z0-9_-]+', str(body.get('id') or '')):
                            raise UploadInterrupted('Confirmation vidéo YouTube manquante ; reprise de la session nécessaire.')
                        if (body.get('status') or {}).get('uploadStatus') in ('failed', 'rejected', 'deleted'):
                            raise YouTubeError('YouTube a rejeté la vidéo après son envoi.')
                        result = {'id': body['id'], 'url': 'https://www.youtube.com/watch?v=' + body['id'],
                                  'privacy': (body.get('status') or {}).get('privacyStatus'), 'upload_status': (body.get('status') or {}).get('uploadStatus')}
                        state['result'] = result
                        await save(size)
                        return result
                    if response.status_code == 308:
                        next_offset = confirmed_offset(response, size)
                        if not probe and next_offset <= offset:
                            raise UploadInterrupted('YouTube ne confirme aucun nouvel octet ; reprise de la session nécessaire.')
                        if next_offset > offset:
                            failures = 0
                        offset = next_offset
                        await save(offset)
                        probe = False
                        continue
                    if response.status_code in (429, 500, 502, 503, 504):
                        raise httpx.TransportError('temporary upload error')
                    if response.status_code in (404, 410):
                        raise YouTubeError('Session YouTube expirée. Aucun nouvel envoi automatique : vérifiez YouTube Studio avant de réessayer.')
                    checked(response)
                    raise YouTubeError('Réponse inattendue pendant l’envoi YouTube.')
                except httpx.TransportError:
                    failures += 1
                    if failures >= 4:
                        raise UploadInterrupted('Envoi interrompu ; reprise automatique de la même session.') from None
                    probe = True
                    await asyncio.sleep(min(2 ** failures, 8))
