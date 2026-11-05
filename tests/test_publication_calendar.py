from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies.auth import require_auth
from app.models.auth import AuthUser
from app.routers.publication_calendar import router


class PublicationCalendarTests(unittest.TestCase):
    def setUp(self):
        self.user = AuthUser(id="user", email="test@example.com", session_id="session", request_token="token", active_workspace_id="workspace", timezone="Europe/Paris")
        app = FastAPI()
        app.include_router(router, prefix="/app")
        app.dependency_overrides[require_auth] = lambda: self.user
        self.client = TestClient(app)
        self.conn = AsyncMock()
        self.conn.fetchval.return_value = True
        self.conn.transaction = MagicMock(return_value=AsyncMock())
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=self.conn)
        patcher = patch("app.routers.publication_calendar.get_pool", return_value=pool)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.revision = datetime(2098, 12, 1, tzinfo=timezone.utc)
        self.strategy_id = "22222222-2222-4222-8222-222222222222"
        self.payload = {"strategy_id": self.strategy_id, "scheduled_at": "2099-01-10T09:00", "expected_updated_at": self.revision.isoformat()}
        self.url = "/app/publication-calendar/11111111-1111-4111-8111-111111111111"

    def test_calendar_is_scoped_and_published_events_are_readonly(self):
        base = {"id": "pub", "status": "scheduled", "platform": "linkedin", "publish_mode": "scheduled", "scheduled_at": self.revision,
                "revision": self.revision, "event_time": self.revision, "title": "Example", "idea_id": "idea", "request_id": "request", "can_open": True, "account": "Example account"}
        self.conn.fetch.return_value = [base, {**base, "id": "already-published", "status": "published"}, {**base, "id": "orphan", "can_open": False}]
        response = self.client.get("/app/publication-calendar/events", params={"strategy_id": self.strategy_id, "start": "2098-12-01T00:00:00Z", "end": "2099-01-01T00:00:00Z"})
        self.assertEqual(response.status_code, 200)
        events = response.json()["data"]
        self.assertFalse(events[0]["IsReadonly"])
        self.assertTrue(events[1]["IsReadonly"])
        self.assertTrue(events[2]["IsReadonly"])
        self.assertEqual(events[2]["PostUrl"], "/app/published")
        self.assertEqual(self.conn.fetch.call_args.args[1], "workspace")
        self.assertIn("pp.workspace_id=$1", self.conn.fetch.call_args.args[0])
        self.assertIn("c.strategy_id=$6", self.conn.fetch.call_args.args[0])
        self.assertEqual(str(self.conn.fetch.call_args.args[-1]), self.strategy_id)

    def test_action_events_are_scoped_and_completed_actions_are_readonly(self):
        base = {"id": "task", "status": "scheduled", "planned_for": self.revision,
                "title": "Create content", "request_id": None, "active_request_exists": False}
        self.conn.fetch.return_value = [base, {**base, "id": "done", "status": "generated"},
                                       {**base, "id": "linked", "active_request_exists": True, "request_id": "request"},
                                       {**base, "id": "running", "status": "processing"}]
        response = self.client.get("/app/strategy-calendar/actions", params={
            "strategy_id": self.strategy_id, "start": "2098-12-01T00:00:00Z", "end": "2099-01-01T00:00:00Z"})
        self.assertEqual(response.status_code, 200)
        events = response.json()["data"]
        self.assertEqual(events[0]["Kind"], "action")
        self.assertEqual(events[0]["Id"], "action:task")
        self.assertFalse(events[0]["IsReadonly"])
        self.assertTrue(all(event["IsReadonly"] for event in events[1:]))
        self.assertEqual(events[0]["PostUrl"], "")
        self.assertIn("request_id=request", events[2]["PostUrl"])
        self.assertIn("c.workspace_id=$1", self.conn.fetch.call_args.args[0])
        self.assertEqual(self.conn.fetch.call_args.args[1], "workspace")
        self.assertEqual(str(self.conn.fetch.call_args.args[2]), self.strategy_id)
        self.conn.fetchval.return_value = False
        denied = self.client.get("/app/strategy-calendar/actions", params={
            "strategy_id": self.strategy_id, "start": "2098-12-01T00:00:00Z", "end": "2099-01-01T00:00:00Z"})
        self.assertEqual(denied.status_code, 404)

    def test_rescheduling_uses_profile_timezone_and_preserves_snapshots(self):
        instant = datetime(2099, 1, 10, 8, tzinfo=timezone.utc)
        self.conn.fetchrow.return_value = {"idea_id": "idea", "scheduled_at": instant, "updated_at": instant}
        response = self.client.put(self.url, json=self.payload)
        self.assertEqual(response.status_code, 200)
        args = self.conn.fetchrow.call_args.args
        self.assertEqual(args[2], "workspace")
        self.assertEqual(args[3], instant)
        self.assertEqual(args[4], self.revision)
        self.assertEqual(str(args[5]), self.strategy_id)
        self.assertIn("c.strategy_id=$5", args[0])
        self.assertIn("pp.status='scheduled'", args[0])
        self.assertIn("pp.publish_mode='scheduled'", args[0])
        self.assertNotIn("SET media_id", args[0])
        self.assertNotIn("SET post_text_snapshot", args[0])
        self.conn.execute.assert_awaited_once()

    def test_changed_or_claimed_publication_cannot_be_moved(self):
        self.conn.fetchrow.return_value = None
        response = self.client.put(self.url, json=self.payload)
        self.assertEqual(response.status_code, 409)
        self.conn.execute.assert_not_awaited()

    def test_past_date_rejected_without_database_write(self):
        response = self.client.put(self.url, json={**self.payload, "scheduled_at": "2000-01-01T09:00"})
        self.assertEqual(response.status_code, 422)
        self.conn.fetchrow.assert_not_awaited()

    def test_nonexistent_dst_hour_is_rejected(self):
        response = self.client.put(self.url, json={**self.payload, "scheduled_at": "2099-03-29T02:30"})
        # Europe/Paris jumps from 02:00 to 03:00 on this date.
        self.assertEqual(response.status_code, 422)
        self.conn.fetchrow.assert_not_awaited()

    def test_unbounded_ranges_invalid_status_and_missing_timezone_are_rejected(self):
        for params in [
            {"start": "2099-01-01T00:00:00Z", "end": "2100-01-01T00:00:00Z"},
            {"start": "2099-01-01T00:00:00Z", "end": "2099-02-01T00:00:00Z", "status": "unknown"},
            {"start": "2099-01-01T00:00:00", "end": "2099-02-01T00:00:00"},
        ]:
            with self.subTest(params=params):
                self.assertEqual(self.client.get("/app/publication-calendar/events", params={**params, "strategy_id": self.strategy_id}).status_code, 422)
        self.conn.fetch.assert_not_awaited()

    def test_client_cannot_change_workspace_or_publication_status(self):
        response = self.client.put(self.url, json={**self.payload, "workspace_id": "other", "status": "published"})
        self.assertEqual(response.status_code, 422)
        self.conn.fetchrow.assert_not_awaited()

    def test_calendar_cannot_read_another_workspace_strategy(self):
        self.conn.fetchval.return_value = False
        response = self.client.get("/app/publication-calendar/events", params={"strategy_id": self.strategy_id,
            "start": "2099-01-01T00:00:00Z", "end": "2099-02-01T00:00:00Z"})
        self.assertEqual(response.status_code, 404)
        self.conn.fetch.assert_not_awaited()

    def test_calendar_requires_a_strategy_and_has_no_standalone_page(self):
        response = self.client.get("/app/publication-calendar/events", params={
            "start": "2099-01-01T00:00:00Z", "end": "2099-02-01T00:00:00Z"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get("/app/publication-calendar", follow_redirects=False).headers["location"], "/app/strategies")
