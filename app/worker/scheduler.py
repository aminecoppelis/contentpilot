"""
Ordonnanceur des tâches planifiées — reproduit exactement les 3 triggers
cron du workflow original (Cahier technique §7.8-7.9, §8.1) :

  - Worker (génération auto)      : chaque minute        -> "* * * * *"
  - Validation (rappels email)    : toutes les 15 min     -> "*/15 * * * *"
  - Rafraîchissement Instagram    : toutes les 6h, min 17 -> "17 */6 * * *"

APScheduler est utilisé en mode AsyncIOScheduler, démarré depuis le lifespan
de l'application FastAPI (voir app/main.py). Le paramètre `max_instances=1`
sur chaque job empêche un chevauchement d'exécutions si un cycle dépasse son
intervalle (protection complémentaire au verrouillage SQL déjà en place).
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.worker.calendar_worker import run_cycle
from app.worker.validation_cron import run_validation_cycle
from app.worker.instagram_token_cron import run_instagram_refresh_cycle
from app.worker.media_video_cron import run_video_poll_cycle
from app.worker.media_image_cron import run_image_generation_cycle
from app.worker.publication_cron import run_publication_cycle
from app.worker.post_generation_cron import run_post_generation_cycle
from app.config import get_settings

logger = logging.getLogger("worker.scheduler")

scheduler = AsyncIOScheduler(timezone=get_settings().app_timezone)


async def _worker_job() -> None:
    try:
        result = await run_cycle()
        if result.get("stage") not in ("idle",):
            logger.info("Worker cycle: %s", result)
    except Exception:  # noqa: BLE001 - le job ne doit jamais tuer le scheduler
        logger.exception("Worker cycle: erreur non interceptée")


async def _validation_job() -> None:
    try:
        result = await run_validation_cycle()
        logger.info("Validation cycle: %s", result)
    except Exception:  # noqa: BLE001
        logger.exception("Validation cycle: erreur non interceptée")


async def _instagram_refresh_job() -> None:
    try:
        result = await run_instagram_refresh_cycle()
        logger.info("Instagram token refresh: %s", result)
    except Exception:  # noqa: BLE001
        logger.exception("Instagram token refresh: erreur non interceptée")



async def _media_image_job() -> None:
    try:
        result = await run_image_generation_cycle()
        if result.get("stage") not in ("idle",):
            logger.info("Image media cycle: %s", result)
    except Exception:  # noqa: BLE001
        logger.exception("Image media cycle: erreur non interceptée")


async def _media_video_job() -> None:
    try:
        result = await run_video_poll_cycle()
        if result.get("stage") not in ("idle",):
            logger.info("Video media cycle: %s", result)
    except Exception:  # noqa: BLE001
        logger.exception("Video media cycle: erreur non interceptée")


async def _post_generation_job() -> None:
    try:
        result = await run_post_generation_cycle()
        if result.get("stage") not in ("idle",):
            logger.info("Post generation cycle: %s", result)
    except Exception:  # noqa: BLE001
        logger.exception("Post generation cycle: erreur non interceptée")


async def _publication_job() -> None:
    try:
        result = await run_publication_cycle()
        if result.get("stage") not in ("idle",):
            logger.info("Scheduled publication cycle: %s", result)
    except Exception:  # noqa: BLE001
        logger.exception("Scheduled publication cycle: erreur non interceptée")

def start_scheduler() -> None:
    scheduler.add_job(
        _worker_job,
        CronTrigger.from_crontab("* * * * *"),
        id="calendar_worker",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )
    scheduler.add_job(
        _media_image_job,
        CronTrigger.from_crontab("* * * * *"),
        id="media_image_generation",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )
    scheduler.add_job(
        _media_video_job,
        CronTrigger.from_crontab("* * * * *"),
        id="media_video_poll",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )
    scheduler.add_job(
        _post_generation_job,
        CronTrigger.from_crontab("* * * * *"),
        id="post_generation_recovery",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )
    scheduler.add_job(
        _publication_job,
        CronTrigger.from_crontab("* * * * *"),
        id="scheduled_publications",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )
    scheduler.add_job(
        _validation_job,
        CronTrigger.from_crontab("*/15 * * * *"),
        id="validation_reminders",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )
    scheduler.add_job(
        _instagram_refresh_job,
        CronTrigger.from_crontab("17 */6 * * *"),
        id="instagram_token_refresh",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.start()
    logger.info("Scheduler démarré : calendar_worker(1min), post_generation(1min), media_image(1min), media_video(1min), publications(1min), validation(15min), instagram_refresh(6h@17)")


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
