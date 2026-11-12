"""Foreground generation must not be reclaimed as a second image job."""
import json
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.routers import media
from app.worker import media_image_cron


class ImageGenerationOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_foreground_image_stays_out_of_worker_queue(self):
        conn = SimpleNamespace(fetchrow=AsyncMock(side_effect=[
            {"use_macaron": False}, {"media_id": "first-image"},
        ]), execute=AsyncMock())

        @asynccontextmanager
        async def acquire():
            yield conn

        user = SimpleNamespace(active_workspace_id="workspace", macaron_position=None)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "first-image.jpg"

            async def generate(**kwargs):
                # Inspect the persisted state while the provider is still busy.
                insert = conn.fetchrow.await_args_list[1].args[0]
                self.assertIn("'processing','running'", insert)
                self.assertNotIn("'pending'", insert)
                return {"url": "https://provider.example/first-image.jpg"}

            def write(mid, data, suffix):
                self.assertEqual(mid, "first-image")
                output.write_bytes(data)
                return str(output), output.name, len(data)

            with patch.object(media, "get_pool", return_value=SimpleNamespace(acquire=acquire)), \
                 patch.object(media, "_idea_exists", AsyncMock(return_value=True)), \
                 patch.object(media.media_gen, "generate_image", AsyncMock(side_effect=generate)) as provider, \
                 patch.object(media, "_image_bytes", AsyncMock(return_value=(b"first image", ".jpg", "image/jpeg"))), \
                 patch.object(media, "_write_media", side_effect=write), \
                 patch.object(media, "_public_url", return_value="https://app.example/first-image.jpg"):
                response = await media.post_ideas_image({"idea_id": "idea", "use_macaron": False}, user)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(json.loads(response.body)["data"]["media_id"], "first-image")
            self.assertEqual(output.read_bytes(), b"first image")
            provider.assert_awaited_once()

    async def test_worker_only_recovers_explicitly_expired_leases(self):
        conn = SimpleNamespace(fetchrow=AsyncMock(return_value=None))

        @asynccontextmanager
        async def context():
            yield conn

        conn.transaction = context
        with patch.object(media_image_cron, "get_pool", return_value=SimpleNamespace(acquire=context)):
            self.assertIsNone(await media_image_cron._claim())
        query = conn.fetchrow.await_args.args[0]
        self.assertIn("status='pending'", query)
        self.assertIn("generation_status IN ('queued','retry')", query)
        self.assertIn("NULLIF(metadata->>'image_lock_until','')::timestamptz < now()", query)
        self.assertNotIn("now()-interval", query)
