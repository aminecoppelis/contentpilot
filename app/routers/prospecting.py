"""LinkedIn account linking and outreach from SocialAI."""
import asyncio
import hmac
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit
from uuid import UUID, uuid4, uuid5

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from app.config import get_settings
from app.database import get_pool
from app.dependencies.auth import require_admin
from app.i18n import resolve_locale
from app.public_origin import resolve_public_origin
from app.security import new_oauth_state, oauth_state_hash
from app.services import ai, unipile
from app.templating import templates


router = APIRouter(tags=['Prospecting'])
PAGE = '/app/prospecting'
PROVIDER = 'unipile_linkedin'
ACCOUNT_ID = re.compile(r'[A-Za-z0-9_-]{1,128}')
# Allow two 25-second Unipile calls per recipient within the proxy's 300-second timeout.
MAX_RECIPIENTS = 5


class ConnectionNotification(BaseModel):
    status: str
    account_id: str = Field(max_length=128)
    name: str = Field(max_length=128)


def form_token(request, user):
    session = request.cookies.get(get_settings().session_cookie_name, '')
    context = f'linkedin-prospecting:{user.active_workspace_id}'.encode()
    return hmac.digest(session.encode(), context, 'sha256').hex() if session else ''


def check_form(request, user, csrf):
    token = form_token(request, user)
    if not token or not hmac.compare_digest(csrf.encode(), token.encode()):
        raise HTTPException(403)


def notice(status, campaign_id=None):
    location = f'{PAGE}?result={status}'
    if campaign_id:
        location += f'&campaign_id={campaign_id}'
    return RedirectResponse(location, status_code=303)


async def connected_account(conn, user):
    return await conn.fetchrow('''SELECT unipile_account_id, display_name
        FROM public.linkedin_prospecting_accounts WHERE user_id=$1::uuid AND workspace_id=$2::uuid''',
        user.id, user.active_workspace_id)


async def owned_campaign(conn, user, campaign_id):
    campaign = await conn.fetchrow('''SELECT id, name, target FROM public.linkedin_prospecting_campaigns
        WHERE id=$1 AND user_id=$2::uuid AND workspace_id=$3::uuid''', campaign_id, user.id, user.active_workspace_id)
    if not campaign:
        raise HTTPException(404)
    return campaign


@router.get('/prospecting', response_class=HTMLResponse)
async def index(request: Request, result: str = '', campaign_id: UUID | None = None, user=Depends(require_admin)):
    async with get_pool().acquire() as conn:
        account = await connected_account(conn, user)
        campaigns = await conn.fetch('''SELECT id, name FROM public.linkedin_prospecting_campaigns
            WHERE user_id=$1::uuid AND workspace_id=$2::uuid ORDER BY created_at DESC''',
            user.id, user.active_workspace_id)
        campaign = await owned_campaign(conn, user, campaign_id) if campaign_id else None
        contacts = await conn.fetch('''SELECT c.*, delivery.status
            FROM public.linkedin_prospecting_contacts c LEFT JOIN LATERAL (
              SELECT status FROM public.linkedin_prospecting_messages m
              WHERE m.campaign_id=c.campaign_id AND m.profile_slug=c.profile_slug
              ORDER BY created_at DESC LIMIT 1
            ) delivery ON true WHERE c.campaign_id=$1 ORDER BY relevance DESC, display_name, profile_slug''',
            campaign_id) if campaign else []
        history = await conn.fetch('''SELECT profile_slug, status, created_at FROM public.linkedin_prospecting_messages
            WHERE user_id=$1::uuid AND workspace_id=$2::uuid AND campaign_id IS NOT DISTINCT FROM $3::uuid
            ORDER BY created_at DESC LIMIT 20''', user.id, user.active_workspace_id, campaign_id)
    return templates.TemplateResponse(request, 'prospecting.html', {
        'auth_user': user, 'active_nav': 'prospecting', 'account': account, 'history': history,
        'configured': bool(unipile.api_origin()), 'csrf': form_token(request, user), 'submission_id': uuid4(),
        'result': result, 'max_recipients': MAX_RECIPIENTS,
        'campaigns': campaigns, 'campaign': campaign, 'contacts': contacts,
    }, headers={'Cache-Control': 'no-store'})


