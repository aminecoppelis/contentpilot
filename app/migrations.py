"""
Application automatique des migrations au démarrage.

Motivation : dépendre du fait que l'exploitant relance `install.sh` après une
mise à jour du code est fragile — c'est ainsi qu'une colonne ajoutée dans une
migration additive peut manquer en base et provoquer un
`UndefinedColumnError` au premier clic sur la fonctionnalité concernée.

Fonctionnement :
  - une table `schema_migrations` mémorise les fichiers déjà appliqués et
    l'empreinte SHA-256 de leur contenu ;
  - au démarrage, tout fichier `migrations/*.sql` non encore appliqué est
    exécuté dans une transaction unique (échec = annulation complète) ;
  - un fichier déjà appliqué dont le contenu a changé est signalé dans les
    logs mais pas rejoué, pour ne jamais écraser des données en silence.

Toutes les migrations du projet étant idempotentes (IF NOT EXISTS, blocs DO
protégés), une réexécution accidentelle resterait sans danger.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import asyncpg

logger = logging.getLogger("app.migrations")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

CREATE_TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS public.schema_migrations (
    filename    text PRIMARY KEY,
    checksum    text NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now()
)
"""


def _checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def apply_pending(pool: asyncpg.Pool) -> dict:
    """Applique les migrations manquantes. Retourne un résumé pour les logs."""
    if not MIGRATIONS_DIR.is_dir():
        logger.warning("Répertoire migrations/ introuvable — étape ignorée")
        return {"applied": [], "skipped": [], "modified": []}

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        return {"applied": [], "skipped": [], "modified": []}

    applied, skipped, modified = [], [], []

    async with pool.acquire() as conn:
        await conn.execute(CREATE_TRACKING_TABLE)
        known = {
            r["filename"]: r["checksum"]
            for r in await conn.fetch("SELECT filename, checksum FROM public.schema_migrations")
        }

    for path in files:
        content = path.read_text(encoding="utf-8")
        digest = _checksum(content)

        if path.name in known:
            if known[path.name] != digest:
                modified.append(path.name)
                logger.warning(
                    "Migration %s modifiée depuis son application — NON rejouée. "
                    "Crée un nouveau fichier plutôt que d'éditer celui-ci.", path.name)
            else:
                skipped.append(path.name)
            continue

        async with pool.acquire() as conn:
            try:
                async with conn.transaction():
                    await conn.execute(content)
                    await conn.execute(
                        "INSERT INTO public.schema_migrations (filename, checksum) "
                        "VALUES ($1, $2) ON CONFLICT (filename) DO UPDATE SET checksum = $2",
                        path.name, digest,
                    )
                applied.append(path.name)
                logger.info("Migration appliquée : %s", path.name)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Migration %s ÉCHOUÉE (transaction annulée, base intacte) : %s",
                    path.name, exc)
                raise

    if applied:
        logger.info("Migrations appliquées au démarrage : %s", ", ".join(applied))
    else:
        logger.info("Schéma déjà à jour (%d migration(s) connue(s))", len(skipped))

    return {"applied": applied, "skipped": skipped, "modified": modified}
