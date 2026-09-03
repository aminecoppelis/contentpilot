"""
Port fidèle des mécanismes de sécurité du workflow n8n original.
Référence : Cahier technique §3, Addendum §3.

Toute modification de ce fichier doit être justifiée par rapport au
comportement documenté — c'est le module le plus sensible du portage.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import re
import time
from urllib.parse import urlencode

import bcrypt

# ---------------------------------------------------------------------------
# Mots de passe (bcrypt, coût 10 — équivalent de crypt(pwd, gen_salt('bf',10)))
# ---------------------------------------------------------------------------

BCRYPT_ROUNDS = 10


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Sessions — jeton opaque côté cookie, seul le hash SHA-256 est stocké en base
# (Cahier technique §3.5 / §4.2, Addendum §6.4)
# ---------------------------------------------------------------------------

def new_session_token() -> str:
    """256 bits d'aléatoire, encodés hex (équivalent gen_random_bytes(32))."""
    return secrets.token_hex(32)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def session_token_hash(raw_token: str) -> str:
    return sha256_hex(raw_token)


def request_auth_token(session_id: str, session_token_hash_value: str) -> str:
    """
    request_token = SHA256(session_id + ':' + session_token_hash)
    Permet l'authentification des appels fetch() sans exposer le cookie brut
    (mécanisme de secours documenté en Cahier technique §4.2).
    """
    return sha256_hex(f"{session_id}:{session_token_hash_value}")


# ---------------------------------------------------------------------------
# Jetons d'activation de compte (Cahier technique §3.4)
# ---------------------------------------------------------------------------

def new_activation_token() -> str:
    return secrets.token_hex(32)


def activation_token_hash(raw_token: str) -> str:
    return sha256_hex(raw_token)


# ---------------------------------------------------------------------------
# Anti-bot des formulaires (honeypot + délai minimal) — Cahier technique §3.3
# Port exact de la fonction JS `antiBotOk` de AUTH - Préparer Login/Register.
# ---------------------------------------------------------------------------

MIN_FORM_ELAPSED_MS = 1_200
MAX_FORM_ELAPSED_MS = 7_200_000  # 2h


def anti_bot_ok(form_started_at_ms: int | None, honeypot_value: str) -> bool:
    honeypot = (honeypot_value or "").strip()
    if honeypot:
        return False
    if not form_started_at_ms or form_started_at_ms <= 0:
        return False
    elapsed = int(time.time() * 1000) - form_started_at_ms
    return MIN_FORM_ELAPSED_MS <= elapsed <= MAX_FORM_ELAPSED_MS


# ---------------------------------------------------------------------------
# Redirections sûres — anti open-redirect (Cahier technique §3.6)
# ---------------------------------------------------------------------------

SAFE_REDIRECT_PREFIX = "/app/"       # équivalent du '/webhook/V0/' original
SAFE_REDIRECT_DEFAULT = "/app/dashboard"


def safe_redirect(value: str | None) -> str:
    raw = (value or "").strip()
    if raw.startswith(SAFE_REDIRECT_PREFIX) and not raw.startswith("//"):
        return raw
    return SAFE_REDIRECT_DEFAULT


def login_url(redirect_to: str) -> str:
    return f"/app/login?{urlencode({'redirect': redirect_to})}"


# ---------------------------------------------------------------------------
# Anti brute-force — paliers de verrouillage progressif (Cahier technique §3.2)
# Implémenté ici en Python pour référence/tests ; la logique réelle utilisée
# par la route /login est portée en SQL dans sql/auth/login.sql (fidélité
# transactionnelle exacte : lecture + verrouillage + écriture atomiques).
# ---------------------------------------------------------------------------

LOCK_LEVEL_MINUTES = {1: 1, 2: 5, 3: 15, 4: 30}  # >=5 -> 60 (voir clause SQL)


def lock_duration_minutes(lock_level: int) -> int:
    return LOCK_LEVEL_MINUTES.get(lock_level, 60)


# ---------------------------------------------------------------------------
# Email / mot de passe — validations de formulaire (Cahier technique §4.4)
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def is_valid_email(value: str) -> bool:
    return bool(_EMAIL_RE.match((value or "").strip()))


def is_valid_password(value: str) -> bool:
    return len(value or "") >= 10


# ---------------------------------------------------------------------------
# OAuth anti-CSRF (state) — Cahier technique §3.7
# ---------------------------------------------------------------------------

def new_oauth_state() -> str:
    return secrets.token_urlsafe(32)


def oauth_state_hash(raw_state: str) -> str:
    return sha256_hex(raw_state)


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a or "", b or "")
