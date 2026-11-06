import unittest
from unittest.mock import AsyncMock

from app.services.dashboard_metrics import load_dashboard_metrics, HISTORY_SQL, UPCOMING_SQL, NEXT_ACTIONS_SQL, ACTION_GROUPS_SQL


class DashboardMetricsTests(unittest.IsolatedAsyncioTestCase):
    async def test_metrics_preserve_counts_timezone_and_workspace_scope(self):
        conn = AsyncMock()
        conn.fetch.side_effect = [
            [{"status": "published", "total": 12}, {"status": "scheduled", "total": 3}],
            [{"day": "2026-11-05", "total": 0}, {"day": "2026-11-06", "total": 2}],
            [{"id": "send", "title": "Example", "platform": "linkedin"}],
            [{"strategy_id": "strategy", "title": "Strategy", "upcoming": 1, "overdue": 2, "failed": 1}],
            [{"id": "future", "title": "Future action"}],
        ]
        conn.fetchrow.return_value = {"scheduled": 3, "overdue": 1, "failed": 2}
        data = await load_dashboard_metrics(conn, "workspace", "Europe/Paris")
        self.assertEqual(data["statuses"], {"published": 12, "scheduled": 3})
        self.assertEqual(data["history"][0]["total"], 0)
        self.assertEqual(data["upcoming"][0]["title"], "Example")
        for call in conn.fetch.call_args_list:
            self.assertEqual(call.args[1], "workspace")
            self.assertIn("workspace_id=$1", call.args[0])
        self.assertEqual(conn.fetch.call_args_list[1].args[2], "Europe/Paris")
        self.assertIn("AT TIME ZONE $2", HISTORY_SQL)
        self.assertIn("LEFT JOIN counts", HISTORY_SQL)
        self.assertIn("pi.deleted_at IS NULL AND pr.deleted_at IS NULL", UPCOMING_SQL)
        self.assertIn("pp.scheduled_at >= now()", UPCOMING_SQL)
        self.assertEqual(data["operations"]["overdue"], 1)
        self.assertEqual(data["action_groups"][0]["overdue"], 2)
        self.assertEqual(data["next_actions"][0]["id"], "future")
        self.assertIn("c.planned_for >= now()", NEXT_ACTIONS_SQL)
        self.assertIn("c.planned_for < now()", ACTION_GROUPS_SQL)
        self.assertIn("s.status='active'", NEXT_ACTIONS_SQL)
        self.assertIn("pr.deleted_at IS NULL", NEXT_ACTIONS_SQL)

    async def test_empty_workspace_has_no_invented_metrics(self):
        conn = AsyncMock()
        conn.fetch.side_effect = [[], [], [], [], []]
        conn.fetchrow.return_value = {"scheduled": 0, "overdue": 0, "failed": 0}
        self.assertEqual(await load_dashboard_metrics(conn, "workspace", "UTC"),
                         {"statuses": {}, "history": [], "upcoming": [],
                          "operations": {"scheduled": 0, "overdue": 0, "failed": 0},
                          "action_groups": [], "next_actions": []})
