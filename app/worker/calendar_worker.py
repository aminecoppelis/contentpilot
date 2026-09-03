"""
Worker planifié — moteur de génération automatique de contenu.
Port fidèle de l'algorithme documenté au Cahier technique §8 / Addendum §2.

Cycle exact (déclenché chaque minute par le scheduler, app/worker/scheduler.py) :
  1. Maintenance (auto-réparation idempotente)
  2. Réclamation atomique d'une tâche (FOR UPDATE SKIP LOCKED)
  3. Génération IA (agent "Worker - Generate with OpenRouter")
  4. Parsing strict du JSON retourné
  5. Sauvegarde (post_ideas + post_versions, idempotente)
  6. Liaison + clôture (post_ideas.current_version_id, post_requests, calendar)
  7. Passage en « À valider » + notification email immédiate à tous les membres actifs du workspace
  8. À chaque étape : gestion d'erreur uniforme -> retry (max 3) puis email d'alerte

IMPORTANT : ce module ne traite qu'UNE tâche par cycle (comme l'original,
qui réclame LIMIT 1). Le scheduler le rappelle toutes les minutes ; si le
volume l'exige, on peut appeler `run_cycle()` plusieurs fois par tick
(voir commentaire dans scheduler.py), au prix d'une revue de charge DB.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import asyncpg

from app.config import get_settings
from app.database import get_pool, sql
from app.services.ai import generate_worker_post, AIGenerationError
from app.services.ai_contracts import AIContractError, parse_worker_post_response
from app.services.mailer import send_worker_error_email, send_validation_reminder_email_raw

logger = logging.getLogger("worker.calendar")

# Anti-spam des alertes : le cron tourne chaque minute. Sans garde-fou, une
# panne persistante (base injoignable, identifiants invalides) génère 1 440
# emails par jour. On ne réémet une alerte identique qu'une fois par heure.
_LAST_ALERT: dict[str, float] = {}
ALERT_COOLDOWN_SECONDS = 3600


def _should_send_alert(signature: str) -> bool:
    import time
    now = time.time()
    last = _LAST_ALERT.get(signature, 0.0)
    if now - last < ALERT_COOLDOWN_SECONDS:
        return False
    _LAST_ALERT[signature] = now
    return True


class WorkerStepError(Exception):
    """Erreur survenue à une étape identifiée du cycle (pour email + retry)."""

    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage
        self.message = message


@dataclass
class ClaimedTask:
    request_id: str
    calendar_id: str
    strategy_id: str
    workspace_id: str
    user_id: str
    email: str
    first_name: str
    subject: str
    prompt: str
    commercial_objective: str
    target_sector: str
    language: str
    preferred_formats: list
    target_audience: list
    constraints: str
    attempt_count: int


async def run_cycle() -> dict:
    """
    Exécute un cycle complet du Worker. Retourne un résumé pour les logs/API
    d'admin (jamais lève d'exception vers l'appelant — toute erreur est
    capturée, journalisée, et notifiée par email selon le pattern original).
    """
    pool = get_pool()

    # --- Étape 1 : maintenance ---------------------------------------------
    try:
        async with pool.acquire() as conn:
            await conn.execute(sql("worker/maintenance.sql"))
    except Exception as exc:  # noqa: BLE001 - capture volontairement large ici
        message = str(exc)
        # Une panne d'infrastructure (base injoignable, mot de passe refusé)
        # n'a rien à voir avec une tâche de génération : elle se règle côté
        # serveur, pas en relançant le worker. On journalise à chaque cycle
        # mais on n'alerte qu'une fois par heure.
        infra = any(k in message.lower() for k in (
            "password authentication failed", "connection refused",
            "could not connect", "does not exist", "too many connections",
            "server closed the connection"))
        if infra:
            logger.error(
                "Worker: base de données inaccessible — %s. "
                "Vérifie DATABASE_URL dans .env et le mot de passe du rôle PostgreSQL.",
                message)
        else:
            logger.exception("Worker maintenance error")
        if _should_send_alert(f"maintenance:{message[:120]}"):
            await _handle_stage_error(None, "maintenance", message)
        return {"stage": "maintenance_error", "detail": message}

    # --- Étape 2 : réclamation atomique --------------------------------------
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql("worker/claim_task.sql"))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Worker claim error")
        await _handle_stage_error(None, "claim", str(exc))
        return {"stage": "claim_error", "detail": str(exc)}

    if row is None:
        # Aucun candidat : comportement normal du nœud Normalize claim result.
        return {"stage": "idle", "claim_error": None}
    if not row["pipeline_ready"]:
        claim_error = str(row["claim_error"] or "").strip()
        if claim_error:
            logger.warning("Worker claim: tâche invalide (%s)", claim_error)
            partial = _task_from_claim_row(row)
            await _handle_stage_error(partial, "claim_validation", claim_error)
            return {"stage": "claim_validation_error", "claim_error": claim_error}
        return {"stage": "idle", "claim_error": None}

    task = ClaimedTask(
        request_id=row["request_id"],
        calendar_id=row["calendar_id"],
        strategy_id=row["strategy_id"],
        workspace_id=row["workspace_id"],
        user_id=row["user_id"],
        email=row["email"],
        first_name=row["first_name"],
        subject=row["subject"],
        prompt=row["prompt"],
        commercial_objective=row["commercial_objective"],
        target_sector=row["target_sector"],
        language=row["language"],
        preferred_formats=json.loads(row["preferred_formats"]) if isinstance(row["preferred_formats"], str) else row["preferred_formats"],
        target_audience=json.loads(row["target_audience"]) if isinstance(row["target_audience"], str) else row["target_audience"],
        constraints=row["constraints"],
        attempt_count=row["attempt_count"],
    )
    logger.info("Worker: tâche réclamée calendar_id=%s request_id=%s (tentative %s)",
                task.calendar_id, task.request_id, task.attempt_count)

    # --- Étape 3 : génération IA ---------------------------------------------
    try:
        ai_result = await generate_worker_post(
            subject=task.subject,
            commercial_objective=task.commercial_objective,
            target_sector=task.target_sector,
            language=task.language,
            preferred_formats=task.preferred_formats,
            target_audience=task.target_audience,
            constraints=task.constraints,
            prompt=task.prompt,
        )
    except AIGenerationError as exc:
        await _handle_stage_error(task, "openrouter", str(exc))
        return {"stage": "openrouter_error", "detail": str(exc), "calendar_id": task.calendar_id}

    # --- Étape 4 : parsing strict n8n ------------------------------------------
    try:
        parsed = parse_worker_post_response(
            ai_result.raw_text,
            {
                "subject": task.subject,
                "prompt": task.prompt,
                "target_sector": task.target_sector,
                "target_audience": task.target_audience,
                "preferred_formats": task.preferred_formats,
            },
        )
        idea = parsed["ideas"][0]
    except (AIContractError, KeyError, IndexError, ValueError, TypeError) as exc:
        await _handle_stage_error(task, "parser", str(exc))
        return {"stage": "parser_error", "detail": str(exc), "calendar_id": task.calendar_id}

    # --- Étape 5 : sauvegarde (idempotente) ------------------------------------
    try:
        async with pool.acquire() as conn:
            save_row = await conn.fetchrow(
                sql("worker/save_idea_and_version.sql"),
                task.request_id, task.workspace_id, task.user_id, task.calendar_id,
                json.dumps(idea), ai_result.raw_text,
            )
        if save_row["save_status"] not in ("saved", "already_saved"):
            raise RuntimeError(f"save_status={save_row['save_status']}")
    except Exception as exc:  # noqa: BLE001
        await _handle_stage_error(task, "save", str(exc))
        return {"stage": "save_error", "detail": str(exc), "calendar_id": task.calendar_id}

    # --- Étape 6 : liaison + clôture --------------------------------------------
    try:
        async with pool.acquire() as conn:
            final_row = await conn.fetchrow(
                sql("worker/link_and_finalize.sql"),
                save_row["request_id"], save_row["calendar_id"],
                save_row["idea_id"], save_row["version_id"],
            )
        if not final_row["finalized"]:
            raise RuntimeError(f"finalization status={final_row['status']}")
    except Exception as exc:  # noqa: BLE001
        await _handle_stage_error(task, "finalization", str(exc))
        return {"stage": "finalization_error", "detail": str(exc), "calendar_id": task.calendar_id}

    # --- Étape 7 : notification immédiate de validation -----------------------
    # La finalisation SQL place le sujet ET l'idée en ready_for_review.
    # L'email part uniquement après cette finalisation réussie. Le mécanisme
    # de rappels existant prend ensuite le relais toutes les 2 heures.
    validation_notice = await _notify_validation_required(str(save_row["idea_id"]))

    logger.info(
        "Worker: cycle terminé avec succès idea_id=%s version_id=%s validation_emails=%s/%s",
        save_row["idea_id"], save_row["version_id"],
        validation_notice["sent"], validation_notice["claimed"],
    )
    return {
        "stage": "done",
        "calendar_id": task.calendar_id,
        "idea_id": save_row["idea_id"],
        "version_id": save_row["version_id"],
        "validation_emails_claimed": validation_notice["claimed"],
        "validation_emails_sent": validation_notice["sent"],
        "validation_email_errors": validation_notice["errors"],
    }


async def _notify_validation_required(idea_id: str) -> dict:
    """Alerte immédiatement chaque membre actif du workspace, sans doublon.

    Le SQL crée/réutilise la ligne de rappel (idea_id, user_id), puis la
    réclame avec le même système de bail que le cron de validation. Après un
    envoi réussi, confirm_sent.sql programme le prochain rappel à +2 heures.
    Si SMTP échoue, le bail expire et le cron de validation réessaiera.
    """
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(sql("validation/ensure_reminders.sql"))
            await conn.execute(sql("validation/seed_immediate_for_idea.sql"), idea_id)
            rows = await conn.fetch(sql("validation/claim_immediate_for_idea.sql"), idea_id)
    except Exception:  # noqa: BLE001
        logger.exception("Worker: impossible de réclamer les notifications de validation idea_id=%s", idea_id)
        return {"claimed": 0, "sent": 0, "errors": 1}

    sent = 0
    errors = 0
    for row in rows:
        try:
            delivered = await send_validation_reminder_email_raw(
                to_email=row["email"],
                first_name=row["first_name"],
                workspace_name=row["workspace_name"],
                idea_title=row["idea_title"],
                request_subject=row["request_subject"],
                post_excerpt=row["post_excerpt"],
                validation_url=row["validation_url"],
                reminder_number=row["reminder_number"],
            )
            if not delivered:
                errors += 1
                logger.warning(
                    "Worker: notification validation non délivrée idea_id=%s user_id=%s; le cron réessaiera",
                    row["idea_id"], row["user_id"],
                )
                continue
            async with pool.acquire() as conn:
                await conn.execute(
                    sql("validation/confirm_sent.sql"),
                    row["idea_id"], row["user_id"], row["lease_token"], row["email"],
                )
            sent += 1
        except Exception:  # noqa: BLE001
            errors += 1
            logger.exception(
                "Worker: échec notification validation idea_id=%s user_id=%s",
                row["idea_id"], row["user_id"],
            )

    return {"claimed": len(rows), "sent": sent, "errors": errors}


STAGE_ERROR_MAP = {
    "maintenance": ("Worker - Maintenance and repair", "calendar_clean_maintenance_failed"),
    "claim": ("Worker - Claim task and create subject", "calendar_clean_claim_failed"),
    "claim_validation": ("Worker - Claim task and create subject", "calendar_clean_claim_invalid"),
    "openrouter": ("Worker - Generate with OpenRouter", "calendar_clean_openrouter_failed"),
    "parser": ("Worker - Parse ready post", "calendar_clean_parser_failed"),
    "save": ("Worker - Save idea and version", "calendar_clean_save_failed"),
    "finalization": ("Worker - Link and finalize", "calendar_clean_finalize_failed"),
}


def _row_value(row, key: str, default=""):
    try:
        value = row[key]
    except Exception:
        value = default
    return default if value is None else value


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _task_from_claim_row(row) -> ClaimedTask:
    """Conserve le contexte du résultat de claim invalide comme le nœud n8n d'erreur."""
    return ClaimedTask(
        request_id=str(_row_value(row, "request_id", "") or ""),
        calendar_id=str(_row_value(row, "calendar_id", "") or ""),
        strategy_id=str(_row_value(row, "strategy_id", "") or ""),
        workspace_id=str(_row_value(row, "workspace_id", "") or ""),
        user_id=str(_row_value(row, "user_id", "") or ""),
        email=str(_row_value(row, "email", "") or ""),
        first_name=str(_row_value(row, "first_name", "") or ""),
        subject=str(_row_value(row, "subject", "Sujet planifié") or "Sujet planifié"),
        prompt=str(_row_value(row, "prompt", "") or ""),
        commercial_objective=str(_row_value(row, "commercial_objective", "") or ""),
        target_sector=str(_row_value(row, "target_sector", "") or ""),
        language=str(_row_value(row, "language", "français") or "français"),
        preferred_formats=_json_list(_row_value(row, "preferred_formats", [])),
        target_audience=_json_list(_row_value(row, "target_audience", [])),
        constraints=str(_row_value(row, "constraints", "") or ""),
        attempt_count=int(_row_value(row, "attempt_count", 0) or 0),
    )


