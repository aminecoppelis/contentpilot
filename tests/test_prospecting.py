from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import auth
from app.models.auth import AuthUser
from app.routers import prospecting
from app.services import unipile


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
        assert 'Créer la campagne' in page.text
        assert 'value="account_id"' not in page.text
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
    campaign = {'id': campaign_id, 'name': 'Campaign', 'target': 'SaaS marketing leads'}
    conn = AsyncMock()
    conn.fetchrow.side_effect = [campaign, account, account, campaign, campaign, campaign, campaign]
    conn.fetchval.return_value = campaign_id
    conn.execute.return_value = 'UPDATE 1'
    prospect = {'profile_slug': 'jean-test', 'display_name': 'Jean Test', 'headline': 'Marketing',
                'location': 'Paris', 'reason': 'Matching role', 'relevance': 90, 'status': None}
    conn.fetch.side_effect = [[campaign], [{**prospect, 'added_at': None},
                                         {**prospect, 'profile_slug': 'marie-test', 'display_name': 'Marie Test',
                                          'added_at': datetime.now(timezone.utc)}], [], [], [{'profile_slug': 'marie-test'}]]

    @asynccontextmanager
    async def acquire():
        yield conn

    app = FastAPI()
    app.include_router(prospecting.router, prefix='/app')
    app.dependency_overrides[prospecting.require_admin] = lambda: user
    search = AsyncMock(return_value={'items': [
        {'type': 'PEOPLE', 'public_profile_url': 'https://www.linkedin.com/in/jean-test',
         'name': 'Jean Test', 'headline': 'Marketing', 'location': 'Paris'},
        {'type': 'PEOPLE', 'public_profile_url': 'https://example.com/in/fake', 'name': 'Untrusted profile'},
    ]})
    ranking = AsyncMock(return_value=[{'index': 0, 'score': 90, 'reason': 'Matching role'},
                                      {'index': 9, 'score': 100, 'reason': 'Invented profile'}])
    send = AsyncMock(return_value=prospecting.notice('batch_processed', campaign_id))
    base = f'/app/prospecting/campaigns/{campaign_id}'
    form = {'csrf': 'test-csrf'}
    with TestClient(app) as client, patch.object(prospecting, 'form_token', return_value='test-csrf'), \
         patch.object(prospecting, 'get_pool', return_value=SimpleNamespace(acquire=acquire)), \
         patch.object(unipile, 'api_origin', return_value='https://api1.unipile.com:13111'), \
         patch.object(unipile, 'search_contacts', search), \
         patch.object(prospecting.ai, 'prospecting_keywords', AsyncMock(return_value='Marketing')), \
         patch.object(prospecting.ai, 'rank_prospecting_contacts', ranking), \
         patch.object(prospecting, 'send_batch', send):
        created = client.post('/app/prospecting/campaigns', data={**form, 'name': 'Campaign', 'target': campaign['target']}, follow_redirects=False)
        assert 'result=campaign_created' in created.headers['location']
        searched = client.post(base + '/search', data=form, follow_redirects=False)
        assert 'result=matches_ready' in searched.headers['location']
        page = client.get(f'/app/prospecting?campaign_id={campaign_id}&lang=en')
        assert page.status_code == 200
        assert all(label in page.text for label in ('Suggested profiles', 'Campaign contacts', 'Jean Test', 'Marie Test'))
        added = client.post(base + '/contacts', data={**form, 'slugs': 'marie-test'}, follow_redirects=False)
        assert 'result=contacts_added' in added.headers['location']
        message = {**form, 'submission_id': str(uuid4()), 'message': 'Hello'}
        rejected = client.post(base + '/send', data={**message, 'slugs': 'jean-test'}, follow_redirects=False)
        assert 'result=pick_contacts' in rejected.headers['location']
        accepted = client.post(base + '/send', data={**message, 'slugs': 'marie-test'}, follow_redirects=False)
        assert 'result=batch_processed' in accepted.headers['location']
    assert conn.executemany.await_args.args[1] == [(campaign_id, 'jean-test', 'Jean Test', 'Marketing', 'Paris', 'Matching role', 90)]
    assert ranking.await_args.args[1] == [{'index': 0, 'headline': 'Marketing', 'location': 'Paris'}]
    send.assert_awaited_once()
    assert send.await_args.args[-3:] == (['marie-test'], 'Hello', campaign_id)
