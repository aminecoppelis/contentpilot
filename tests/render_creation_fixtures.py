"""Render presentation-only fixtures for the browser DOM test; no app startup or API calls."""
from pathlib import Path
from types import SimpleNamespace
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from app.i18n import SUPPORTED_LOCALES, translate


def render(locale):
    env = Environment(loader=ChoiceLoader([
        DictLoader({'base.html': '{% block content %}{% endblock %}'}),
        FileSystemLoader('templates'),
    ]))
    return env.get_template('posts/new.html').render(
        t=lambda key, **kwargs: translate(key, locale, **kwargs),
        auth_user=SimpleNamespace(macaron_enabled=True, macaron_url='', macaron_position_display='Bottom right'),
    )


if __name__ == '__main__':
    Path('.cache').mkdir(exist_ok=True)
    for locale in SUPPORTED_LOCALES:
        Path(f'.cache/creation-{locale}.html').write_text(render(locale), encoding='utf-8')
