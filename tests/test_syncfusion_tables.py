import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.dependencies.auth import require_auth
from app.models.auth import AuthUser
from app.routers import posts
from app.templating import _i18n_context


class SyncfusionTableTests(unittest.TestCase):
    def setUp(self):
        self.user = AuthUser(id="user", email="test@example.com", session_id="session",
                             request_token="token", active_workspace_id="workspace")
        app = FastAPI()
        app.include_router(posts.router, prefix="/app")
        app.dependency_overrides[require_auth] = lambda: self.user
        self.client = TestClient(app)

    def load_posts(self, key, page):
        now = datetime.now(timezone.utc)
        rows = [{"id": str(i), "title": f"Example post {i}", "subject": "Example",
                 "status": "generated", "updated_at": now, "created_at": now,
                 "created_by_name": "Tester", "generation_origin": "manual", "strategy_id": "",
                 "strategy_title": "", "strategy_action_title": "", "ideas_count": 1,
                 "approved_count": 0, "media_count": 1} for i in range(24)]
        conn = AsyncMock()
        conn.fetch.side_effect = [rows, []]
        conn.fetchval.return_value = 24
        conn.fetchrow.return_value = {"all_count": 24, "strategy_count": 0, "manual_count": 24}
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        settings = SimpleNamespace(syncfusion_license_key=key)
        with patch.object(posts, "get_pool", return_value=pool), patch.object(posts, "get_settings", return_value=settings), patch("app.templating.get_settings", return_value=settings):
            response = self.client.get(f"/app/posts?page={page}")
        return response, conn

    def test_grid_filters_can_access_records_beyond_first_page(self):
        response, conn = self.load_posts("test-license-v35", 3)
        self.assertEqual(response.status_code, 200)
        query = conn.fetch.call_args_list[0].args
        self.assertEqual(query[1], "workspace")
        self.assertEqual(query[-2:], (0, None))
        self.assertIn("Example post 23", response.text)
        self.assertIn("35.1.37/dist/ej2.min.js", response.text)
        self.assertIn("data-syncfusion=", response.text)
        self.assertIn("classList.add('pg-grid-loading')", response.text)
        self.assertIn('class="pgGridLoading"', response.text)
        self.assertLess(response.text.index("classList.add('pg-grid-loading')"), response.text.index('class="pgGridLoading"'))

    def test_without_license_standard_server_paging_is_preserved(self):
        response, conn = self.load_posts("", 3)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(conn.fetch.call_args_list[0].args[-2:], (20, 10))
        self.assertNotIn("35.1.37/dist/ej2.min.js", response.text)
        self.assertNotIn("classList.add('pg-grid-loading')", response.text)
        self.assertNotIn('class="pgGridLoading"', response.text)

    def test_editor_enables_stepper_without_grid_preferences(self):
        request = Request({"type": "http", "path": "/app/posts/view", "query_string": b"", "headers": []})
        with patch("app.templating.get_settings", return_value=SimpleNamespace(syncfusion_license_key="test-license")):
            context = _i18n_context(request)
            self.assertFalse(context["syncfusion_tables"])
            self.assertTrue(context["syncfusion_post_flow"])

    def test_strategy_detail_keeps_its_existing_editor(self):
        request = Request({"type": "http", "path": "/app/strategies", "query_string": b"strategy_id=example", "headers": []})
        with patch("app.templating.get_settings", return_value=SimpleNamespace(syncfusion_license_key="test-license")):
            self.assertFalse(_i18n_context(request)["syncfusion_tables"])
