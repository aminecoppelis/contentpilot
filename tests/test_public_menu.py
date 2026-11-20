import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.i18n import SUPPORTED_LOCALES, translate
from app.routers import auth, legal, public_pages


class PublicMenuTests(unittest.TestCase):
    def setUp(self):
        app=FastAPI();app.include_router(public_pages.router);app.include_router(legal.router);app.include_router(auth.router,prefix='/app')
        self.client=TestClient(app)

    def test_public_pages_have_local_links_and_all_languages(self):
        for locale in SUPPORTED_LOCALES:
            for page in ['','offers','how-it-works','gdpr','pricing','contact']:
                response=self.client.get('/'+page,params={'lang':locale})
                self.assertEqual(response.status_code,200)
                html=response.text
                self.assertIn('lang="'+locale+'"',html)
                for destination in ['','offers','how-it-works','gdpr','pricing','contact']:
                    self.assertIn('href="/'+destination+'?lang='+locale+'"',html)
                self.assertIn('href="/'+page+'?lang='+locale+'" aria-current="page"',html)
                self.assertIn('href="/app/login?lang='+locale+'"',html)
                self.assertIn('href="/app/register?lang='+locale+'"',html)
                self.assertNotIn('https://actifpilot.com/',html)
                self.assertNotIn('js.public.',html)
                self.assertNotIn('js.site.',html)
                self.assertIn('class="publicFooter"',html)
                self.assertIn('/static/css/public-site.css',html)
                self.assertIn('family=Inter',html)
                self.assertGreaterEqual(html.count('<section'),4)
                self.assertEqual(html.count('<h1>'),1)
                for language in SUPPORTED_LOCALES:self.assertIn('value="'+language+'"',html)
                if locale=='ar':self.assertIn('dir="rtl"',html)

    def test_home_is_public_and_does_not_redirect_to_dashboard(self):
        response=self.client.get('/?lang=fr',follow_redirects=False)
        self.assertEqual(response.status_code,200)
        self.assertNotIn('location',response.headers)
        self.assertIn('publicHomeHero',response.text)
        self.assertIn(translate('js.site.home_title','fr'),response.text)
        self.assertIn('Illustration du parcours',response.text)

    def test_contact_prepares_email_without_claiming_delivery(self):
        html=self.client.get('/contact?lang=fr').text
        self.assertIn('id="publicContactForm"',html)
        for name in ['name','email','company','phone','subject','message']:
            self.assertIn('name="'+name+'"',html)
        self.assertIn(translate('js.site.contact_hint','fr'),html)
        self.assertIn('mailto:contact_customer@actifpilot.com',html)

    def test_pricing_does_not_copy_another_products_prices(self):
        html=self.client.get('/pricing?lang=fr').text
        for value in ['9€','29€','SSO','SLA','100% conforme']:
            self.assertNotIn(value,html)
        self.assertIn(translate('js.site.pricing_note','fr'),html)

    def test_authentication_pages_share_the_menu_and_keep_login_redirect(self):
        for path in ['/app/login','/app/register']:
            for locale in SUPPORTED_LOCALES:
                html=self.client.get(path,params={'lang':locale,'redirect':'/app/posts/new'}).text
                self.assertIn('class="publicHeader"',html)
                self.assertIn('lang="'+locale+'"',html)
                self.assertEqual(html.count('id="publicLanguage"'),1)
                self.assertNotIn('class="authLangSelect"',html)
                self.assertIn('name="redirect" value="/app/posts/new"',html)
                self.assertIn(translate('js.public.signup',locale),html)
