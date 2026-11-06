from pathlib import Path
from types import SimpleNamespace
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from app.i18n import translate

if __name__ == '__main__':
    env = Environment(loader=ChoiceLoader([
        DictLoader({'base.html': '{% block content %}{% endblock %}'}), FileSystemLoader('templates')]))
    account = dict(id='account-id', provider='buffer', is_buffer=True, display_name='Example account',
                   external_account_id='channel-id', is_active=False, is_owner_workspace=True,
                   provider_label='Buffer', token_expired=False, token_temporary=False)
    html = env.get_template('networks/list.html').render(
        t=lambda key, **kwargs: translate(key, 'fr', **kwargs),
        accounts=[account], total=1, notice='', pagination=None, syncfusion_tables=False,
        auth_user=SimpleNamespace(is_super_admin=False))
    Path('.cache/networks-fixture.html').write_text(html, encoding='utf-8')
