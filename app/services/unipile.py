"""Server-side client for the Unipile LinkedIn messaging integration."""
import re
from urllib.parse import quote, unquote, urlsplit

import httpx

from app.config import get_settings

V2_ORIGIN = 'https://api.unipile.com'
V2_ACCOUNT_ID = re.compile(r'acc_[A-Za-z0-9_-]{1,124}')

class UnipileError(Exception):
    def __init__(self, status: int = 502):
        self.status = status


def api_origin() -> str:
    settings = get_settings()
    if not settings.unipile_api_key.strip():
        return ''
    dsn = settings.unipile_dsn.strip().rstrip('/')
    if dsn in ('', V2_ORIGIN, V2_ORIGIN + '/v2', 'api.unipile.com'):
        return V2_ORIGIN
    if dsn and '://' not in dsn:
        dsn = 'https://' + dsn
    try:
        parts = urlsplit(dsn)
        valid = (parts.scheme == 'https' and parts.hostname
                 and parts.hostname.endswith('.unipile.com') and not parts.username
                 and not parts.password and not parts.path and not parts.query and not parts.fragment)
    except ValueError:
        valid = False
    return dsn if valid else ''


def uses_v2() -> bool:
    return api_origin() == V2_ORIGIN


def profile_slug(value: str) -> str:
    try:
        parts = urlsplit(value.strip())
        match = re.fullmatch(r'/in/([^/]+)/?', unquote(parts.path))
    except ValueError:
        raise ValueError('invalid LinkedIn URL') from None
    if (parts.scheme != 'https' or parts.netloc.lower() not in ('linkedin.com', 'www.linkedin.com')
            or not match or not re.fullmatch(r'[\w-]{1,160}', match[1])):
        raise ValueError('invalid LinkedIn URL')
    return match[1]


async def request(method: str, path: str, **kwargs) -> dict:
    origin = api_origin()
    if not origin:
        raise UnipileError(503)
    headers = {'X-API-KEY': get_settings().unipile_api_key.strip(), 'Accept': 'application/json'}
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            prefix = '/v2/' if origin == V2_ORIGIN else '/api/v1/'
            response = await client.request(method, origin + prefix + path, headers=headers, **kwargs)
        if not response.is_success:
            raise UnipileError(response.status_code)
        if response.status_code == 204:
            return {}
        data = response.json()
    except (httpx.HTTPError, ValueError):
        raise UnipileError() from None
    if not isinstance(data, dict):
        raise UnipileError()
    return data


async def search_contacts(account_id: str, keywords: str, *, cursor: str | None = None) -> dict:
    pagination = {'cursor': cursor} if cursor else {}
    if uses_v2():
        return await request('POST', f'{account_id}/linkedin/search/people',
                             params=pagination, json={'keywords': keywords, 'network_distance': [1]})
    return await request('POST', 'linkedin/search', params={'account_id': account_id, 'limit': 10, **pagination},
                         json={'api': 'classic', 'category': 'people', 'keywords': keywords,
                               'network_distance': [1]})


async def get_profile(account_id: str, slug: str) -> dict:
    profile = f'users/{quote(slug, safe="")}'
    if uses_v2():
        return await request('GET', f'{account_id}/{profile}', params={'variant': 'linkedin_classic'})
    return await request('GET', profile, params={'account_id': account_id})


async def send_message(account_id: str, provider_id: str, message: str) -> dict:
    if uses_v2():
        return await request('POST', f'{account_id}/inboxes/CLASSIC/chats/send',
                             json={'users_ids': provider_id, 'text': message})
    return await request('POST', 'chats', files={
        'account_id': (None, account_id), 'attendees_ids': (None, provider_id), 'text': (None, message),
    })
