"""
Cron de rafraîchissement automatique des jetons Instagram — toutes les 6h,
à la 17e minute (Cahier technique §7.8), afin de désynchroniser ce job des
tâches système lancées pile à l'heure ronde.

Sélectionne les comptes Instagram dont le jeton longue durée approche de
l'expiration, appelle l'endpoint Meta de rafraîchissement, et met à jour
`token_ciphertext` / `token_expires_at`.
"""
from __future__ import annotations

import logging

from app.database import get_pool
from app.services.meta import refresh_instagram_long_lived_token
from app.services.crypto import encrypt_token, decrypt_token

logger = logging.getLogger("worker.instagram_refresh")

REFRESH_WINDOW_DAYS = 7  # rafraîchir les jetons expirant dans les 7 prochains jours

SELECT_ACCOUNTS_SQL = """
SELECT id::text, workspace_id::text, token_ciphertext, external_account_id
FROM public.app_social_accounts
WHERE provider = 'instagram'
  AND is_active = true
  AND deleted_at IS NULL
  AND token_expires_at IS NOT NULL
  AND token_expires_at <= now() + make_interval(days => $1::int)
ORDER BY token_expires_at ASC
LIMIT 100;
"""

UPDATE_TOKEN_SQL = """
UPDATE public.app_social_accounts
SET token_ciphertext = $2::text,
    token_expires_at = $3::timestamptz,
    updated_at = now()
WHERE id = $1::uuid;
"""


async def run_instagram_refresh_cycle() -> dict:
    pool = get_pool()
    refreshed = 0
    errors = 0

    async with pool.acquire() as conn:
        rows = await conn.fetch(SELECT_ACCOUNTS_SQL, REFRESH_WINDOW_DAYS)

    for row in rows:
        try:
            current_token = decrypt_token(row["token_ciphertext"])
            new_token, expires_at = await refresh_instagram_long_lived_token(current_token)
            new_ciphertext = encrypt_token(new_token)
            async with pool.acquire() as conn:
                await conn.execute(UPDATE_TOKEN_SQL, row["id"], new_ciphertext, expires_at)
            refreshed += 1
        except Exception:  # noqa: BLE001
            logger.exception("Instagram refresh: échec pour account_id=%s", row["id"])
            errors += 1

    return {"candidates": len(rows), "refreshed": refreshed, "errors": errors}
