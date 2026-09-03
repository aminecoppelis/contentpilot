"""
Point d'entrée FastAPI — assemble tous les routeurs, le scheduler (Worker +
crons), les templates Jinja2 et les fichiers statiques.

Architecture (Cahier technique §1) :
  - Toutes les routes métier sont montées sous le préfixe /app (équivalent
    du /webhook/V0 original).
  - Le Worker et les crons tournent dans le MÊME process par défaut (via
    APScheduler, démarré au lifespan). Pour une charge de production plus
    importante, ils peuvent être extraits en process séparé en réutilisant
    tel quel app/worker/* (voir Addendum §8 recommandations infra).
"""
from __future__ import annotations

import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import HTTPException
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import get_settings
from app.database import init_pool, close_pool, get_pool
from app.migrations import apply_pending
from app.logging_config import setup_logging
from app.dependencies.auth import AuthRequiredHTML
from app.worker.scheduler import start_scheduler, shutdown_scheduler

from app.routers import (auth, posts, media, publish, networks, strategies, workspace,
                          admin, listing, media_proxy)

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Doit précéder toute autre initialisation : uvicorn a déjà installé sa
    # propre configuration de logging, qui rendait les loggers applicatifs muets.
    setup_logging(get_settings().log_level)

    media_dir = get_settings().media_storage_path
    media_dir.mkdir(parents=True, exist_ok=True)
    await init_pool()
    logger.info("Pool DB initialisé")

    # Applique les migrations manquantes avant de servir la moindre requête.
    # Évite qu'une colonne ajoutée dans une migration récente manque en base
    # parce que install.sh n'a pas été relancé après une mise à jour du code.
    if get_settings().auto_migrate:
        try:
            await apply_pending(get_pool())
        except Exception:  # noqa: BLE001
            logger.exception(
                "Migrations impossibles à appliquer — démarrage interrompu. "
                "Corrige le schéma puis relance (ou mets AUTO_MIGRATE=false).")
            raise
    else:
        logger.info("AUTO_MIGRATE=false — migrations non appliquées automatiquement")
    if get_settings().disable_scheduler:
        logger.warning("Scheduler désactivé (DISABLE_SCHEDULER=1) : "
                       "worker de génération et crons NON démarrés")
    else:
        start_scheduler()
    yield
    if not get_settings().disable_scheduler:
        shutdown_scheduler()
    await close_pool()
    logger.info("Arrêt propre de l'application")


app = FastAPI(title="Post Generator", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")
# Route canonique des fichiers générés. Le stockage physique est
# <projet>/public-media/ par défaut.
app.mount("/public-media", StaticFiles(directory=str(get_settings().media_storage_path), check_dir=False), name="public-media")
# Alias de compatibilité pour les anciennes URLs éventuellement déjà stockées
# en base avant la migration. Il pointe vers LE MÊME dossier, sans duplication.
app.mount("/n8n-files/public-media", StaticFiles(directory=str(get_settings().media_storage_path), check_dir=False), name="legacy-public-media")
templates = Jinja2Templates(directory="templates")

# Tous les routeurs métier sous /app (équivalent du /webhook/V0 original)
for router in (auth.router, posts.router, media.router, publish.router,
               networks.router, strategies.router, workspace.router, admin.router,
               listing.router, media_proxy.router):
    app.include_router(router, prefix="/app")


@app.exception_handler(AuthRequiredHTML)
async def auth_required_html_handler(request: Request, exc: AuthRequiredHTML):
    return RedirectResponse(exc.redirect_to, status_code=302)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if isinstance(exc.detail, dict):
        return JSONResponse(exc.detail, status_code=exc.status_code)
    accepts_html = "text/html" in request.headers.get("accept", "")
    if accepts_html:
        return _render_error_page(
            request,
            badge="Erreur " + str(exc.status_code),
            title="Page introuvable" if exc.status_code == 404 else "Une erreur est survenue",
            message=str(exc.detail or "La ressource demandée n'est pas disponible."),
            status_code=exc.status_code,
        )
    return JSONResponse({"success": False, "error": "HTTP_ERROR", "message": str(exc.detail)},
                        status_code=exc.status_code)


def _render_error_page(request: Request, *, badge: str, title: str, message: str,
                        detail: str = "", status_code: int = 500):
    """Port de "GLOBAL - Construire Error Page" / "GLOBAL - GET Not Found"."""
    return templates.TemplateResponse(request, "error.html", {
        "badge": badge, "title": title, "message": message, "detail": detail,
        "back": "/app/dashboard",
    }, status_code=status_code)


@app.get("/app/error")
async def get_error_page(request: Request, message: str | None = None, detail: str | None = None):
    return _render_error_page(
        request, badge="Erreur", title="Une erreur est survenue",
        message=message or "Le traitement n'a pas pu aboutir.", detail=detail or "", status_code=200)


@app.get("/app/not-found")
async def get_not_found_page(request: Request):
    return _render_error_page(
        request, badge="Erreur 404", title="Page introuvable",
        message="La page demandée n'existe pas ou a été déplacée.", status_code=404)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return RedirectResponse("/app/dashboard", status_code=302)
