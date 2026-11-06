from types import SimpleNamespace
import unittest
from app.i18n import SUPPORTED_LOCALES, translate
from app.templating import templates


class CalendarAccountsUXTests(unittest.TestCase):
    def test_buffer_configuration_is_visible_only_to_owner_without_duplicate(self):
        base = dict(id='account-id', provider='buffer', is_buffer=True, display_name='Example account',
                    external_account_id='channel-id', is_active=True, is_owner_workspace=True,
                    provider_label='Buffer', token_expired=False, token_temporary=False)
        for locale in SUPPORTED_LOCALES:
            t = lambda key, **kwargs: translate(key, locale, **kwargs)
            own = templates.get_template('networks/_account_rows.html').render(accounts=[base], t=t)
            shared = templates.get_template('networks/_account_rows.html').render(
                accounts=[{**base, 'is_owner_workspace': False}], t=t)
            self.assertEqual(own.count('data-buffer-edit="1"'), 1)
            self.assertIn('window.openBufferModalFromButton(this)', own)
            self.assertNotIn('data-buffer-edit="1"', shared)
            self.assertIn(translate('js.connections.shared', locale), shared)
            self.assertIn('toggleNetwork(', own)
            self.assertIn('removeNetworkFromWorkspace(', shared)
            self.assertNotIn('<div class="mini">account-id</div>', own)
            self.assertNotIn('js.connections.', own)

    def test_calendar_filter_scope_and_native_date_fallback_remain_available(self):
        for locale in SUPPORTED_LOCALES:
            html = templates.get_template('strategies/_publication_calendar.html').render(
                t=lambda key, **kwargs: translate(key, locale, **kwargs),
                auth_user=SimpleNamespace(timezone='Europe/Paris'))
            self.assertIn('id="publicationCalendarResetFilters"', html)
            self.assertIn('id="publicationCalendarFilterScope"', html)
            self.assertIn('type="datetime-local" id="publicationCalendarDate"', html)
            self.assertNotIn('js.calendar.', html)
