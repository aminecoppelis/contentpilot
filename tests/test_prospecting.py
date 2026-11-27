import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import auth
from app.models.auth import AuthUser
from app.routers import prospecting
from app.services import unipile
from app.worker import prospecting_cron


def test_search_keeps_linkedin_results_when_both_ai_steps_fail():
    job = {'id': uuid4(), 'target': 'Responsable IA B2B', 'goal': 'Discovery call', 'offer': 'Assessment',
           'unipile_account_id': 'acc_example', 'search_keywords': '', 'search_locale': 'fr'}
    first = {'type': 'individual', 'public_identifier': 'contact-ia', 'display_name': 'Contact IA', 'description': 'Responsable IA'}
    second = {**first, 'public_identifier': 'contact-b2b', 'display_name': 'Contact B2B'}
    search = AsyncMock(side_effect=[{'data': [first], 'next_cursor': 'next'}, {'data': [first, second]}])
    state = AsyncMock(return_value=True)
    ai_error = prospecting.ai.AIGenerationError('Mock failure')
    with patch.object(prospecting_cron, 'set_search_state', state), \
         patch.object(unipile, 'search_contacts', search), \
         patch.object(prospecting.ai, 'prospecting_keywords', AsyncMock(side_effect=ai_error)), \
         patch.object(prospecting.ai, 'rank_prospecting_contacts', AsyncMock(side_effect=ai_error)), \
         patch.object(prospecting.ai, 'draft_prospecting_messages', AsyncMock(side_effect=[
             ai_error, [{'index': 0, 'text': 'Bonjour, échangeons sur votre équipe IA.'}],
         ])):
        asyncio.run(prospecting_cron.search_campaign(job))
    assert [call.kwargs['cursor'] for call in search.await_args_list] == [None, 'next']
    assert [call.args[1] for call in state.await_args_list] == [15, 25, 40, 50, 65, 100]
    assert state.await_args_list[1].kwargs['profiles'][0][1] == 'contact-ia'
    assert state.await_args_list[-2].kwargs['profiles'][0][-1] == 'Bonjour, échangeons sur votre équipe IA.'
    assert state.await_args.kwargs == {'status': 'done', 'result': 'matches_partial_hooks'}


def test_v2_links_an_existing_linkedin_account_with_the_server_key():
    user = AuthUser(id=str(uuid4()), active_workspace_id=str(uuid4()), email='test@example.com',
                    session_id='test-session', request_token='test-token', is_super_admin=True)
    conn = AsyncMock()
    conn.fetchval.return_value = 'acc_example'

    @asynccontextmanager
    async def acquire():
        yield conn

    app = FastAPI()
    app.include_router(prospecting.router, prefix='/app')
    app.dependency_overrides[prospecting.require_admin] = lambda: user

    def unipile_response(request):
        assert str(request.url) == 'https://api.unipile.com/v2/accounts/acc_example'
        assert request.headers['X-API-KEY'] == 'test-key'
        return httpx.Response(200, json={'id': 'acc_example', 'provider': 'linkedin', 'status': 'running', 'name': 'LinkedIn Test'})

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(unipile_response))
    settings = SimpleNamespace(unipile_dsn='', unipile_api_key='test-key')
    with TestClient(app) as client, patch.object(prospecting, 'form_token', return_value='test-csrf'), \
         patch.object(prospecting, 'get_pool', return_value=SimpleNamespace(acquire=acquire)), \
         patch.object(unipile, 'get_settings', return_value=settings), \
         patch.object(unipile.httpx, 'AsyncClient', return_value=upstream):
        response = client.post('/app/prospecting/attach', data={'csrf': 'test-csrf', 'account_id': 'acc_example'},
                               follow_redirects=False)
    assert response.headers['location'] == '/app/prospecting?result=attached'
    assert conn.fetchval.await_args.args[1:] == (user.id, user.active_workspace_id, 'acc_example', 'LinkedIn Test')


def test_prospecting_denies_direct_access_to_non_admins():
    user = AuthUser(id=str(uuid4()), active_workspace_id=str(uuid4()), email='test@example.com',
                    session_id='test-session', request_token='test-token')
    app = FastAPI()
    app.include_router(prospecting.router, prefix='/app')
    with TestClient(app) as client, patch.object(auth, 'require_auth', AsyncMock(return_value=user)), \
         patch.object(prospecting, 'get_pool') as pool:
        assert client.get('/app/prospecting').status_code == 403
        assert client.post('/app/prospecting/campaigns', data={
            'csrf': 'token', 'name': 'Campaign', 'target': 'Marketing',
        }).status_code == 403
        pool.assert_not_called()


def test_unipile_profile_url_is_normalized_without_fetching_the_input_url():
    assert unipile.profile_slug('https://www.linkedin.com/in/jean-test/?trk=example') == 'jean-test'
    for url in ('https://linkedin.com.example.org/in/jean', 'https://linkedin.com/in/jean%2Ftest',
                'https://linkedin.com/company/jean', 'http://linkedin.com/in/jean'):
        try:
            unipile.profile_slug(url)
        except ValueError:
            continue
        raise AssertionError(f'Unexpected valid URL: {url}')


