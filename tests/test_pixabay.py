import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.dependencies.auth import require_auth
from app.routers.media import router
from app.services import pixabay


HIT = {'id': 42, 'webformatURL': 'https://pixabay.com/get/photo.jpg',
       'largeImageURL': 'https://pixabay.com/get/photo-large.jpg',
       'pageURL': 'https://pixabay.com/photos/example-42/', 'user': 'Photographer', 'tags': 'nature'}


class PostQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_analysis_receives_actual_post(self):
        queries = ['panneaux solaires', 'installation solaire', 'toiture solaire', 'energie solaire', 'centrale solaire']
        with patch('app.services.ai._run_agent', new=AsyncMock(return_value=SimpleNamespace(parsed={'queries': queries}))) as agent:
            result = await pixabay.post_queries('Toiture solaire', 'Installer des panneaux solaires sur les maisons.')
        self.assertEqual(result, queries)
        context = json.loads(agent.call_args.args[1])
        self.assertEqual(context['post'], 'Installer des panneaux solaires sur les maisons.')
        self.assertEqual(context['title'], 'Toiture solaire')

    def test_preserves_five_separate_search_phrases(self):
        queries = ['panneaux solaires', 'installation solaire', 'toiture solaire', 'energie solaire', 'centrale solaire']
        self.assertEqual(pixabay.validate_post_queries({'queries': queries})['queries'], queries)

    def test_rejects_duplicates_missing_queries_and_long_sentences(self):
        for value in [{}, {'queries': ['bureau'] * 5}, {'queries': ['une tres longue phrase de recherche photo peu adaptee'] * 5}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                pixabay.validate_post_queries(value)


class PixabayCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_is_cached_and_does_not_expose_key(self):
        with tempfile.TemporaryDirectory() as directory:
            response = httpx.Response(200, json={'totalHits': 1, 'hits': [HIT]}, request=httpx.Request('GET', 'https://pixabay.com/api/'))
            with patch.object(pixabay, 'CACHE_DIR', Path(directory)), patch.object(pixabay, 'get_settings', return_value=SimpleNamespace(pixabay_api_key='secret')), patch.object(httpx.AsyncClient, 'get', new=AsyncMock(return_value=response)) as get:
                first = await pixabay.photos(query='nature')
                second = await pixabay.photos(query='nature')
                self.assertEqual(first, second)
                self.assertEqual(get.await_count, 1)
                self.assertNotIn('secret', json.dumps(pixabay.search_results(first)))
                self.assertNotIn('secret', ''.join(p.name for p in Path(directory).iterdir()))

    async def test_missing_key_has_actionable_error(self):
        with patch.object(pixabay, 'get_settings', return_value=SimpleNamespace(pixabay_api_key='')):
            with self.assertRaisesRegex(ValueError, 'PIXABAY_API_KEY'):
                await pixabay.photos(query='nature')

    async def test_provider_failure_does_not_leak_key(self):
        request = httpx.Request('GET', 'https://pixabay.com/api/?key=secret')
        response = httpx.Response(403, request=request)
        with tempfile.TemporaryDirectory() as directory, patch.object(pixabay, 'CACHE_DIR', Path(directory)), patch.object(pixabay, 'get_settings', return_value=SimpleNamespace(pixabay_api_key='secret')), patch.object(httpx.AsyncClient, 'get', new=AsyncMock(return_value=response)):
            with self.assertRaises(ValueError) as error:
                await pixabay.photos(query='nature')
            self.assertNotIn('secret', str(error.exception))


class PixabayRouteTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router, prefix='/app')
        app.dependency_overrides[require_auth] = lambda: SimpleNamespace(active_workspace_id='workspace')
        self.client = TestClient(app)

    def test_keywords_use_edited_post_and_workspace(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {'title': 'Saved title', 'post_text': 'Saved text', 'summary': ''}
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        queries = ['solar panels', 'solar roof', 'solar farm', 'solar installation', 'solar energy']
        with patch('app.routers.media.get_pool', return_value=pool), patch.object(pixabay, 'post_queries', new=AsyncMock(return_value=queries)) as analyze:
            response = self.client.post('/app/media/pixabay/keywords', json={
                'idea_id': '11111111-1111-1111-1111-111111111111',
                'title': 'Edited title', 'post_text': 'Edited solar post',
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['queries'], queries)
        analyze.assert_awaited_once_with('Edited title', 'Edited solar post')
        self.assertEqual(conn.fetchrow.call_args.args[-1], 'workspace')

    def test_keywords_do_not_analyze_another_workspace_post(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = None
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        with patch('app.routers.media.get_pool', return_value=pool), patch.object(pixabay, 'post_queries', new=AsyncMock()) as analyze:
            response = self.client.post('/app/media/pixabay/keywords', json={'idea_id': '11111111-1111-1111-1111-111111111111'})
        self.assertEqual(response.status_code, 404)
        analyze.assert_not_awaited()

    def test_search_returns_photo_choices(self):
        with patch.object(pixabay, 'photos', new=AsyncMock(return_value={'totalHits': 1, 'hits': [HIT]})):
            response = self.client.get('/app/media/pixabay?q=nature')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['photos'][0]['id'], 42)

    def test_empty_search_is_rejected(self):
        self.assertEqual(self.client.get('/app/media/pixabay?q=').status_code, 422)

    def test_import_checks_workspace_before_provider(self):
        with patch('app.routers.media._idea_exists', new=AsyncMock(return_value=False)), patch.object(pixabay, 'photos', new=AsyncMock()) as photos:
            response = self.client.post('/app/media/pixabay/import', json={'idea_id': '11111111-1111-1111-1111-111111111111', 'image_id': 42})
            self.assertEqual(response.status_code, 404)
            photos.assert_not_awaited()

    def test_untrusted_photo_url_is_rejected(self):
        with self.assertRaises(ValueError):
            pixabay.photo_url('https://pixabay.com.evil.example/image.jpg')