@router.post('/prospecting/campaigns')
async def create_campaign(request: Request, csrf: str = Form(), name: str = Form(max_length=120),
                          target: str = Form(max_length=1200), user=Depends(require_admin)):
    check_form(request, user, csrf)
    if not name.strip() or not target.strip():
        return notice('campaign_required')
    async with get_pool().acquire() as conn:
        campaign_id = await conn.fetchval('''INSERT INTO public.linkedin_prospecting_campaigns
            (user_id, workspace_id, name, target) VALUES ($1::uuid,$2::uuid,$3,$4) RETURNING id''',
            user.id, user.active_workspace_id, name.strip(), target.strip())
    return notice('campaign_created', campaign_id)


def real_profiles(data):
    profiles = {}
    items = data.get('items')
    if not isinstance(items, list):
        return []
    for item in items[:10]:
        if not isinstance(item, dict) or item.get('type') != 'PEOPLE':
            continue
        url = item.get('public_profile_url') or item.get('profile_url')
        if not isinstance(url, str):
            continue
        try:
            slug = unipile.profile_slug(url).casefold()
        except ValueError:
            continue
        fields = {key: str(item.get(key) or '')[:limit]
                  for key, limit in (('name', 250), ('headline', 400), ('location', 200))}
        profiles.setdefault(slug, fields)
    return list(profiles.items())


@router.post('/prospecting/campaigns/{campaign_id}/search')
async def search_campaign(request: Request, campaign_id: UUID, csrf: str = Form(), user=Depends(require_admin)):
    check_form(request, user, csrf)
    async with get_pool().acquire() as conn:
        campaign = await owned_campaign(conn, user, campaign_id)
        account = await connected_account(conn, user)
    if not account:
        return notice('not_connected', campaign_id)
    try:
        async with asyncio.timeout(100):
            keywords = await ai.prospecting_keywords(campaign['target'])
            profiles = real_profiles(await unipile.search_contacts(account['unipile_account_id'], keywords))
            if not profiles:
                return notice('no_matches', campaign_id)
            summaries = [{'index': i, 'headline': fields['headline'], 'location': fields['location']}
                         for i, (_, fields) in enumerate(profiles)]
            matches = await ai.rank_prospecting_contacts(campaign['target'], summaries, resolve_locale(request))
    except (ai.AIGenerationError, unipile.UnipileError, httpx.HTTPError, TimeoutError):
        return notice('search_failed', campaign_id)
    rows = []
    for match in matches:
        if not isinstance(match, dict):
            continue
        index, score, reason = match.get('index'), match.get('score'), match.get('reason')
        if (type(index) is not int or not 0 <= index < len(profiles) or type(score) is not int
                or not 0 <= score <= 100 or not isinstance(reason, str) or not reason.strip()):
            continue
        slug, fields = profiles[index]
        rows.append((campaign_id, slug, fields['name'] or slug, fields['headline'], fields['location'], reason[:500], score))
    if not rows:
        return notice('no_matches', campaign_id)
    async with get_pool().acquire() as conn:
        await conn.executemany('''INSERT INTO public.linkedin_prospecting_contacts
            (campaign_id, profile_slug, display_name, headline, location, reason, relevance)
            VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (campaign_id, profile_slug) DO UPDATE
            SET display_name=EXCLUDED.display_name, headline=EXCLUDED.headline, location=EXCLUDED.location,
                reason=EXCLUDED.reason, relevance=EXCLUDED.relevance''', rows)
    return notice('matches_ready', campaign_id)


@router.post('/prospecting/campaigns/{campaign_id}/contacts')
async def add_contacts(request: Request, campaign_id: UUID, csrf: str = Form(),
                       slugs: list[str] = Form(default=[]), user=Depends(require_admin)):
    check_form(request, user, csrf)
    async with get_pool().acquire() as conn:
        await owned_campaign(conn, user, campaign_id)
        updated = await conn.execute('''UPDATE public.linkedin_prospecting_contacts SET added_at=now()
            WHERE campaign_id=$1 AND added_at IS NULL AND profile_slug=ANY($2::text[])''', campaign_id, slugs)
    return notice('contacts_added' if updated != 'UPDATE 0' else 'pick_contacts', campaign_id)


