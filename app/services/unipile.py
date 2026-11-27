"""Server-side client for the Unipile LinkedIn messaging integration."""
import re
from urllib.parse import unquote, urlsplit

import httpx

from app.config import get_settings


class UnipileError(Exception):
    def __init__(self, status: int = 502):
        self.status = status


def api_origin() -> str:
    settings = get_settings()
    dsn = settings.unipile_dsn.strip().rstrip('/')
    if dsn and '://' not in dsn:
        dsn = 'https://' + dsn
    try:
        parts = urlsplit(dsn)
        valid = (parts.scheme == 'https' and parts.hostname
                 and parts.hostname.endswith('.unipile.com') and not parts.username
                 and not parts.password and not parts.path and not parts.query and not parts.fragment)
    except ValueError:
        valid = False
    return dsn if valid and settings.unipile_api_key.strip() else ''


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
            response = await client.request(method, origin + '/api/v1/' + path, headers=headers, **kwargs)
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


async def search_contacts(account_id: str, keywords: str) -> dict:
    return await request('POST', 'linkedin/search', params={'account_id': account_id, 'limit': 10},
                         json={'api': 'classic', 'category': 'people', 'keywords': keywords,
                               'network_distance': [1]})
