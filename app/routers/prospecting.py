"""LinkedIn account linking and outreach from SocialAI."""
import asyncio
import hmac
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit
from uuid import UUID, uuid4, uuid5

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from app.config import get_settings
from app.database import get_pool
from app.dependencies.auth import require_admin
from app.i18n import resolve_locale, translate
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
    location = f'{PAGE}/campaigns/{campaign_id}' if campaign_id else PAGE
    location += '?' + urlencode({'result': status})
    return RedirectResponse(location, status_code=303)


async def connected_account(conn, user):
    return await conn.fetchrow('''SELECT unipile_account_id, display_name
        FROM public.linkedin_prospecting_accounts WHERE user_id=$1::uuid AND workspace_id=$2::uuid''',
        user.id, user.active_workspace_id)


async def owned_campaign(conn, user, campaign_id):
    campaign = await conn.fetchrow('''SELECT id, name, target, goal, offer, search_status, search_progress, search_result
        FROM public.linkedin_prospecting_campaigns
        WHERE id=$1 AND user_id=$2::uuid AND workspace_id=$3::uuid''', campaign_id, user.id, user.active_workspace_id)
    if not campaign:
        raise HTTPException(404)
    return campaign


@router.get('/prospecting', response_class=HTMLResponse)
async def index(request: Request, result: str = '', campaign_id: UUID | None = None, user=Depends(require_admin)):
    if campaign_id:
        return notice(result, campaign_id)
    return await render_page(request, user, result)


@router.get('/prospecting/campaigns/new', response_class=HTMLResponse)
async def new_campaign(request: Request, user=Depends(require_admin)):
    return await render_page(request, user, '', view='new')


@router.get('/prospecting/campaigns/{campaign_id}', response_class=HTMLResponse)
async def campaign_detail(request: Request, campaign_id: UUID, result: str = '', user=Depends(require_admin)):
    return await render_page(request, user, result, campaign_id, view='detail')


async def campaign_statistics(conn, user, campaign_id=None):
    return await conn.fetch('''SELECT c.id, c.name, c.search_status, c.search_progress, c.search_result,
        count(p.profile_slug)::int AS found, count(p.added_at)::int AS added,
        count(*) FILTER (WHERE delivery.status='sent')::int AS sent,
        count(*) FILTER (WHERE delivery.status='failed')::int AS failed,
        count(*) FILTER (WHERE delivery.status IN ('pending','unknown'))::int AS review
        FROM public.linkedin_prospecting_campaigns c
        LEFT JOIN public.linkedin_prospecting_contacts p ON p.campaign_id=c.id
        LEFT JOIN LATERAL (SELECT m.status FROM public.linkedin_prospecting_messages m
            WHERE m.campaign_id=p.campaign_id AND m.profile_slug=p.profile_slug
            ORDER BY m.created_at DESC LIMIT 1) delivery ON true
        WHERE c.user_id=$1::uuid AND c.workspace_id=$2::uuid AND ($3::uuid IS NULL OR c.id=$3)
        GROUP BY c.id ORDER BY c.created_at DESC, c.id DESC''', user.id, user.active_workspace_id, campaign_id)


@router.get('/prospecting/progress', response_class=JSONResponse)
async def search_progress(request: Request, campaign_id: UUID | None = None, user=Depends(require_admin)):
    async with get_pool().acquire() as conn:
        rows = await campaign_statistics(conn, user, campaign_id)
    if campaign_id and not rows:
        raise HTTPException(404)
    response = []
    for row in rows:
        entry = dict(row)
        entry['id'] = str(row['id'])
        entry['status_label'] = translate('prospecting.search_status.' + row['search_status'], resolve_locale(request))
        entry['result_label'] = translate('prospecting.result.' + row['search_result'], resolve_locale(request)) if row['search_result'] else ''
        response.append(entry)
    return JSONResponse(response, headers={'Cache-Control': 'no-store'})


async def render_page(request, user, result, campaign_id=None, brief=None, view='list'):
    async with get_pool().acquire() as conn:
        account = await connected_account(conn, user)
        campaigns = await campaign_statistics(conn, user, campaign_id) if view != 'new' else []
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
        'configured': bool(unipile.api_origin()), 'unipile_v2': unipile.uses_v2(),
        'csrf': form_token(request, user), 'submission_id': uuid4(),
        'result': result, 'max_recipients': MAX_RECIPIENTS,
        'campaigns': campaigns, 'campaign': campaign, 'contacts': contacts,
        'brief': brief or {},
        'view': view,
    }, headers={'Cache-Control': 'no-store'})

