import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader

from app.i18n import translate
from app.routers.legal import router, document_html


class LegalPagesTests(unittest.TestCase):
    def setUp(self):
        app=FastAPI();app.include_router(router);app.include_router(router,prefix='/app',include_in_schema=False)
        self.client=TestClient(app)

    def test_public_documents_in_both_languages_without_database(self):
        with patch('app.database.get_pool') as pool:
            for prefix in ('','/app'):
                for document,last_section in [('privacy',13),('terms',14)]:
                    for lang in ('fr','en'):
                        response=self.client.get(prefix+'/'+document,params={'lang':lang})
                        self.assertEqual(response.status_code,200)
                        self.assertIn('<html lang="'+lang+'">',response.text)
                        self.assertIn('<h2>'+str(last_section)+'. Contact</h2>',response.text)
                        self.assertIn('mailto:contact_customer@actifpilot.com',response.text)
                        self.assertIn('COPPELIS SARL',response.text)
                        if document == 'terms':
                            self.assertIn('09/03/2026' if lang == 'fr' else '9 March 2026', response.text)
                            self.assertIn('750 132 946', response.text)
                        else:
                            self.assertIn('23/11/2026' if lang == 'fr' else '23 November 2026', response.text)
                            self.assertIn('SocialAI', response.text)
                            self.assertIn('youtube.readonly', response.text)
                            self.assertIn('youtube.upload', response.text)
                            self.assertIn('href="https://security.google.com/settings/security/permissions"', response.text)
            pool.assert_not_called()

    def test_footers_have_requested_links_and_language(self):
        env=Environment(loader=FileSystemLoader('templates'),autoescape=True)
        template=env.get_template('partials/auth_legal.html')
        for locale in ('fr','en'):
            html=template.render(locale=locale,t=lambda key,**kw:translate(key,locale,**kw))
            for page in ('privacy','terms'):
                self.assertIn('href="/'+page+'?lang='+locale+'"',html)
            self.assertNotIn('https://actifpilot.com',html)
            self.assertNotIn('href="#"',html)
            self.assertIn('<strong>',html)
        for name in ('login.html','register.html'):
            self.assertIn("include 'partials/auth_legal.html'",Path('templates',name).read_text(encoding='utf-8'))

    def test_document_text_cannot_inject_markup(self):
        rendered=str(document_html('1. Title\n\n<script>alert(1)</script>\n\n- Item'))
        self.assertNotIn('<script>',rendered)
        self.assertIn('&lt;script&gt;',rendered)
        self.assertIn('<ul><li>Item</li></ul>',rendered)
