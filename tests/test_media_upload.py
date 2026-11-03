from io import BytesIO
import unittest
from PIL import Image
from app.routers.media import _uploaded_media_format


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