@router.post('/prospecting/campaigns/draft')
async def draft_campaign(request: Request, csrf: str = Form(), name: str = Form(default='', max_length=120),
                         target: str = Form(default='', max_length=1200), goal: str = Form(default='', max_length=1200),
                         offer: str = Form(default='', max_length=1200), user=Depends(require_admin)):
    check_form(request, user, csrf)
    brief = {'name': name.strip(), 'target': target.strip(), 'goal': goal.strip(), 'offer': offer.strip()}
    if not all(brief[key] for key in ('target', 'goal', 'offer')):
        return await render_page(request, user, 'brief_required', brief=brief, view='new')
    try:
        draft = await asyncio.wait_for(ai.draft_prospecting_campaign(brief, resolve_locale(request)), timeout=45)
    except (ai.AIGenerationError, httpx.HTTPError, asyncio.TimeoutError):
        return await render_page(request, user, 'draft_failed', brief=brief, view='new')
    return await render_page(request, user, 'campaign_draft_ready', brief=draft, view='new')


@router.post('/prospecting/campaigns')
async def create_campaign(request: Request, csrf: str = Form(), name: str = Form(max_length=120),
                          target: str = Form(max_length=1200), goal: str = Form(default='', max_length=1200),
                          offer: str = Form(default='', max_length=1200), user=Depends(require_admin)):
    check_form(request, user, csrf)
    if not name.strip() or not target.strip():
        return notice('campaign_required')
    async with get_pool().acquire() as conn:
        campaign_id = await conn.fetchval('''INSERT INTO public.linkedin_prospecting_campaigns
            (user_id, workspace_id, name, target, goal, offer, search_status, search_locale)
            VALUES ($1::uuid,$2::uuid,$3,$4,$5,$6,
                CASE WHEN $7::boolean AND EXISTS (SELECT 1 FROM public.linkedin_prospecting_accounts
                    WHERE user_id=$1::uuid AND workspace_id=$2::uuid) THEN 'queued' ELSE 'idle' END,$8) RETURNING id''',
            user.id, user.active_workspace_id, name.strip(), target.strip(), goal.strip(), offer.strip(),
            bool(unipile.api_origin()), resolve_locale(request))
    return notice('campaign_created')


@router.post('/prospecting/campaigns/{campaign_id}/brief')
async def update_campaign_brief(request: Request, campaign_id: UUID, csrf: str = Form(),
                               target: str = Form(max_length=1200), goal: str = Form(max_length=1200),
                               offer: str = Form(max_length=1200), user=Depends(require_admin)):
    check_form(request, user, csrf)
    brief = [value.strip() for value in (target, goal, offer)]
    if not all(brief):
        return notice('brief_required', campaign_id)
    async with get_pool().acquire() as conn:
        await owned_campaign(conn, user, campaign_id)
        await conn.execute('''UPDATE public.linkedin_prospecting_campaigns SET target=$2, goal=$3, offer=$4
            WHERE id=$1 AND user_id=$5::uuid AND workspace_id=$6::uuid''',
            campaign_id, *brief, user.id, user.active_workspace_id)
    return notice('brief_saved', campaign_id)


@router.post('/prospecting/campaigns/{campaign_id}/search')
async def search_campaign(request: Request, campaign_id: UUID, csrf: str = Form(),
                          keywords: str = Form(default='', max_length=220), user=Depends(require_admin)):
    check_form(request, user, csrf)
    async with get_pool().acquire() as conn:
        await owned_campaign(conn, user, campaign_id)
        if not await connected_account(conn, user):
            return notice('not_connected', campaign_id)
        await conn.execute('''UPDATE public.linkedin_prospecting_campaigns
            SET search_status='queued', search_progress=0, search_result='', search_keywords=$2, search_locale=$3
            WHERE id=$1 AND search_status NOT IN ('queued','running')''', campaign_id, keywords.strip(), resolve_locale(request))
    return notice('search_queued', campaign_id)


