from io import BytesIO
import unittest
from PIL import Image
from app.routers.media import _uploaded_media_format
from app.routers.media import _store_uploaded_video
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import tempfile


class MediaUploadTests(unittest.TestCase):
    def test_photo_content(self):
        for fmt, suffix, mime in [('PNG', '.png', 'image/png'), ('JPEG', '.jpg', 'image/jpeg'), ('WEBP', '.webp', 'image/webp')]:
            with self.subTest(fmt=fmt):
                raw = BytesIO()
                Image.new('RGB', (16, 16), 'white').save(raw, format=fmt)
                self.assertEqual(_uploaded_media_format(raw.getvalue()), ('image', suffix, mime))

    def test_invalid_content(self):
        for data in [b'', b'<script>alert(1)</script>', b'not a photo.jpg', b'\x89PNG\r\n\x1a\ntruncated']:
            with self.subTest(data=data), self.assertRaises(ValueError):
                _uploaded_media_format(data)

    def test_video_containers(self):
        self.assertEqual(_uploaded_media_format(b'\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp42'), ('video', '.mp4', 'video/mp4'))
        self.assertEqual(_uploaded_media_format(b'\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  '), ('video', '.mov', 'video/quicktime'))


class LargeVideoUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_streams_chunks_and_cleans_up_oversized_video(self):
        for limit, succeeds in [(20, True), (5, False)]:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = SimpleNamespace(read=AsyncMock(side_effect=[b'next', b'']))
                with patch('app.services.media_storage.media_dir', return_value=root), patch(
                        'app.config.get_settings', return_value=SimpleNamespace(media_video_upload_max_bytes=limit)):
                    if succeeds:
                        name, _, size = await _store_uploaded_video(source, 'video', b'head', '.mp4')
                        self.assertEqual(Path(name).read_bytes(), b'headnext')
                        self.assertEqual(size, 8)
                        self.assertTrue(all(call.args == (1024 * 1024,) for call in source.read.await_args_list))
                    else:
                        with self.assertRaises(ValueError):
                            await _store_uploaded_video(source, 'video', b'head', '.mp4')
                        self.assertEqual(list(root.iterdir()), [])