@router.post('/prospecting/connect')
async def connect(request: Request, csrf: str = Form(), user=Depends(require_admin)):
    check_form(request, user, csrf)
    origin = resolve_public_origin(request)
    if urlsplit(origin).scheme != 'https' or not unipile.api_origin():
        return notice('configuration')
    state = new_oauth_state()
    expiry = datetime.now(timezone.utc) + timedelta(minutes=15)
    async with get_pool().acquire() as conn:
        account = await connected_account(conn, user)
        await conn.execute('''INSERT INTO public.app_social_oauth_states
            (user_id, workspace_id, state_hash, provider, expires_at) VALUES ($1::uuid,$2::uuid,$3,$4,$5)''',
            user.id, user.active_workspace_id, oauth_state_hash(state), PROVIDER, expiry)
    payload = {
        'type': 'reconnect' if account else 'create', 'providers': ['LINKEDIN'],
        'api_url': unipile.api_origin(), 'expiresOn': expiry.isoformat(), 'name': state,
        'notify_url': origin + PAGE + '/notify', 'success_redirect_url': origin + PAGE + '?result=connecting',
        'failure_redirect_url': origin + PAGE + '?result=connect_failed',
    }
    if account:
        payload['reconnect_account'] = account['unipile_account_id']
    try:
        data = await unipile.request('POST', 'hosted/accounts/link', json=payload)
        url = data.get('url')
        parts = urlsplit(url) if isinstance(url, str) else None
        if parts and parts.scheme == 'https' and parts.netloc == 'account.unipile.com':
            return RedirectResponse(url, status_code=303)
    except (unipile.UnipileError, ValueError):
        pass
    return notice('connect_failed')


@router.post('/prospecting/notify', include_in_schema=False)
async def notify(event: ConnectionNotification):
    if event.status not in ('CREATION_SUCCESS', 'RECONNECTED') or not ACCOUNT_ID.fullmatch(event.account_id):
        return Response(status_code=204)
    state_hash = oauth_state_hash(event.name)
    async with get_pool().acquire() as conn:
        valid = await conn.fetchval('''SELECT EXISTS(SELECT 1 FROM public.app_social_oauth_states AS pending
            JOIN public.app_users AS owner ON owner.id=pending.user_id
            WHERE pending.state_hash=$1 AND pending.provider=$2 AND pending.expires_at>now()
              AND lower(owner.role)='admin' AND owner.is_active AND owner.deleted_at IS NULL)''', state_hash, PROVIDER)
    if not valid:
        return Response(status_code=204)
    try:
        account = await unipile.request('GET', f'accounts/{event.account_id}')
    except unipile.UnipileError:
        return Response(status_code=502)
    if account.get('type') != 'LINKEDIN' or account.get('id') != event.account_id:
        return Response(status_code=204)
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            state = await conn.fetchrow('''DELETE FROM public.app_social_oauth_states AS pending
                USING public.app_users AS owner
                WHERE pending.state_hash=$1 AND pending.provider=$2 AND pending.expires_at>now()
                  AND owner.id=pending.user_id AND lower(owner.role)='admin' AND owner.is_active AND owner.deleted_at IS NULL
                RETURNING pending.user_id, pending.workspace_id''',
                state_hash, PROVIDER)
            if state:
                name = str(account.get('name') or 'LinkedIn')[:250]
                if event.status == 'CREATION_SUCCESS':
                    await conn.execute('''INSERT INTO public.linkedin_prospecting_accounts
                        (user_id, workspace_id, unipile_account_id, display_name) VALUES ($1,$2,$3,$4)
                        ON CONFLICT DO NOTHING''', state['user_id'], state['workspace_id'], event.account_id, name)
                else:
                    await conn.execute('''UPDATE public.linkedin_prospecting_accounts SET display_name=$4
                        WHERE user_id=$1 AND workspace_id=$2 AND unipile_account_id=$3''',
                        state['user_id'], state['workspace_id'], event.account_id, name)
    return Response(status_code=204)


