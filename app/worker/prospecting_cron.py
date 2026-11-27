"""Durable background discovery and AI hooks for LinkedIn campaigns."""
import asyncio
import logging
import re
from uuid import uuid4

import httpx

from app.database import get_pool
from app.services import ai, unipile

logger = logging.getLogger(__name__)
MAX_PAGES = 3
AI_ERRORS = (ai.AIGenerationError, httpx.HTTPError, asyncio.TimeoutError)


def real_profiles(data):
    profiles = {}
    items = data.get('items')
    if not isinstance(items, list):
        items = data.get('data')
    if not isinstance(items, list):
        return []
    for item in items:
        if not isinstance(item, dict) or item.get('type') not in (None, 'PEOPLE', 'individual'):
            continue
        identifier = item.get('public_identifier')
        url = item.get('public_profile_url') or item.get('profile_url')
        try:
            slug = unipile.profile_slug(url if isinstance(url, str) else '').casefold()
        except ValueError:
            if not isinstance(identifier, str) or not re.fullmatch(r'[\w-]{1,160}', identifier):
                continue
            slug = identifier.casefold()
        specifics = item.get('specifics') or {}
        linkedin = (specifics.get('linkedin') or specifics) if isinstance(specifics, dict) else {}
        location = item.get('location') or (linkedin.get('location') if isinstance(linkedin, dict) else '')
        fields = {'name': str(item.get('name') or item.get('display_name') or '')[:250],
                  'first_name': str(item.get('first_name') or '')[:120],
                  'headline': str(item.get('headline') or item.get('description') or '')[:400],
                  'location': location[:200] if isinstance(location, str) else '', 'photo_url': unipile.linkedin_photo(item)}
        profiles.setdefault(slug, fields)
        if len(profiles) == 10:
            break
    return list(profiles.items())


async def set_search_state(job, progress, *, status='running', result='', profiles=()):
    async with get_pool().acquire() as conn, conn.transaction():
        updated = await conn.execute('''UPDATE public.linkedin_prospecting_campaigns
            SET search_progress=$3, search_status=$4, search_result=$5,
                search_lease=CASE WHEN $4='running' THEN search_lease ELSE NULL END
            WHERE id=$1 AND search_lease=$2''', job['id'], job['search_lease'], progress, status, result)
        if updated == 'UPDATE 0':
            return False
        if profiles:
            await conn.executemany('''INSERT INTO public.linkedin_prospecting_contacts AS contact
                (campaign_id, profile_slug, display_name, headline, location, reason, relevance, draft_message, photo_url)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT (campaign_id,profile_slug) DO UPDATE SET
                display_name=EXCLUDED.display_name, headline=EXCLUDED.headline, location=EXCLUDED.location,
                photo_url=COALESCE(NULLIF(EXCLUDED.photo_url, ''), contact.photo_url),
                reason=CASE WHEN EXCLUDED.reason='' THEN contact.reason ELSE EXCLUDED.reason END,
                relevance=CASE WHEN EXCLUDED.reason='' THEN contact.relevance ELSE EXCLUDED.relevance END,
                draft_message=CASE WHEN contact.draft_message='' THEN EXCLUDED.draft_message ELSE contact.draft_message END''', profiles)
        return True


def contact_rows(job, profiles, ranks=None, hooks=None):
    ranks, hooks = ranks or {}, hooks or {}
    return [(job['id'], slug, fields['name'] or slug, fields['headline'], fields['location'],
             *ranks.get(i, ('', 0)), hooks.get(i, ''), fields['photo_url']) for i, (slug, fields) in enumerate(profiles)]


