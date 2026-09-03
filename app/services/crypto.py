"""
Chiffrement des jetons OAuth au repos (Cahier technique §3.8, Addendum §11).

Utilise Fernet (AES-128-CBC + HMAC, authentifié) au lieu du chiffrement
"clé stockée en base" de l'original, par défaut plus robuste — la clé est
lue depuis la configuration d'infrastructure (jamais en base ici).
Voir Addendum §11 pour la discussion du compromis sécurité/flexibilité.
"""
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    key = getattr(settings, "token_encryption_key", None)
    if not key:
        # Dérive une clé stable à partir de la clé OpenRouter en dev uniquement.
        # EN PRODUCTION : définir TOKEN_ENCRYPTION_KEY (Fernet.generate_key()).
        import hashlib
        import base64
        seed = hashlib.sha256((settings.database_url or "dev-seed").encode()).digest()
        key = base64.urlsafe_b64encode(seed)
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


def encrypt_token(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_token(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