@router.post('/prospecting/disconnect')
async def disconnect(request: Request, csrf: str = Form(), user=Depends(require_admin)):
    check_form(request, user, csrf)
    async with get_pool().acquire() as conn:
        account = await connected_account(conn, user)
        if account:
            account_id = account['unipile_account_id']
            try:
                await unipile.request('DELETE', f'accounts/{account_id}')
            except unipile.UnipileError as exc:
                if exc.status != 404:
                    return notice('disconnect_failed')
            await conn.execute('''DELETE FROM public.linkedin_prospecting_accounts
                WHERE user_id=$1::uuid AND workspace_id=$2::uuid AND unipile_account_id=$3''',
                user.id, user.active_workspace_id, account_id)
    return notice('disconnected')


@router.post('/prospecting/send')
async def send(request: Request, csrf: str = Form(), submission_id: UUID = Form(),
               profile_urls: str = Form(max_length=6144), message: str = Form(max_length=3000),
               user=Depends(require_admin)):
    check_form(request, user, csrf)
    try:
        slugs = list(dict.fromkeys(unipile.profile_slug(line).casefold()
                                   for line in profile_urls.splitlines() if line.strip()))
    except ValueError:
        return notice('profile_invalid')
    if not slugs:
        return notice('profile_invalid')
    if len(slugs) > MAX_RECIPIENTS:
        return notice('too_many_profiles')
    message = message.strip()
    if not message:
        return notice('message_required')
    return await send_batch(user, submission_id, slugs, message)


@router.post('/prospecting/campaigns/{campaign_id}/send')
async def send_campaign(request: Request, campaign_id: UUID, csrf: str = Form(), submission_id: UUID = Form(),
                        message: str = Form(max_length=3000), slugs: list[str] = Form(default=[]),
                        user=Depends(require_admin)):
    check_form(request, user, csrf)
    slugs = list(dict.fromkeys(slugs))
    if not slugs:
        return notice('pick_contacts', campaign_id)
    if len(slugs) > MAX_RECIPIENTS:
        return notice('too_many_profiles', campaign_id)
    if not message.strip():
        return notice('message_required', campaign_id)
    async with get_pool().acquire() as conn:
        await owned_campaign(conn, user, campaign_id)
        eligible = await conn.fetch('''SELECT profile_slug FROM public.linkedin_prospecting_contacts
            WHERE campaign_id=$1 AND added_at IS NOT NULL AND profile_slug=ANY($2::text[])''', campaign_id, slugs)
    if len(eligible) != len(slugs):
        return notice('pick_contacts', campaign_id)
    return await send_batch(user, submission_id, slugs, message.strip(), campaign_id)


async def send_batch(user, submission_id, slugs, message, campaign_id=None):
    async with get_pool().acquire() as conn:
        account = await connected_account(conn, user)
        if not account:
            return notice('not_connected', campaign_id)
    processed = False
    for slug in slugs:
        recipient_submission = uuid5(submission_id, f'{user.id}:{user.active_workspace_id}:{campaign_id}:{slug}')
        async with get_pool().acquire() as conn:
            inserted = await conn.fetchval('''INSERT INTO public.linkedin_prospecting_messages
            (submission_id, user_id, workspace_id, profile_slug, status, campaign_id)
            VALUES ($1,$2::uuid,$3::uuid,$4,'pending',$5)
            ON CONFLICT DO NOTHING RETURNING submission_id''',
                recipient_submission, user.id, user.active_workspace_id, slug, campaign_id)
        if not inserted:
            continue
        processed = True
        status = await send_to_profile(account['unipile_account_id'], slug, message)
        async with get_pool().acquire() as conn:
            await conn.execute('''UPDATE public.linkedin_prospecting_messages SET status=$2 WHERE submission_id=$1''',
                               recipient_submission, status)
    return notice('batch_processed' if processed else 'already_submitted', campaign_id)


async def send_to_profile(account_id, slug, message):
    try:
        profile = await unipile.request('GET', f'users/{quote(slug, safe="")}', params={'account_id': account_id})
    except unipile.UnipileError:
        return 'failed'
    provider_id = profile.get('provider_id')
    if not isinstance(provider_id, str) or not provider_id.startswith('ACo'):
        return 'failed'
    try:
        sent = await unipile.request('POST', 'chats', files={
            'account_id': (None, account_id), 'attendees_ids': (None, provider_id), 'text': (None, message),
        })
    except unipile.UnipileError as exc:
        return 'failed' if exc.status in (400, 401, 403, 404, 409, 422, 429) else 'unknown'
    return 'sent' if sent.get('message_id') else 'unknown'