async def analyse_contacts(job, profiles):
    summaries = [{'index': i, 'headline': fields['headline'], 'location': fields['location']}
                 for i, (_, fields) in enumerate(profiles)]
    brief = {key: job[key] for key in ('target', 'goal', 'offer')}
    message_profiles = [{**summary, 'first_name': fields['first_name']}
                        for summary, (_, fields) in zip(summaries, profiles)]
    ranking, drafts = await asyncio.gather(
        asyncio.wait_for(ai.rank_prospecting_contacts(job['target'], summaries, job['search_locale']), timeout=20),
        asyncio.wait_for(ai.draft_prospecting_messages(brief, message_profiles, job['search_locale']), timeout=35),
        return_exceptions=True,
    )
    ranks, hooks = {}, {}
    for result in (ranking, drafts):
        if isinstance(result, BaseException) and not isinstance(result, AI_ERRORS):
            raise result
    for match in ranking if isinstance(ranking, list) else []:
        if not isinstance(match, dict):
            continue
        i, score, reason = match.get('index'), match.get('score'), match.get('reason')
        if (type(i) is int and 0 <= i < len(profiles) and type(score) is int and 0 <= score <= 100
                and isinstance(reason, str) and reason.strip()):
            ranks.setdefault(i, (reason.strip()[:500], score))
    for message in drafts if isinstance(drafts, list) else []:
        if not isinstance(message, dict):
            continue
        i, text = message.get('index'), message.get('text')
        if type(i) is int and 0 <= i < len(profiles) and isinstance(text, str) and 0 < len(text.strip()) <= 3000:
            hooks.setdefault(i, text.strip())
    return ranks, hooks


async def search_campaign(job):
    if not job['unipile_account_id']:
        await set_search_state(job, 0, status='failed', result='not_connected')
        return
    keywords = job['search_keywords']
    if not keywords:
        try:
            keywords = await asyncio.wait_for(ai.prospecting_keywords(job['target']), timeout=8)
        except AI_ERRORS:
            keywords = job['target'][:220]
    if not await set_search_state(job, 15):
        return
    cursor, seen, incomplete = None, set(), False
    for page in range(MAX_PAGES):
        try:
            data = await asyncio.wait_for(unipile.search_contacts(job['unipile_account_id'], keywords, cursor=cursor), timeout=22)
        except (unipile.UnipileError, asyncio.TimeoutError) as exc:
            status = getattr(exc, 'status', None)
            result = {401: 'search_account_error', 403: 'search_account_error', 404: 'search_account_error',
                      429: 'search_rate_limited', None: 'search_timeout'}.get(status, 'search_failed')
            await set_search_state(job, 100 if seen else 0, status='done' if seen else 'failed', result=result)
            return
        if not isinstance(data.get('items'), list) and not isinstance(data.get('data'), list):
            await set_search_state(job, 100 if seen else 0, status='done' if seen else 'failed', result='search_unusable')
            return
        profiles = [(slug, fields) for slug, fields in real_profiles(data) if slug not in seen]
        if profiles:
            seen.update(slug for slug, _ in profiles)
            if not await set_search_state(job, 25 + page * 25, profiles=contact_rows(job, profiles)):
                return
            ranks, hooks = await analyse_contacts(job, profiles)
            incomplete |= len(hooks) < len(profiles)
            if not await set_search_state(job, 40 + page * 25, profiles=contact_rows(job, profiles, ranks, hooks)):
                return
        next_cursor = data.get('next_cursor') or data.get('cursor')
        if not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
    result = ('matches_partial_hooks' if incomplete else 'matches_ready') if seen else 'no_matches'
    await set_search_state(job, 100, status='done', result=result)


async def run_prospecting_cycle():
    async with get_pool().acquire() as conn:
        job = await conn.fetchrow('''WITH next_campaign AS (
            SELECT c.id FROM public.linkedin_prospecting_campaigns c
            WHERE c.search_status='queued' OR (c.search_status='running'
                AND c.search_started_at < now() - interval '8 minutes')
            ORDER BY c.created_at LIMIT 1 FOR UPDATE SKIP LOCKED
        ), claimed AS (
            UPDATE public.linkedin_prospecting_campaigns c SET search_status='running', search_progress=5,
                search_lease=$1, search_started_at=now() FROM next_campaign n WHERE c.id=n.id RETURNING c.*
        ) SELECT c.*, a.unipile_account_id FROM claimed c
          LEFT JOIN public.app_users u ON u.id=c.user_id AND lower(u.role)='admin'
              AND u.is_active AND u.deleted_at IS NULL
          LEFT JOIN public.linkedin_prospecting_accounts a ON a.user_id=u.id AND a.workspace_id=c.workspace_id''', uuid4())
    if job:
        try:
            await search_campaign(job)
        except Exception:
            logger.exception('Background LinkedIn search failed for campaign %s', job['id'])
            await set_search_state(job, 0, status='failed', result='search_failed')


