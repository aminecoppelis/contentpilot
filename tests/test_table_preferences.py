import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.auth import require_auth
from app.models.auth import AuthUser
from app.routers.table_preferences import router


class TablePreferenceTests(unittest.TestCase):
    def setUp(self):
        self.user = AuthUser(id="user-a", email="a@example.com", session_id="session", request_token="token", active_workspace_id="workspace-a")
        app = FastAPI()
        app.include_router(router, prefix="/app")
        app.dependency_overrides[require_auth] = lambda: self.user
        self.client = TestClient(app)
        self.conn = AsyncMock()
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=self.conn)
        patcher = patch("app.routers.table_preferences.get_pool", return_value=pool)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.payload = {"revision": 100, "state": {"version": 1, "columnCount": 3,
            "filters": [{"field": "c0", "operator": "contains", "value": "example", "predicate": "and"}],
            "sort": [{"field": "c1", "direction": "Descending"}], "search": "search text", "pageSize": 20,
            "columns": [{"field": "c2", "width": 250, "visible": False}, {"field": "c0", "width": 300, "visible": True}],
            "pageFilters": {"origin": "strategy"}}}

    def test_load_is_scoped_to_authenticated_user_and_workspace(self):
        self.conn.fetch.return_value = [{"view_key": "posts", "state": json.dumps(self.payload["state"]), "revision": 100}]
        response = self.client.get("/app/table-preferences")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.conn.fetch.call_args.args[1:], ("user-a", "workspace-a"))
        self.assertEqual(response.json()["data"]["posts"]["state"], self.payload["state"])

    def test_save_keeps_state_and_rejects_older_writes_in_sql(self):
        response = self.client.put("/app/table-preferences/posts", json=self.payload)
        self.assertEqual(response.status_code, 200)
        args = self.conn.execute.call_args.args
        self.assertEqual(args[1:4], ("user-a", "workspace-a", "posts"))
        saved = json.loads(args[4])
        self.assertEqual(saved["filters"][0]["value"], "example")
        self.assertEqual(saved["columns"][0]["field"], "c2")
        self.assertEqual(saved["pageSize"], 20)
        self.assertIn("revision < EXCLUDED.revision", args[0])
        self.assertEqual(args[5], 100)

    def test_another_user_and_workspace_use_separate_keys(self):
        self.user.id = "user-b"
        self.user.active_workspace_id = "workspace-b"
        self.client.put("/app/table-preferences/posts", json=self.payload)
        self.assertEqual(self.conn.execute.call_args.args[1:3], ("user-b", "workspace-b"))

    def test_client_cannot_choose_a_user_or_workspace(self):
        payload = {**self.payload, "workspace_id": "other", "user_id": "other"}
        self.assertEqual(self.client.put("/app/table-preferences/posts", json=payload).status_code, 422)
        self.conn.execute.assert_not_awaited()

    def test_invalid_views_fields_sizes_and_operators_are_rejected(self):
        self.assertEqual(self.client.put("/app/table-preferences/unknown", json=self.payload).status_code, 422)
        for change in [{"pageSize": 100000}, {"filters": [{"field": "c99", "operator": "equal"}]},
                       {"filters": [{"field": "__proto__", "operator": "equal"}]},
                       {"filters": [{"field": "c0", "operator": "execute"}]}, {"search": "x" * 40000}]:
            with self.subTest(change=change):
                payload = {**self.payload, "state": {**self.payload["state"], **change}}
                self.assertEqual(self.client.put("/app/table-preferences/posts", json=payload).status_code, 422)
        self.conn.execute.assert_not_awaited()

    def test_regular_user_cannot_save_admin_table_preferences(self):
        self.assertEqual(self.client.put("/app/table-preferences/users", json=self.payload).status_code, 403)
        self.conn.execute.assert_not_awaited()

    def test_calendar_preferences_are_saved_separately_from_grids(self):
        payload = {"revision": 101, "state": {"kind": "calendar", "version": 1, "activeView": "Agenda", "status": "scheduled", "platform": "linkedin"}}
        response = self.client.put("/app/table-preferences/publication_calendar", json=payload)
        self.assertEqual(response.status_code, 200)
        args = self.conn.execute.call_args.args
        self.assertEqual(args[3], "publication_calendar")
        self.assertEqual(json.loads(args[4])["activeView"], "Agenda")
        self.assertEqual(self.client.put("/app/table-preferences/posts", json=payload).status_code, 422)
        self.assertEqual(self.client.put("/app/table-preferences/publication_calendar", json=self.payload).status_code, 422)
