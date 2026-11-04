import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from jinja2 import Environment, FileSystemLoader

from app.i18n import SUPPORTED_LOCALES, translate
from app.routers.posts import _add_publication_statuses, _publication_badges


class PublicationStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_visible_requests_share_one_workspace_scoped_query(self):
        conn = AsyncMock()
        conn.fetch.return_value = [
            {"request_id": "first", "status": "published", "count": 2},
            {"request_id": "first", "status": "scheduled", "count": 1},
            {"request_id": "second", "status": "failed", "count": 1},
        ]
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        requests = [{"id": "first"}, {"id": "second"}, {"id": "third"}]
        with patch("app.routers.posts.get_pool", return_value=pool):
            await _add_publication_statuses(requests, "workspace")
        self.assertEqual(conn.fetch.await_count, 1)
        self.assertEqual(conn.fetch.call_args.args[1:], ("workspace", ["first", "second", "third"]))
        self.assertEqual(requests[0]["publication_badges"], [
            {"status": "published", "count": 2}, {"status": "scheduled", "count": 1}])
        self.assertEqual(requests[1]["publication_badges"], [{"status": "failed", "count": 1}])
        self.assertEqual(requests[2]["publication_badges"], [])

    async def test_empty_page_does_not_query_database(self):
        with patch("app.routers.posts.get_pool") as pool:
            await _add_publication_statuses([], "workspace")
            pool.assert_not_called()

    def test_error_alias_and_unknown_status_remain_visible(self):
        self.assertEqual(_publication_badges({"failed": 1, "error": 2, "unexpected": 1}), [
            {"status": "failed", "count": 3}, {"status": "other", "count": 1}])

    def test_badges_and_empty_state_render_in_all_languages(self):
        root = Path(__file__).resolve().parent.parent
        env = Environment(loader=FileSystemLoader(root / "templates"), autoescape=True)
        template = env.get_template("posts/_publication_status.html")
        for locale in SUPPORTED_LOCALES:
            with self.subTest(locale=locale):
                t = lambda key, **kwargs: translate(key, locale, **kwargs)
                html = template.render(t=t, r={"publication_badges": _publication_badges({"published": 2, "scheduled": 1})})
                self.assertIn(t("posts.publication.published"), html)
                self.assertIn(t("posts.publication.scheduled"), html)
                self.assertIn("×2", html)
                self.assertNotIn("posts.publication.", html)
                empty = template.render(t=t, r={"publication_badges": []})
                self.assertIn(t("posts.publication.none"), empty)
