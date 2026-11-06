from pathlib import Path
from types import SimpleNamespace
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from app.i18n import SUPPORTED_LOCALES, translate


def render(locale, platform='linkedin', read_only=False):
    env = Environment(loader=ChoiceLoader([
        DictLoader({'base.html': '{% block content %}{% endblock %}'}), FileSystemLoader('templates')]))
    ideas = [dict(idea_id=f'idea-{i}', full_text=f'Example text {i}', post_title=f'Example {i}',
                  title=f'Example {i}', recommended_format='Post', status_cls='generated',
                  status_label='Draft', media=[], scores_list=[], seo_keywords=[],
                  is_published=False, is_scheduled=False) for i in range(2)]
    return env.get_template('posts/view.html').render(
        t=lambda key, **kwargs: translate(key, locale, **kwargs),
        ideas=ideas, ideas_json=ideas, request_id='request', page_heading='Example subject',
        single_idea_view=False, read_only=read_only, generation_in_progress=False,
        generation_failed=False, background_jobs=[], generated_count=2, expected_count=2,
        origin_context={'platform': platform, 'account_name': 'Example account'},
        auth_user=SimpleNamespace(timezone='Europe/Paris'),
    )


if __name__ == '__main__':
    for locale in SUPPORTED_LOCALES:
        Path(f'.cache/editor-{locale}.html').write_text(render(locale), encoding='utf-8')
