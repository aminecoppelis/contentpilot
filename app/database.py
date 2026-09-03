"""
Pool de connexions PostgreSQL (asyncpg).

Toutes les requêtes métier critiques (auth, session, worker) sont conservées
sous forme de SQL brut dans /sql, port fidèle des requêtes originales du
workflow n8n (voir Cahier technique, Annexe B). On n'utilise volontairement
PAS d'ORM sur ces requêtes : elles reposent sur des CTE PostgreSQL complexes
(FOR UPDATE SKIP LOCKED, LATERAL, jsonb_build_object...) qu'un ORM classique
ne saurait pas générer sans les réécrire, ce qui casserait la fidélité
comportementale exigée.
"""
from __future__ import annotations

import asyncpg
from pathlib import Path
from functools import lru_cache

from app.config import get_settings

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=2,
            max_size=20,
            command_timeout=30,
            server_settings={"timezone": "UTC"},
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Le pool DB n'est pas initialisé — appeler init_pool() au démarrage.")
    return _pool


@lru_cache(maxsize=64)
def _read_sql(name: str) -> str:
    """Charge et met en cache le contenu d'un fichier .sql de /sql."""
    path = SQL_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Fichier SQL introuvable: {path}")
    return path.read_text(encoding="utf-8")


def sql(name: str) -> str:
    """Retourne le texte SQL du fichier `name` (ex: 'auth/login.sql')."""
    return _read_sql(name)