@router.post('/prospecting/campaigns/{campaign_id}/contacts')
async def add_contacts(request: Request, campaign_id: UUID, csrf: str = Form(),
                       slugs: list[str] = Form(default=[]), single: str = Form(default='', max_length=160),
                       user=Depends(require_admin)):
    check_form(request, user, csrf)
    async with get_pool().acquire() as conn:
        await owned_campaign(conn, user, campaign_id)
        updated = await conn.execute('''UPDATE public.linkedin_prospecting_contacts SET added_at=now()
            WHERE campaign_id=$1 AND added_at IS NULL AND profile_slug=ANY($2::text[])''',
            campaign_id, [single] if single else slugs)
    return notice('contacts_added' if updated != 'UPDATE 0' else 'pick_contacts', campaign_id)


@router.post('/prospecting/campaigns/{campaign_id}/draft-messages')
async def draft_messages(request: Request, campaign_id: UUID, csrf: str = Form(),
                         slugs: list[str] = Form(default=[]), user=Depends(require_admin)):
    check_form(request, user, csrf)
    slugs = list(dict.fromkeys(slugs))
    if not slugs:
        return notice('pick_contacts', campaign_id)
    if len(slugs) > MAX_RECIPIENTS:
        return notice('too_many_profiles', campaign_id)
    async with get_pool().acquire() as conn:
        campaign = await owned_campaign(conn, user, campaign_id)
        account = await connected_account(conn, user)
        contacts = await conn.fetch('''SELECT profile_slug, display_name, headline, location
            FROM public.linkedin_prospecting_contacts WHERE campaign_id=$1 AND added_at IS NOT NULL
              AND profile_slug=ANY($2::text[]) ORDER BY profile_slug''', campaign_id, slugs)
    if not account:
        return notice('not_connected', campaign_id)
    if len(contacts) != len(slugs):
        return notice('pick_contacts', campaign_id)
    if not campaign['goal'] or not campaign['offer']:
        return notice('brief_required', campaign_id)

    async def describe(contact):
        profile = {}
        try:
            profile = await unipile.get_profile(account['unipile_account_id'], contact['profile_slug'])
        except unipile.UnipileError:
            pass
        return {
            'first_name': str(profile.get('first_name') or '')[:120],
            'headline': str(profile.get('headline') or profile.get('description') or contact['headline'])[:400],
            'location': str(contact['location'])[:160],
        }

    profiles = await asyncio.gather(*(describe(contact) for contact in contacts))
    brief = {key: campaign[key] for key in ('target', 'goal', 'offer')}
    try:
        generated = await asyncio.wait_for(ai.draft_prospecting_messages(
            brief, [{'index': i, **profile} for i, profile in enumerate(profiles)], resolve_locale(request)), timeout=50)
    except (ai.AIGenerationError, httpx.HTTPError, asyncio.TimeoutError):
        return notice('draft_failed', campaign_id)
    drafts = {}
    for item in generated:
        if not isinstance(item, dict):
            continue
        i, message = item.get('index'), item.get('text')
        if type(i) is int and 0 <= i < len(contacts) and isinstance(message, str) and 0 < len(message.strip()) <= 3000:
            drafts.setdefault(contacts[i]['profile_slug'], message.strip())
    if len(drafts) != len(contacts):
        return notice('draft_failed', campaign_id)
    async with get_pool().acquire() as conn:
        await conn.executemany('''UPDATE public.linkedin_prospecting_contacts AS contact SET draft_message=$3
            WHERE campaign_id=$1 AND profile_slug=$2 AND added_at IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM public.linkedin_prospecting_messages AS delivery
                WHERE delivery.campaign_id=contact.campaign_id AND delivery.profile_slug=contact.profile_slug
                  AND delivery.status IN ('pending', 'sent', 'unknown')
            )''',
            [(campaign_id, slug, message) for slug, message in drafts.items()])
    return notice('message_drafts_ready', campaign_id)


@router.post('/prospecting/connect')
async def connect(request: Request, csrf: str = Form(), user=Depends(require_admin)):
    check_form(request, user, csrf)
    origin = resolve_public_origin(request)
    if urlsplit(origin).scheme != 'https' or not unipile.api_origin() or unipile.uses_v2():
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


