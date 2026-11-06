import unittest
from starlette.requests import Request
from app.ui_navigation import breadcrumb_items
from app.i18n import SUPPORTED_LOCALES,translate


class NavigationTests(unittest.TestCase):
    def request(self,path,query=b''):
        return Request({'type':'http','path':path,'scheme':'http','server':('test',80),'headers':[],'query_string':query})

    def test_strategy_and_post_parents_and_current_item(self):
        t=lambda key:translate(key,'fr')
        for path,query,parent in [('/app/posts/view',b'request_id=example','/app/posts'),('/app/strategies',b'strategy_id=example','/app/strategies')]:
            items=breadcrumb_items(self.request(path,query),t)
            self.assertEqual(items[1]['url'],parent)
            self.assertEqual(items[-1]['url'],'')
            self.assertEqual(len(items),3)

    def test_all_labels_exist_in_seven_languages(self):
        for locale in SUPPORTED_LOCALES:
            for path in ['/app/dashboard','/app/posts/new','/app/posts/view','/app/posts/edit','/app/posts/ideas-page','/app/strategies/new','/app/networks','/app/account','/app/workspace','/app/admin/users','/app/history']:
                items=breadcrumb_items(self.request(path),lambda key:translate(key,locale))
                self.assertTrue(items)
                for item in items:
                    self.assertFalse(item['text'].startswith(('js.','nav.','menu.','strat.')),(locale,path,item))
                    self.assertTrue(item['url']=='' or item['url'].startswith('/app/'))

    def test_unknown_route_does_not_invent_a_destination(self):
        self.assertEqual(breadcrumb_items(self.request('/app/unknown'),lambda key:key),[])
