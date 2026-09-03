"""
Configuration du journal applicatif.

Problème résolu : uvicorn installe sa propre configuration de logging au
démarrage (`disable_existing_loggers`), ce qui rendait muets tous les
loggers de l'application. Résultat : aucune trace de `mailer`, `worker`,
`auth`... dans journalctl, et donc aucun diagnostic possible.

On force ici une configuration explicite, appliquée APRÈS celle d'uvicorn
(au lifespan), avec un format lisible dans journalctl.
"""
from __future__ import annotations

import logging
import sys

APP_LOGGERS = (
    "app",
    "app.migrations",
    "auth",
    "services.ai",
    "services.mailer",
    "worker.calendar",
    "worker.scheduler",
    "worker.validation",
    "worker.instagram_refresh",
)

FORMAT = "%(levelname)-8s %(name)-22s %(message)s"


def setup_logging(level: str = "info") -> None:
    numeric = getattr(logging, str(level).upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(FORMAT))

    root = logging.getLogger()
    root.setLevel(numeric)
    # Évite les doublons si la fonction est appelée deux fois
    for h in list(root.handlers):
        if getattr(h, "_pg_handler", False):
            root.removeHandler(h)
    handler._pg_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)

    # Réactive explicitement chaque logger applicatif : uvicorn a pu les
    # désactiver via disable_existing_loggers.
    for name in APP_LOGGERS:
        lg = logging.getLogger(name)
        lg.disabled = False
        lg.setLevel(numeric)
        lg.propagate = True

    # Bruit inutile en INFO
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    logging.getLogger("app").info(
        "Journalisation active (niveau %s) — les messages mailer/worker/auth "
        "apparaissent désormais dans journalctl", level.upper())
