import json
import unittest
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

from app.dependencies.auth import require_auth
from app.i18n import SUPPORTED_LOCALES, translate
from app.routers.posts import router
from app.services import brand_profiles


class Controls(HTMLParser):
    def __init__(self, text):
        super().__init__(); self.controls={}; self.feed(text)
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='input' and attrs.get('name'):
            self.controls[attrs['name']]=attrs


class BrandProfileTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_and_save_are_scoped_to_user_and_company(self):
        conn=AsyncMock()
        conn.fetchval.return_value=json.dumps({'company':'Example', 'constraints':'', 'use_macaron':False, 'auto_apply':True})
        pool=MagicMock(); pool.acquire.return_value.__aenter__=AsyncMock(return_value=conn)
        with patch.object(brand_profiles,'get_pool',return_value=pool):
            profile=await brand_profiles.load_brand_profile('user-A','company-A')
            self.assertFalse(profile['use_macaron'])
            self.assertEqual(profile['constraints'],'')
            self.assertEqual(conn.fetchval.await_args.args[1:],('user-A','company-A'))
            await brand_profiles.save_brand_profile('user-B','company-B',brand_profiles.BrandProfile(**profile))
            self.assertEqual(conn.execute.await_args.args[1:3],('user-B','company-B'))
            self.assertIn('ON CONFLICT (user_id,workspace_id)',conn.execute.await_args.args[0])

    def test_endpoint_uses_authenticated_scope_and_rejects_foreign_identifiers(self):
        app=FastAPI(); app.include_router(router,prefix='/app')
        app.dependency_overrides[require_auth]=lambda:SimpleNamespace(id='user',active_workspace_id='company')
        client=TestClient(app)
        with patch('app.routers.posts.save_brand_profile',new_callable=AsyncMock) as save:
            payload={'company':'Example','use_macaron':False,'auto_apply':True,'constraints':''}
            response=client.post('/app/posts/brand-profile',json=payload)
            self.assertEqual(response.status_code,200)
            self.assertEqual(save.await_args.args[:2],('user','company'))
            self.assertFalse(response.json()['data']['use_macaron'])
            for invalid in [{**payload,'workspace_id':'foreign'}, {**payload,'constraints':'x'*901}, {**payload,'auto_apply':'false'}]:
                self.assertEqual(client.post('/app/posts/brand-profile',json=invalid).status_code,422)
            self.assertEqual(save.await_count,1)

    def test_prefill_is_opt_in_and_preserves_disabled_macaron_in_all_languages(self):
        env=Environment(loader=ChoiceLoader([DictLoader({'base.html':'{% block content %}{% endblock %}'}),FileSystemLoader('templates')]),autoescape=True)
        template=env.get_template('posts/new.html')
        for locale in SUPPORTED_LOCALES:
            for enabled in (False,True):
                profile=brand_profiles.BrandProfile(company='Example "Brand"',constraints='',use_macaron=False,auto_apply=enabled).model_dump()
                html=template.render(t=lambda key,**kw:translate(key,locale,**kw),brand_profile=profile,
                    auth_user=SimpleNamespace(macaron_enabled=True,macaron_url='',macaron_position_display='Bottom right'))
                controls=Controls(html).controls
                self.assertEqual(controls['company']['value'],'Example "Brand"' if enabled else '')
                self.assertEqual('checked' in controls['use_macaron'],not enabled)
                self.assertNotIn('js.brand.',html)