async def _handle_stage_error(task: ClaimedTask | None, stage: str, message: str) -> None:
    """Reproduit « Worker - * error » puis « Worker - Mark failure » n8n."""
    error_node, error_stage = STAGE_ERROR_MAP.get(
        stage, ("Pipeline calendrier", "calendar_clean_worker_failed")
    )
    message = str(message or "Erreur de génération.").replace("\x00", " ").strip()[:2800]
    try:
        pool = get_pool()
    except RuntimeError:
        logger.error("Worker: pool DB indisponible, alerte non envoyée (%s)", message)
        return

    mark_row = None
    if task is not None and (task.calendar_id or task.request_id):
        try:
            async with pool.acquire() as conn:
                mark_row = await conn.fetchrow(
                    sql("worker/mark_failure.sql"),
                    task.calendar_id or "",
                    task.request_id or "",
                    error_node,
                    message,
                    error_stage,
                )
        except Exception:  # noqa: BLE001
            logger.exception("Worker: échec de Mark failure (stage=%s)", stage)

    attempt_count = int(mark_row["attempt_count"] or 0) if mark_row is not None else (task.attempt_count if task else 0)
    try:
        recipient = task.email if (task and task.email) else None
        delivered = await send_worker_error_email(
            recipient=recipient,
            first_name=(task.first_name if task else ""),
            stage=error_stage,
            message=message,
            calendar_id=(task.calendar_id if task else ""),
            subject_name=(task.subject if task else "Sujet planifié"),
            request_id=(task.request_id if task else ""),
            error_node=error_node,
            attempt_count=attempt_count,
        )
        if not delivered:
            raise RuntimeError("email d'erreur non délivré (SMTP indisponible)")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Worker: échec d'envoi de l'email d'erreur (stage=%s)", stage)
        # n8n journalise l'échec SMTP dans le payload de la tâche calendrier.
        if task is not None and task.calendar_id:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE public.app_growth_strategy_action_calendar
                        SET payload = COALESCE(payload,'{}'::jsonb) || jsonb_build_object(
                              'clean_worker_smtp_error',$2::text,
                              'clean_worker_smtp_error_at',now()::text
                            ),
                            updated_at = now()
                        WHERE id=$1::uuid
                        """,
                        task.calendar_id, str(exc)[:1800],
                    )
            except Exception:  # noqa: BLE001
                logger.exception("Worker: impossible de journaliser l'échec SMTP en base")
