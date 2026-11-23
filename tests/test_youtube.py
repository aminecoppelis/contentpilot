import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import httpx
from cryptography.fernet import Fernet
from starlette.requests import Request

from app.routers import youtube as routes, publish
from app.services import youtube as yt
from app.services.social_accounts import accessible_account_query
from app.worker import publication_cron


def mock_pool(conn):
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    conn.transaction = MagicMock(return_value=AsyncMock())
    return pool


def options(**patches):
    return {'title': 'Test vidéo', 'description': 'Description', 'tags': ['tag'],
            'privacy': 'private', 'made_for_kids': False, **patches}


class YouTubeTests(unittest.IsolatedAsyncioTestCase):
    async def test_callback_encrypts_credentials_in_the_origin_company(self):
        conn = AsyncMock(); conn.fetchrow.side_effect = [{'redirect_uri': 'https://example.test/callback'}, {'id': 'account'}]
        tokens = {'access_token': 'access-fixture', 'refresh_token': 'refresh-fixture', 'expires_in': 3600}
        channel = {'id': 'channel-id', 'snippet': {'title': 'Company channel'}}
        cipher = Fernet(Fernet.generate_key())
        encrypt = lambda text: cipher.encrypt(text.encode()).decode()
        request = Request({'type': 'http', 'headers': []})
        with patch.object(routes, 'get_pool', return_value=mock_pool(conn)), patch.object(routes, 'session_hash', return_value='browser'), \
             patch.object(yt, 'exchange_code', AsyncMock(return_value=(tokens, channel))), patch.object(routes, 'encrypt_token', side_effect=encrypt), \
             patch.object(routes, 'ensure_local_workspace_link', AsyncMock()) as link:
            response = await routes.callback(request, state='state', code='code', user=SimpleNamespace(id='user', active_workspace_id='company'))
        self.assertIn('connected=1', response.headers['location'])
        self.assertNotIn('fixture', response.headers['location'])
        saved = conn.fetchrow.await_args.args
        self.assertEqual(saved[2:4], ('company', 'channel-id'))
        self.assertEqual(json.loads(cipher.decrypt(saved[6].encode()))['refresh_token'], 'refresh-fixture')
        link.assert_awaited_once_with(conn, 'account', 'company', 'user')

    async def test_revocation_failure_is_never_reported_as_success(self):
        for status, body, succeeds in [(200, {}, True), (400, {'error':'invalid_token'}, True), (503, {}, False)]:
            received = []
            def handler(request):
                received.append(request)
                return httpx.Response(status, json=body)
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            with patch.object(yt, 'decrypt_token', return_value=json.dumps({'refresh_token':'refresh-fixture'})), patch.object(yt.httpx, 'AsyncClient', return_value=client):
                if succeeds:
                    await yt.revoke({'token_ciphertext':'encrypted'})
                else:
                    with self.assertRaises(yt.YouTubeError):
                        await yt.revoke({'token_ciphertext':'encrypted'})
            self.assertEqual(str(received[0].url), 'https://oauth2.googleapis.com/revoke')
            self.assertIn(b'refresh-fixture', received[0].content)

    async def test_worker_never_succeeds_without_youtube_confirmation(self):
        for outcome, failure in [({}, None), (None, ValueError())]:
            conn = AsyncMock(); conn.fetchval.return_value = True
            job = {'publication_id': 'publication', 'idea_id': 'idea', 'workspace_id': 'company',
                   'media_type': 'video', 'platform': 'youtube', 'response': {'social_account_id': 'account', 'youtube': options()}}
            with patch.object(publication_cron, '_claim_batch', AsyncMock(return_value=[job])), \
                 patch.object(publication_cron, 'get_pool', return_value=mock_pool(conn)), \
                 patch.object(publication_cron, 'fetch_accessible_account', AsyncMock(return_value={'id': 'account', 'provider': 'youtube'})), \
                 patch.object(publication_cron, 'publish_to_account', AsyncMock(return_value=outcome, side_effect=failure)), \
                 patch.object(publication_cron.logger, 'exception'):
                result = await publication_cron.run_publication_cycle(limit=1)
            self.assertEqual(result['published'], 0)
            self.assertEqual(result['failed'], 1)
            self.assertEqual(conn.execute.await_args_list[0].args[2], 'failed')

    async def test_foreign_workspace_cannot_get_progress(self):
        conn = AsyncMock(); conn.fetchrow.return_value = None
        with patch.object(routes, 'get_pool', return_value=mock_pool(conn)):
            response = await routes.progress('publication', SimpleNamespace(active_workspace_id='other-company'))
        self.assertEqual(response.status_code, 404)
        self.assertIn('workspace_id=$2::uuid', conn.fetchrow.await_args.args[0])
        self.assertEqual(conn.fetchrow.await_args.args[-1], 'other-company')
        self.assertNotIn('ciphertext', conn.fetchrow.await_args.args[0])

    async def test_foreign_workspace_cannot_refresh_token(self):
        conn = AsyncMock(); conn.fetchrow.return_value = None
        with patch.object(yt, 'get_pool', return_value=mock_pool(conn)), patch.object(yt, 'configured', return_value=SimpleNamespace()), \
             patch.object(yt.httpx, 'AsyncClient') as client:
            with self.assertRaisesRegex(yt.YouTubeError, 'inaccessible'):
                await yt.access_token('foreign-account', 'other-company')
            client.assert_not_called()

    async def test_immediate_and_scheduled_use_existing_publication_queue(self):
        for mode in ('immediate', 'scheduled'):
            conn = AsyncMock()
            conn.fetchrow.side_effect = [
                {'raw_idea': {}}, {'post_text': 'Text', 'cta': '', 'hashtags': []},
                {'status': 'ready', 'media_type': 'video', 'public_url': 'https://app.test/video.mp4'},
                {'publication_id': 'publication'},
            ]
            conn.fetch.return_value = [{'id': 'account', 'provider': 'youtube', 'metadata': {}}]
            target = {'account_id': 'account', 'provider': 'youtube', 'platform': 'youtube',
                      'publish_content_type': 'short', 'publish_mode': mode, 'youtube': options(),
                      'scheduled_at': '2099-01-01T12:00:00Z'}
            with patch.object(publish, 'get_pool', return_value=mock_pool(conn)), patch.object(publish, 'publish_to_account', AsyncMock()) as send:
                response = await publish.post_ideas_publish({'idea_id': 'idea', 'version_id': 'version', 'media_id': 'media', 'targets': [target]},
                    SimpleNamespace(id='user', active_workspace_id='company', timezone='Europe/Paris'))
            self.assertEqual(response.status_code, 200)
            result = json.loads(response.body)['data']['results'][0]
            self.assertEqual(result['status'], 'processing' if mode=='immediate' else 'scheduled')
            send.assert_not_awaited()
            insert = conn.fetchrow.await_args.args
            self.assertIn('INSERT INTO public.post_publications', insert[0])
            self.assertEqual(insert[7], 'scheduled')
            self.assertEqual(json.loads(insert[-1])['youtube'], options())

    async def test_worker_confirms_and_reschedules_same_session_on_interruption(self):
        for interrupted in (False, True):
            conn = AsyncMock(); conn.fetchval.return_value = True
            job = {'publication_id': 'publication', 'idea_id': 'idea', 'workspace_id': 'company',
                   'media_type': 'video', 'platform': 'youtube', 'publication_type': 'short',
                   'response': {'social_account_id': 'account', 'youtube': options()}}
            send = AsyncMock(side_effect=yt.UploadInterrupted('Retry same session') if interrupted else None,
                             return_value={'id': 'video123', 'url': 'https://www.youtube.com/watch?v=video123'})
            with patch.object(publication_cron, '_claim_batch', AsyncMock(return_value=[job])), \
                 patch.object(publication_cron, 'get_pool', return_value=mock_pool(conn)), \
                 patch.object(publication_cron, 'fetch_accessible_account', AsyncMock(return_value={'id': 'account', 'provider': 'youtube'})), \
                 patch.object(publication_cron, 'publish_to_account', send):
                result = await publication_cron.run_publication_cycle(limit=1)
            self.assertEqual(send.await_args.kwargs['youtube_context']['workspace_id'], 'company')
            if interrupted:
                self.assertEqual(result['published'], 0)
                self.assertIn("status='scheduled'", conn.execute.await_args.args[0])
                self.assertEqual(conn.execute.await_args.args[1:3], ('publication', 'company'))
            else:
                self.assertEqual(result['published'], 1)
                saved = conn.execute.await_args_list[0].args
                self.assertEqual(saved[2], 'published')
                self.assertEqual(json.loads(saved[3])['provider_response']['id'], 'video123')
    def test_metadata_validation(self):
        self.assertEqual(yt.video_options(options(tags=['a', 'a']))['tags'], ['a'])
        for data in [options(title=''), options(title='x'*101), options(privacy='friends'),
                     options(tags='bad'), options(description='é'*2501), options(made_for_kids=None)]:
            with self.subTest(data=data), self.assertRaises(yt.YouTubeError):
                yt.video_options(data)

    def test_google_errors_are_safe_and_actionable(self):
        for status, reason, message in [(403, 'quotaExceeded', 'Quota'), (401, 'authError', 'Reconnectez'), (400, 'invalid_grant', 'Reconnectez')]:
            with self.subTest(reason=reason), self.assertRaisesRegex(yt.YouTubeError, message):
                yt.checked(httpx.Response(status, json={'error': {'errors': [{'reason': reason}]}}))
        for url in ['http://www.googleapis.com/upload/youtube/v3/videos', 'https://evil.test/upload/youtube/v3/videos', 'https://www.googleapis.com.evil.test/upload/youtube/v3/videos']:
            with self.assertRaises(yt.YouTubeError):
                yt.session_url(url)

    def test_shared_youtube_accounts_are_not_accessible(self):
        self.assertIn("a.provider <> 'youtube' OR a.workspace_id = $2::uuid", accessible_account_query(active_only=True))
        self.assertIsNone(publish._validate_publication_combination('youtube', 'youtube', 'short', 'video', {}))
        self.assertIsNotNone(publish._validate_publication_combination('youtube', 'youtube', 'standard', 'image', {}))

    async def test_refresh_scoped_encrypted_and_offline(self):
        cipher = Fernet(Fernet.generate_key())
        encrypt = lambda value: cipher.encrypt(value.encode()).decode()
        decrypt = lambda value: cipher.decrypt(value.encode()).decode()
        conn = AsyncMock()
        conn.fetchrow.return_value = {'token_ciphertext': encrypt(json.dumps({'access_token': 'expired', 'refresh_token': 'refresh'})),
                                    'token_expires_at': datetime.now(timezone.utc)-timedelta(hours=1)}
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'access_token': 'new', 'expires_in': 3600})))
        with patch.object(yt, 'get_pool', return_value=mock_pool(conn)), patch.object(yt, 'configured', return_value=SimpleNamespace(google_client_id='id', google_client_secret='secret')), \
             patch.object(yt.httpx, 'AsyncClient', return_value=client), patch.object(yt, 'encrypt_token', side_effect=encrypt), patch.object(yt, 'decrypt_token', side_effect=decrypt):
            self.assertEqual(await yt.access_token('account', 'company'), 'new')
        self.assertIn('workspace_id=$2::uuid', conn.fetchrow.await_args.args[0])
        self.assertEqual(conn.fetchrow.await_args.args[1:], ('account', 'company', False))
        saved = conn.execute.await_args.args[3]
        self.assertNotIn('refresh', saved)
        self.assertEqual(json.loads(decrypt(saved))['refresh_token'], 'refresh')

    async def test_authorization_check_purges_only_confirmed_revocation(self):
        settings = SimpleNamespace(google_client_id='id', google_client_secret='secret')
        for status, error in [(400, 'invalid_grant'), (503, 'server_error')]:
            with self.subTest(error=error):
                conn = AsyncMock()
                conn.fetchrow.return_value = {
                    'token_ciphertext': json.dumps({'refresh_token': 'refresh'}),
                    'token_expires_at': None,
                }
                client = httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda request: httpx.Response(status, json={'error': error})
                ))
                with patch.object(yt, 'get_pool', return_value=mock_pool(conn)), \
                     patch.object(yt, 'configured', return_value=settings), \
                     patch.object(yt, 'decrypt_token', side_effect=lambda value: value), \
                     patch.object(yt.httpx, 'AsyncClient', return_value=client):
                    expected = yt.AuthorizationRevoked if status == 400 else yt.YouTubeError
                    with self.assertRaises(expected):
                        await yt.access_token('account', 'company', verify=True)
                self.assertEqual(conn.execute.await_count, 3 if status == 400 else 0)
                if status == 400:
                    sql, account, workspace = conn.execute.await_args.args
                    self.assertIn("- 'provider_response'", sql)
                    self.assertIn('youtube_upload_ciphertext=NULL', sql)
                    self.assertEqual((account, workspace), ('account', 'company'))

    async def test_chunk_upload_recovers_server_offset_and_saves_confirmation(self):
        cipher = Fernet(Fernet.generate_key())
        encrypt = lambda value: cipher.encrypt(value.encode()).decode()
        decrypt = lambda value: cipher.decrypt(value.encode()).decode()
        conn = AsyncMock()
        requests = []
        sequence = 0

        def handler(request):
            nonlocal sequence
            requests.append((request.method, request.headers.get('content-range'), len(request.content)))
            sequence += 1
            if sequence == 1:
                return httpx.Response(200, headers={'Location': yt.UPLOAD_URL+'?upload_id=test'})
            if sequence == 2:
                return httpx.Response(308)
            if sequence == 3:
                # Google committed the first chunk but the response was lost.
                raise httpx.ReadError('offline')
            if sequence == 4:
                return httpx.Response(308, headers={'Range': 'bytes=0-262143'})
            return httpx.Response(201, json={'id': 'video123', 'status': {'privacyStatus': 'private', 'uploadStatus': 'uploaded'}})

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'video.mp4'
            path.write_bytes(b'x'*300000)
            row = {'file_path': str(path), 'mime_type': 'video/mp4', 'youtube_upload_ciphertext': None}
            conn.fetchrow.return_value = row
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            settings = SimpleNamespace(media_storage_path=Path(directory).resolve(), youtube_chunk_bytes=262144)
            with patch.object(yt, 'get_pool', return_value=mock_pool(conn)), patch.object(yt, 'get_settings', return_value=settings), \
                 patch.object(yt, 'access_token', AsyncMock(return_value='access')), patch.object(yt.httpx, 'AsyncClient', return_value=client), \
                 patch.object(yt, 'encrypt_token', side_effect=encrypt), patch.object(yt, 'decrypt_token', side_effect=decrypt), \
                 patch.object(yt.asyncio, 'sleep', AsyncMock()):
                result = await yt.upload({'id': 'account'}, 'publication', 'company', options())
            self.assertEqual(result['id'], 'video123')
            self.assertEqual(requests[-1][1], 'bytes 262144-299999/300000')
            self.assertEqual(sum(method=='POST' for method, _, _ in requests), 1)
            saves = conn.execute.await_args_list
            self.assertEqual([call.args[-2] for call in saves], [0, 0, 262144, 300000])
            last_state = json.loads(decrypt(saves[-1].args[3]))
            self.assertEqual(last_state['result']['id'], 'video123')
            self.assertTrue(all(call.args[2]=='company' for call in saves))

    async def test_expired_session_never_starts_duplicate_upload(self):
        conn = AsyncMock()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'video.mp4'; path.write_bytes(b'video')
            state = {'url': yt.UPLOAD_URL+'?upload_id=old', 'size': 5, 'mtime': path.stat().st_mtime_ns}
            conn.fetchrow.return_value = {'file_path': str(path), 'mime_type': 'video/mp4', 'youtube_upload_ciphertext': json.dumps(state)}
            calls = []
            def handler(request):
                calls.append(request.method)
                return httpx.Response(404)
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            with patch.object(yt, 'get_pool', return_value=mock_pool(conn)), patch.object(yt, 'get_settings', return_value=SimpleNamespace(media_storage_path=Path(directory).resolve(), youtube_chunk_bytes=262144)), \
                 patch.object(yt, 'decrypt_token', side_effect=lambda value: value), patch.object(yt, 'access_token', AsyncMock(return_value='access')), patch.object(yt.httpx, 'AsyncClient', return_value=client):
                with self.assertRaisesRegex(yt.YouTubeError, 'expirée'):
                    await yt.upload({'id': 'account'}, 'publication', 'company', options())
            self.assertEqual(calls, ['PUT'])

    async def test_repeated_chunk_failures_are_bounded_even_if_probes_succeed(self):
        conn = AsyncMock()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'video.mp4'; path.write_bytes(b'video')
            state = {'url': yt.UPLOAD_URL+'?upload_id=old', 'size': 5, 'mtime': path.stat().st_mtime_ns}
            conn.fetchrow.return_value = {'file_path': str(path), 'mime_type': 'video/mp4', 'youtube_upload_ciphertext': json.dumps(state)}
            calls = []
            def handler(request):
                calls.append(request.headers['Content-Range'])
                return httpx.Response(308 if request.headers['Content-Range'].startswith('bytes */') else 503)
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            with patch.object(yt, 'get_pool', return_value=mock_pool(conn)), patch.object(yt, 'get_settings', return_value=SimpleNamespace(media_storage_path=Path(directory).resolve(), youtube_chunk_bytes=262144)), \
                 patch.object(yt, 'decrypt_token', side_effect=lambda value: value), patch.object(yt, 'encrypt_token', side_effect=lambda value: value), \
                 patch.object(yt, 'access_token', AsyncMock(return_value='access')), patch.object(yt.httpx, 'AsyncClient', return_value=client), patch.object(yt.asyncio, 'sleep', AsyncMock()):
                with self.assertRaises(yt.UploadInterrupted):
                    await yt.upload({'id': 'account'}, 'publication', 'company', options())
            self.assertEqual(sum(value=='bytes 0-4/5' for value in calls), 4)

    async def test_oauth_state_offline_session_binding_and_replay_rejection(self):
        conn = AsyncMock(); conn.fetchrow.return_value = None
        user = SimpleNamespace(id='user', active_workspace_id='company')
        request = Request({'type': 'http', 'headers': [(b'cookie', b'pg_session=browser-token')]})
        settings = SimpleNamespace(google_client_id='client')
        with patch.object(routes, 'get_pool', return_value=mock_pool(conn)), patch.object(yt, 'configured', return_value=settings), \
             patch.object(yt, 'redirect_uri', return_value='https://example.test/callback'), patch.object(routes, 'session_hash', return_value='browser-hash'), \
             patch.object(yt, 'exchange_code', AsyncMock()) as exchange:
            response = await routes.connect(request, user)
            params = parse_qs(urlsplit(response.headers['location']).query)
            self.assertEqual(params['access_type'], ['offline'])
            self.assertIn(yt.UPLOAD_SCOPE, params['scope'][0])
            self.assertEqual(conn.execute.await_args.args[-1], 'browser-hash')
            rejected = await routes.callback(request, state=params['state'][0], code='code', user=user)
            self.assertIn('oauth_error', rejected.headers['location'])
            exchange.assert_not_awaited()
        sql, *args = conn.fetchrow.await_args.args
        self.assertIn('DELETE FROM', sql)
        self.assertIn('workspace_id=$3::uuid', sql)
        self.assertIn('session_hash=$4', sql)
        self.assertEqual(args[1:], ['user', 'company', 'browser-hash'])
