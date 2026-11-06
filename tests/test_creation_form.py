from collections import Counter
from html.parser import HTMLParser
import unittest
from tests.render_creation_fixtures import render
from app.i18n import SUPPORTED_LOCALES


class FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.controls = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            self.ids.append(attrs['id'])
        if tag in {'input', 'textarea', 'select'} and attrs.get('name'):
            self.controls[attrs['name']] = attrs


class CreationFormTests(unittest.TestCase):
    def test_fields_defaults_and_constraints_survive_in_all_languages(self):
        names = {'subject', 'theme', 'commercial_objective', 'language', 'post_count',
                 'target_sector', 'company', 'website', 'solution', 'default_tags',
                 'constraints', 'use_macaron'}
        for locale in SUPPORTED_LOCALES:
            html = render(locale)
            parser = FormParser()
            parser.feed(html)
            self.assertEqual(set(parser.controls), names)
            self.assertTrue(all(count == 1 for count in Counter(parser.ids).values()))
            self.assertEqual(parser.controls['post_count']['value'], '5')
            self.assertEqual(parser.controls['post_count']['max'], '8')
            self.assertEqual(parser.controls['theme']['maxlength'], '3500')
            self.assertEqual(parser.controls['constraints']['maxlength'], '900')
            self.assertIn('required', parser.controls['subject'])
            self.assertNotIn('js.creation.', html)
