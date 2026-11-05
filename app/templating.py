"""
Instance Jinja2 partagée par tous les routeurs (+ main.py).

Avant, chaque routeur créait son propre `Jinja2Templates(...)`, ce qui rendait
impossible l'ajout d'helpers globaux (i18n). Ici on centralise, et on branche
le contexte de traduction via un context_processor : chaque template reçoit
`t()`, `locale`, `dir`, et la liste des langues.
"""
from __future__ import annotations

from fastapi.templating import Jinja2Templates
from app.config import get_settings

from app.i18n import (
    DEFAULT_LOCALE,
    LOCALE_NAMES,
    LOCALE_SHORT,
    SUPPORTED_LOCALES,
    js_catalog,
    resolve_locale,
    text_dir,
    translate,
)


def _i18n_context(request) -> dict:
    locale = resolve_locale(request)
    license_key = get_settings().syncfusion_license_key.strip()
    grid_paths = {"/app/posts", "/app/published", "/app/strategies", "/app/networks", "/app/admin/users", "/app/workspace"}
    use_grid = bool(license_key and request.url.path in grid_paths
                    and not (request.url.path == "/app/strategies" and request.query_params.get("strategy_id")))
    post_flow = request.url.path == "/app/posts/view"
    publication_calendar = request.url.path == "/app/strategies" and bool(request.query_params.get("strategy_id"))

    def _t(key: str, **params) -> str:
        return translate(key, locale, **params)

    return {
        "t": _t,  # {{ t('nav.dashboard') }}  /  {{ t('hello', name=x) }}
        "locale": locale,
        "dir": text_dir(locale),
        "supported_locales": SUPPORTED_LOCALES,
        "locale_names": LOCALE_NAMES,
        "locale_short": LOCALE_SHORT,
        "js_catalog": js_catalog(locale),  # sous-ensemble js.* pour window.__I18N
        "syncfusion_license_key": license_key,
        "syncfusion_tables": use_grid,
        "post_flow": post_flow,
        "syncfusion_post_flow": bool(license_key and post_flow),
        "syncfusion_calendar": bool(license_key and publication_calendar),
    }


templates = Jinja2Templates(directory="templates", context_processors=[_i18n_context])

# Filet de sécurité : quelques routeurs rendent des fragments (lignes de
# tableau pour le scroll infini) via `templates.get_template(x).render(...)`,
# sans passer par TemplateResponse — donc sans `request`, donc sans
# context_processor. Sans ce repli, `t()` y serait indéfini et ferait
# planter le rendu. Ici, ces fragments s'affichent simplement en français ;
# TemplateResponse (avec request) écrase toujours ce repli par la bonne locale.
templates.env.globals.setdefault("t", lambda key, **params: translate(key, DEFAULT_LOCALE, **params))
templates.env.globals.setdefault("locale", DEFAULT_LOCALE)
templates.env.globals.setdefault("dir", text_dir(DEFAULT_LOCALE))
templates.env.globals.setdefault("supported_locales", SUPPORTED_LOCALES)
templates.env.globals.setdefault("locale_names", LOCALE_NAMES)
templates.env.globals.setdefault("locale_short", LOCALE_SHORT)
templates.env.globals.setdefault("js_catalog", js_catalog(DEFAULT_LOCALE))


def render_fragment(request, name: str, **context) -> str:
    """Rendu d'un fragment HTML (lignes de tableau pour le scroll infini) hors
    TemplateResponse — utiliser ceci plutôt que `templates.get_template(x).render(...)`
    directement, sinon `t()`/`locale`/`dir` retombent sur le français par défaut
    au lieu de la langue de la requête."""
    return templates.get_template(name).render(_i18n_context(request), **context)