@router.post('/prospecting/attach')
async def attach(request: Request, csrf: str = Form(), account_id: str = Form(max_length=128),
                 user=Depends(require_admin)):
    check_form(request, user, csrf)
    if not unipile.uses_v2():
        return notice('configuration')
    account_id = account_id.strip()
    if not unipile.V2_ACCOUNT_ID.fullmatch(account_id):
        return notice('account_id_invalid')
    try:
        account = await unipile.request('GET', f'accounts/{account_id}')
    except unipile.UnipileError:
        return notice('attach_failed')
    if (account.get('id') != account_id or account.get('provider') != 'linkedin'
            or account.get('is_locked') or account.get('status') not in ('running', 'partial', 'degraded')):
        return notice('attach_failed')
    async with get_pool().acquire() as conn:
        inserted = await conn.fetchval('''INSERT INTO public.linkedin_prospecting_accounts
            (user_id, workspace_id, unipile_account_id, display_name) VALUES ($1::uuid,$2::uuid,$3,$4)
            ON CONFLICT DO NOTHING RETURNING unipile_account_id''',
            user.id, user.active_workspace_id, account_id, str(account.get('name') or 'LinkedIn')[:250])
    return notice('attached' if inserted else 'account_already_linked')


@router.post('/prospecting/notify', include_in_schema=False)
async def notify(event: ConnectionNotification):
    if unipile.uses_v2() or event.status not in ('CREATION_SUCCESS', 'RECONNECTED') or not ACCOUNT_ID.fullmatch(event.account_id):
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
            if not unipile.uses_v2() and not unipile.V2_ACCOUNT_ID.fullmatch(account_id):
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
                        slugs: list[str] = Form(default=[]),
                        user=Depends(require_admin)):
    check_form(request, user, csrf)
    slugs = list(dict.fromkeys(slugs))
    if not slugs:
        return notice('pick_contacts', campaign_id)
    if len(slugs) > MAX_RECIPIENTS:
        return notice('too_many_profiles', campaign_id)
    form = await request.form()
    messages = {}
    for slug in slugs:
        text = form.get(f'message:{slug}')
        if not isinstance(text, str) or not 0 < len(text.strip()) <= 3000:
            return notice('personalized_messages_required', campaign_id)
        messages[slug] = text.strip()
    async with get_pool().acquire() as conn:
        await owned_campaign(conn, user, campaign_id)
        eligible = await conn.fetch('''SELECT profile_slug FROM public.linkedin_prospecting_contacts
            WHERE campaign_id=$1 AND added_at IS NOT NULL AND profile_slug=ANY($2::text[])''', campaign_id, slugs)
    if len(eligible) != len(slugs):
        return notice('pick_contacts', campaign_id)
    return await send_batch(user, submission_id, slugs, messages, campaign_id)


async def send_batch(user, submission_id, slugs, message, campaign_id=None):
    async with get_pool().acquire() as conn:
        account = await connected_account(conn, user)
        if not account:
            return notice('not_connected', campaign_id)
    processed = False
    for slug in slugs:
        recipient_submission = uuid5(submission_id, f'{user.id}:{user.active_workspace_id}:{campaign_id}:{slug}')
        text = message[slug] if isinstance(message, dict) else message
        async with get_pool().acquire() as conn, conn.transaction():
            inserted = await conn.fetchval('''INSERT INTO public.linkedin_prospecting_messages
            (submission_id, user_id, workspace_id, profile_slug, status, campaign_id)
            VALUES ($1,$2::uuid,$3::uuid,$4,'pending',$5)
            ON CONFLICT DO NOTHING RETURNING submission_id''',
                recipient_submission, user.id, user.active_workspace_id, slug, campaign_id)
            if inserted and campaign_id:
                await conn.execute('''UPDATE public.linkedin_prospecting_contacts SET draft_message=$3
                    WHERE campaign_id=$1 AND profile_slug=$2''', campaign_id, slug, text)
        if not inserted:
            continue
        processed = True
        status = await send_to_profile(account['unipile_account_id'], slug, text)
        async with get_pool().acquire() as conn:
            await conn.execute('''UPDATE public.linkedin_prospecting_messages SET status=$2 WHERE submission_id=$1''',
                               recipient_submission, status)
    return notice('batch_processed' if processed else 'already_submitted', campaign_id)


async def send_to_profile(account_id, slug, message):
    try:
        profile = await unipile.get_profile(account_id, slug)
    except unipile.UnipileError:
        return 'failed'
    provider_id = profile.get('provider_id') or profile.get('id')
    if not isinstance(provider_id, str) or not provider_id.startswith(('ACo', 'ADo')):
        return 'failed'
    try:
        sent = await unipile.send_message(account_id, provider_id, message)
    except unipile.UnipileError as exc:
        return 'failed' if exc.status in (400, 401, 403, 404, 409, 422, 429) else 'unknown'
    return 'sent' if sent.get('message_id') else 'unknown'
