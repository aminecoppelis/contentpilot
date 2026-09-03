"""Gestion centralisée du fuseau horaire utilisateur.

Règle applicative :
- toutes les dates persistées restent des ``timestamptz`` (instant absolu/UTC) ;
- un ``datetime-local`` sans offset est interprété dans le fuseau IANA de
  l'utilisateur ;
- tout instant affiché est reconverti dans ce même fuseau.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings

UTC = timezone.utc


def valid_timezone_name(value: object) -> str | None:
    name = str(value or "").strip()
    if not name or len(name) > 100:
        return None
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return name


def normalize_timezone_name(value: object, fallback: str | None = None) -> str:
    valid = valid_timezone_name(value)
    if valid:
        return valid
    fallback_valid = valid_timezone_name(fallback)
    if fallback_valid:
        return fallback_valid
    configured = valid_timezone_name(get_settings().app_timezone)
    return configured or "UTC"


def request_timezone_name(request, fallback: str | None = None) -> str:
    """Résout le fuseau envoyé par le navigateur, puis le profil, puis l'app."""
    header = request.headers.get("X-PG-Timezone", "") if request is not None else ""
    cookie = request.cookies.get("pg_timezone", "") if request is not None else ""
    return normalize_timezone_name(header or cookie or fallback)


def zone(value: object) -> ZoneInfo:
    return ZoneInfo(normalize_timezone_name(value))


def to_user_datetime(value: datetime | None, timezone_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        # Les valeurs DB attendues sont des timestamptz. Si un driver/test fournit
        # malgré tout un datetime naïf, on l'interprète comme UTC, jamais comme le
        # fuseau du serveur Python.
        value = value.replace(tzinfo=UTC)
    return value.astimezone(zone(timezone_name))


def format_user_datetime(value: datetime | None, timezone_name: str,
                         fmt: str = "%d/%m/%Y %H:%M", empty: str = "") -> str:
    local = to_user_datetime(value, timezone_name)
    return local.strftime(fmt) if local else empty


def _roundtrips(naive: datetime, tz: ZoneInfo, fold: int) -> bool:
    aware = naive.replace(tzinfo=tz, fold=fold)
    back = aware.astimezone(UTC).astimezone(tz).replace(tzinfo=None)
    return back == naive


def parse_user_datetime(value: object, timezone_name: str) -> datetime:
    """Convertit une saisie utilisateur en UTC sans dépendre du fuseau serveur.

    Un ISO avec offset est un instant absolu. Un ISO sans offset (cas d'un
    ``datetime-local``) est interprété dans le fuseau IANA de l'utilisateur.
    Les heures inexistantes/ambiguës lors du changement DST sont refusées au
    lieu de choisir silencieusement le mauvais instant.
    """
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Date ou heure manquante.")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Date ou heure invalide.") from exc

    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC)

    tz = zone(timezone_name)
    fold0_ok = _roundtrips(parsed, tz, 0)
    fold1_ok = _roundtrips(parsed, tz, 1)
    if not fold0_ok and not fold1_ok:
        raise ValueError("Cette heure n’existe pas dans ton fuseau horaire à cause du changement d’heure.")

    aware0 = parsed.replace(tzinfo=tz, fold=0)
    aware1 = parsed.replace(tzinfo=tz, fold=1)
    if fold0_ok and fold1_ok and aware0.utcoffset() != aware1.utcoffset():
        raise ValueError("Cette heure est ambiguë dans ton fuseau horaire à cause du changement d’heure. Choisis une autre heure.")

    aware = aware0 if fold0_ok else aware1
    return aware.astimezone(UTC)


def coerce_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def format_user_value(value: object, timezone_name: str,
                      fmt: str = "%d/%m/%Y %H:%M", empty: str = "") -> str:
    return format_user_datetime(coerce_datetime(value), timezone_name, fmt, empty)
