import unittest

from app.routers.strategies import _apply_publication_preview


class StrategyPublicationPreviewTests(unittest.TestCase):
    def test_published_photo_wins_over_another_gallery_selection(self):
        preview = {"media_id": "new-gallery-photo", "media_url": "new.jpg", "post_text": "Edited draft"}
        _apply_publication_preview(preview, {
            "publication_id": "publication", "publication_media_id": "actually-published-photo",
            "publication_media_url": "published.jpg", "publication_text": "Published text",
            "publication_status": "published", "publication_media_type": "image",
        })
        self.assertEqual(preview["media_id"], "actually-published-photo")
        self.assertEqual(preview["media_url"], "published.jpg")
        self.assertEqual(preview["post_text"], "Published text")
        self.assertEqual(preview["status"], "published")

    def test_publication_without_photo_never_uses_generated_gallery_photo(self):
        preview = {"media_id": "unused-photo", "media_url": "unused.jpg"}
        _apply_publication_preview(preview, {
            "publication_id": "publication", "publication_media_id": None,
            "publication_media_url": None, "publication_status": "published",
        })
        self.assertEqual(preview["media_id"], "")
        self.assertEqual(preview["media_url"], "")

    def test_draft_retains_selected_gallery_media(self):
        preview = {"media_id": "selected-photo", "media_url": "draft.jpg"}
        _apply_publication_preview(preview, {})
        self.assertEqual(preview, {"media_id": "selected-photo", "media_url": "draft.jpg"})

    def test_scheduled_video_uses_saved_video(self):
        preview = {"media_type": "image", "media_id": "draft-photo"}
        _apply_publication_preview(preview, {
            "publication_id": "publication", "publication_media_id": "video",
            "publication_status": "scheduled", "publication_media_type": "video",
        })
        self.assertEqual(preview["media_type"], "video")
        self.assertEqual(preview["media_id"], "video")
        self.assertEqual(preview["status"], "scheduled")