def test_send_is_scoped_to_the_active_account_and_deduplicates_the_same_submission():
    user = AuthUser(id=str(uuid4()), active_workspace_id=str(uuid4()), email='test@example.com',
                    session_id='test-session', request_token='test-token', is_super_admin=True)
    conn = AsyncMock()
    conn.fetchrow.return_value = {'unipile_account_id': 'account_id', 'display_name': 'Test'}
    conn.fetchval.side_effect = [uuid4(), uuid4(), None, None]
    conn.fetch.return_value = []

    @asynccontextmanager
    async def acquire():
        yield conn

    conn.transaction = acquire
    app = FastAPI()
    app.include_router(prospecting.router, prefix='/app')
    app.dependency_overrides[prospecting.require_admin] = lambda: user
    api = AsyncMock(side_effect=[{'provider_id': 'ACoFirst'}, {'message_id': 'test-message'},
                                 {'provider_id': 'ACoSecond'}, unipile.UnipileError(504)])
    with TestClient(app) as client, patch.object(prospecting, 'form_token', return_value='test-csrf'), \
         patch.object(prospecting, 'get_pool', return_value=SimpleNamespace(acquire=acquire)), \
         patch.object(unipile, 'api_origin', return_value='https://api1.unipile.com:13111'), \
         patch.object(unipile, 'request', api):
        data = {'csrf': 'test-csrf', 'submission_id': str(uuid4()),
                'profile_urls': ('https://www.linkedin.com/in/jean-test/\n'
                                 'https://www.linkedin.com/in/marie-test/\n'
                                 'https://www.linkedin.com/in/JEAN-TEST/?trk=test'), 'message': 'Bonjour'}
        invalid = client.post('/app/prospecting/send', data={**data, 'csrf': 'invalid'}, follow_redirects=False)
        assert invalid.status_code == 403
        page = client.get('/app/prospecting?lang=fr')
        assert page.status_code == 200
        assert 'Nouvelle campagne' in page.text
        assert 'value="account_id"' not in page.text
        campaign_id = uuid4()
        conn.fetch.side_effect = [[{'id': campaign_id, 'name': 'IA B2B', 'search_status': 'running',
                                    'search_progress': 50, 'search_result': '', 'found': 12,
                                    'added': 2, 'sent': 1, 'failed': 0, 'review': 0}], []]
        dashboard = client.get('/app/prospecting?lang=fr')
        assert 'data-grid-view="prospecting_campaigns"' in dashboard.text
        assert f'/app/prospecting/campaigns/{campaign_id}' in dashboard.text
        assert 'data-stat="found">12' in dashboard.text
        assert 'data-stat="progress">50%' in dashboard.text
        response = client.post('/app/prospecting/send', data=data, follow_redirects=False)
        replay = client.post('/app/prospecting/send', data=data, follow_redirects=False)
    assert response.headers['location'] == '/app/prospecting?result=batch_processed'
    assert replay.headers['location'] == '/app/prospecting?result=already_submitted'
    assert api.await_count == 4
    assert conn.fetchrow.await_args.args[1:] == (user.id, user.active_workspace_id)
    assert api.await_args_list[0].kwargs['params'] == {'account_id': 'account_id'}
    assert [api.await_args_list[i].kwargs['files']['attendees_ids'] for i in (1, 3)] == [
        (None, 'ACoFirst'), (None, 'ACoSecond'),
    ]
    assert [call.args[-1] for call in conn.execute.await_args_list] == ['sent', 'unknown']


