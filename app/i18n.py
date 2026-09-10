"""
Internationalisation — catalogues JSON dynamiques.

- Les traductions vivent dans `translations/<locale>.json` (clés plates
  pointées, ex. "nav.dashboard").
- `translate(key, locale, **params)` : lookup dans la locale demandée, repli
  sur la locale par défaut, puis sur la clé elle-même. Interpolation via
  str.format(**params).
- La locale d'une requête est résolue par `resolve_locale(request)` :
  `?lang=` > cookie `pg_lang` > en-tête Accept-Language > défaut.
- Rechargement à chaud si `RELOAD_TRANSLATIONS=1` (dev).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("app.i18n")

TRANSLATIONS_DIR = Path(__file__).resolve().parent.parent / "translations"

DEFAULT_LOCALE = "fr"
SUPPORTED_LOCALES = ["fr", "en", "ar"]
LOCALE_NAMES = {"fr": "Français", "en": "English", "ar": "العربية"}
LOCALE_SHORT = {"fr": "FR", "en": "EN", "ar": "AR"}
RTL_LOCALES = {"ar", "he", "fa", "ur"}

COOKIE_NAME = "pg_lang"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365

_CATALOGS: dict[str, dict[str, str]] = {}
# Empreinte (mtime) des fichiers au dernier chargement + horodatage de la
# dernière vérification, pour un rechargement à chaud sans redémarrage.
_CATALOG_MTIMES: dict[str, float] = {}
_LAST_CHECK: float = 0.0
_CHECK_INTERVAL = 1.0  # secondes : au plus une vérification disque par seconde


def _current_mtimes() -> dict[str, float]:
    out: dict[str, float] = {}
    for loc in SUPPORTED_LOCALES:
        try:
            out[loc] = (TRANSLATIONS_DIR / f"{loc}.json").stat().st_mtime
        except OSError:
            out[loc] = 0.0
    return out


def _maybe_reload() -> None:
    """Recharge les catalogues si un fichier JSON a changé sur le disque.
    Throttlé à une vérification par seconde. Rend les modifications de
    traduction visibles sans redémarrer le serveur (uvicorn --reload ne
    surveille que les .py)."""
    global _LAST_CHECK
    import time

    now = time.monotonic()
    if now - _LAST_CHECK < _CHECK_INTERVAL:
        return
    _LAST_CHECK = now
    if _current_mtimes() != _CATALOG_MTIMES:
        load_all()


def _load_catalog(locale: str) -> dict[str, str]:
    path = TRANSLATIONS_DIR / f"{locale}.json"
    if not path.is_file():
        logger.warning("Catalogue de traduction manquant : %s", path)
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Catalogue %s illisible : %s", path, exc)
        return {}
    # Aplatit un éventuel JSON imbriqué en clés pointées.
    flat: dict[str, str] = {}

    def _walk(prefix: str, node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                _walk(f"{prefix}.{k}" if prefix else k, v)
        else:
            flat[prefix] = str(node)

    _walk("", data)
    return flat


def load_all() -> None:
    _CATALOGS.clear()
    for loc in SUPPORTED_LOCALES:
        _CATALOGS[loc] = _load_catalog(loc)
    _CATALOG_MTIMES.clear()
    _CATALOG_MTIMES.update(_current_mtimes())
    logger.info(
        "Traductions chargées : %s",
        ", ".join(f"{loc}={len(_CATALOGS.get(loc, {}))}" for loc in SUPPORTED_LOCALES),
    )


def normalize_locale(value: str | None) -> str:
    if not value:
        return DEFAULT_LOCALE
    code = value.strip().lower().replace("_", "-").split("-")[0]
    return code if code in SUPPORTED_LOCALES else DEFAULT_LOCALE


def is_supported(value: str | None) -> bool:
    return bool(value) and value.strip().lower() in SUPPORTED_LOCALES


def text_dir(locale: str) -> str:
    return "rtl" if normalize_locale(locale) in RTL_LOCALES else "ltr"


def translate(key: str, locale: str = DEFAULT_LOCALE, **params: Any) -> str:
    if os.environ.get("RELOAD_TRANSLATIONS") == "1":
        load_all()
    else:
        _maybe_reload()
    loc = normalize_locale(locale)
    catalog = _CATALOGS.get(loc) or {}
    value = catalog.get(key)
    if value is None and loc != DEFAULT_LOCALE:
        value = (_CATALOGS.get(DEFAULT_LOCALE) or {}).get(key)
    if value is None:
        value = key  # dernier repli : la clé brute, visible = à traduire
    if params:
        try:
            return value.format(**params)
        except (KeyError, IndexError, ValueError):
            return value
    return value


def js_catalog(locale: str = DEFAULT_LOCALE) -> dict[str, str]:
    """Sous-ensemble `js.*` du catalogue, injecté dans les pages pour le
    JavaScript (via window.__I18N)."""
    if os.environ.get("RELOAD_TRANSLATIONS") == "1":
        load_all()
    else:
        _maybe_reload()
    loc = normalize_locale(locale)
    catalog = _CATALOGS.get(loc) or {}
    fallback = _CATALOGS.get(DEFAULT_LOCALE) or {}
    keys = set(catalog) | set(fallback)
    return {k: catalog.get(k, fallback.get(k, k)) for k in keys if k.startswith("js.")}


def _accept_language_locale(header: str | None) -> str | None:
    if not header:
        return None
    for part in header.split(","):
        code = part.split(";")[0].strip().lower().split("-")[0]
        if code in SUPPORTED_LOCALES:
            return code
    return None


def resolve_locale(request) -> str:
    """Priorité : ?lang= > cookie pg_lang > Accept-Language > défaut."""
    try:
        q = request.query_params.get("lang")
        if is_supported(q):
            return normalize_locale(q)
    except Exception:  # noqa: BLE001
        pass
    try:
        c = request.cookies.get(COOKIE_NAME)
        if is_supported(c):
            return normalize_locale(c)
    except Exception:  # noqa: BLE001
        pass
    try:
        h = _accept_language_locale(request.headers.get("accept-language"))
        if h:
            return h
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_LOCALE


# Chargement initial à l'import du module.
load_all()
