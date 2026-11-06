import unittest
from tests.render_editor_fixtures import render
from app.i18n import SUPPORTED_LOCALES


class EditorPresentationTests(unittest.TestCase):
    def test_preview_contains_no_simulated_engagement(self):
        for locale in SUPPORTED_LOCALES:
            for platform in ['linkedin', 'facebook', 'instagram']:
                html = render(locale, platform)
                self.assertNotIn('class="lpStats"', html)
                self.assertNotIn('class="lpLikes"', html)
                self.assertNotIn('js.editor.', html)
                self.assertIn('postPreviewNotice', html)
                self.assertIn('id="copy-0"', html)
                self.assertIn('id="publish-btn-0"', html)

    def test_read_only_has_no_publish_actions_or_broken_status_description(self):
        html = render('fr', read_only=True)
        self.assertNotIn('id="publish-btn-', html)
        self.assertNotIn('aria-describedby="post-edit-status-', html)
        self.assertIn('readonly aria-readonly="true"', html)