def test_campaign_suggestions_use_real_profiles_and_only_added_contacts_can_be_sent():
    campaign_id = uuid4()
    user = AuthUser(id=str(uuid4()), active_workspace_id=str(uuid4()), email='test@example.com',
                    session_id='test-session', request_token='test-token', is_super_admin=True)
    account = {'unipile_account_id': 'account_id', 'display_name': 'Sender'}
    campaign = {'id': campaign_id, 'name': 'Campaign', 'target': 'SaaS marketing leads',
                'goal': 'Discovery call', 'offer': 'Workflow assessment', 'search_status': 'done',
                'search_progress': 100, 'search_result': 'matches_ready', 'found': 2}
    conn = AsyncMock()
    conn.fetchrow.side_effect = [campaign, account, account, campaign, campaign, campaign, campaign,
                                 campaign, account, account, campaign]
    conn.fetchval.return_value = campaign_id
    conn.execute.return_value = 'UPDATE 1'
    prospect = {'profile_slug': 'jean-test', 'display_name': 'Jean Test', 'headline': 'Marketing',
                'location': 'Paris', 'reason': 'Matching role', 'relevance': 90, 'status': None,
                'draft_message': 'A personalized opening'}
    conn.fetch.side_effect = [[campaign], [{**prospect, 'added_at': None},
                                         {**prospect, 'profile_slug': 'marie-test', 'display_name': 'Marie Test',
                                          'added_at': datetime.now(timezone.utc)}], [], [], [{'profile_slug': 'marie-test'}],
                              [{**prospect, 'profile_slug': 'marie-test'}], [], []]

    @asynccontextmanager
    async def acquire():
        yield conn

    app = FastAPI()
    app.include_router(prospecting.router, prefix='/app')
    app.dependency_overrides[prospecting.require_admin] = lambda: user
    search = AsyncMock(return_value={'data': [
        {'type': 'individual', 'profile_url': 'https://www.linkedin.com/in/jean-test',
         'display_name': 'Jean Test', 'description': 'Marketing', 'specifics': {'linkedin': {'location': 'Paris'}}},
        {'type': 'individual', 'profile_url': 'https://example.com/in/fake', 'display_name': 'Untrusted profile'},
    ]})
    ranking = AsyncMock(return_value=[{'index': 0, 'score': 90, 'reason': 'Matching role'},
                                      {'index': 9, 'score': 100, 'reason': 'Invented profile'}])
    send = AsyncMock(return_value=prospecting.notice('batch_processed', campaign_id))
    message_drafts = AsyncMock(return_value=[{'index': 0, 'text': 'Hello Marie, I noticed your experience.'}])
    campaign_draft = AsyncMock(return_value={key: campaign[key] for key in ('name', 'target', 'goal', 'offer')})
    base = f'/app/prospecting/campaigns/{campaign_id}'
    form = {'csrf': 'test-csrf'}
    with TestClient(app) as client, patch.object(prospecting, 'form_token', return_value='test-csrf'), \
         patch.object(prospecting, 'get_pool', return_value=SimpleNamespace(acquire=acquire)), \
         patch.object(unipile, 'api_origin', return_value='https://api1.unipile.com:13111'), \
         patch.object(unipile, 'search_contacts', search), \
         patch.object(prospecting.ai, 'prospecting_keywords', AsyncMock(return_value='Marketing')), \
         patch.object(prospecting.ai, 'rank_prospecting_contacts', ranking), \
         patch.object(prospecting.ai, 'draft_prospecting_campaign', campaign_draft), \
         patch.object(prospecting.ai, 'draft_prospecting_messages', message_drafts), \
         patch.object(unipile, 'get_profile', AsyncMock(return_value={'first_name': 'Marie', 'description': 'B2B strategy'})), \
         patch.object(prospecting, 'send_batch', send):
        created = client.post('/app/prospecting/campaigns', data={**form, 'name': 'Campaign', 'target': campaign['target']}, follow_redirects=False)
        assert 'result=campaign_created' in created.headers['location']
        searched = client.post(base + '/search', data=form, follow_redirects=False)
        assert 'result=search_queued' in searched.headers['location']
        page = client.get(f'{base}?lang=en')
        assert page.status_code == 200
        assert all(label in page.text for label in ('Suggested profiles', 'Campaign contacts', 'Jean Test', 'Marie Test', 'A personalized opening'))
        assert 'name="message:jean-test"' in page.text
        assert 'name="message:marie-test"' in page.text
        added = client.post(base + '/contacts', data={**form, 'slugs': 'marie-test', 'message:marie-test': 'Edited when adding'}, follow_redirects=False)
        assert 'result=contacts_added' in added.headers['location']
        message = {**form, 'submission_id': str(uuid4()), 'message:jean-test': 'Hello Jean', 'message:marie-test': 'Hello Marie'}
        rejected = client.post(base + '/send', data={**message, 'slugs': 'jean-test'}, follow_redirects=False)
        assert 'result=pick_contacts' in rejected.headers['location']
        accepted = client.post(base + '/send', data={**message, 'slugs': 'marie-test'}, follow_redirects=False)
        assert 'result=batch_processed' in accepted.headers['location']
        drafted = client.post(base + '/draft-messages', data={**form, 'slugs': 'marie-test'}, follow_redirects=False)
        assert 'result=message_drafts_ready' in drafted.headers['location']
        brief = client.post('/app/prospecting/campaigns/draft', data={
            **form, 'target': campaign['target'], 'goal': campaign['goal'], 'offer': campaign['offer'],
        })
        assert brief.status_code == 200
        assert 'Workflow assessment' in brief.text
        saved = client.post(base + '/save-message', data={**form, 'single': 'jean-test', 'message:jean-test': 'Edited opening'},
                            follow_redirects=False)
        assert 'result=message_saved' in saved.headers['location']
    assert any(call.args[1:] == (campaign_id, ['marie-test'], ['Edited when adding']) for call in conn.execute.await_args_list)
    assert conn.execute.await_args.args[1:] == (campaign_id, 'jean-test', 'Edited opening')
    search.assert_not_awaited()
    assert conn.executemany.await_args.args[1] == [(campaign_id, 'marie-test', 'Hello Marie, I noticed your experience.')]
    assert message_drafts.await_args.args[1] == [{'index': 0, 'first_name': 'Marie', 'headline': 'B2B strategy', 'location': 'Paris'}]
    send.assert_awaited_once()
    assert send.await_args.args[-3:] == (['marie-test'], {'marie-test': 'Hello Marie'}, campaign_id)
