"""
Cron de rappel/validation — toutes les 15 minutes.
CORRIGÉ : port EXACT de l'algorithme réel découvert dans les nœuds
"VALIDATION - Réclamer rappels email" / "Construire email rappel" /
"Confirmer rappel envoyé" (précédemment approximé avec un seuil de 24h
inventé — l'original utilise un mécanisme de bail/lease bien plus riche) :

  - Table dédiée `app_post_validation_email_reminders` (créée/migrée à la
    volée par la requête elle-même, motif "auto-réparant" déjà noté ailleurs
    dans le workflow).
  - Un rappel = 1 (idée, utilisateur membre actif du workspace) — donc un
    même post peut générer plusieurs emails si plusieurs personnes du
    workspace doivent valider.
  - Auto-résolution : dès qu'une idée n'est plus 'pending_review'/
    'ready_for_review', a été supprimée, ou que le membre n'est plus actif,
    la ligne de rappel est marquée résolue (plus jamais notifiée).
  - Re-création idempotente à chaque cycle (ON CONFLICT DO UPDATE) pour les
    idées encore éligibles.
  - Réclamation atomique par bail (`lease_until` = now()+20min, `lease_token`
    aléatoire) — même famille de pattern que le Worker principal, mais sans
    FOR UPDATE SKIP LOCKED explicite ici (le bail joue ce rôle).
  - **Intervalle entre deux rappels réussis : 2 heures** (`next_send_at`).
  - La confirmation d'envoi utilise le lease_token pour n'accepter QUE la
    confirmation correspondant à la réclamation en cours (anti-doublon en
    cas de concurrence).
"""
from __future__ import annotations

import logging

from app.database import get_pool, sql
from app.services.mailer import send_validation_reminder_email_raw

logger = logging.getLogger("worker.validation")


async def run_validation_cycle() -> dict:
    pool = get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql("validation/claim_reminders.sql"))

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
                # Envoi échoué : on NE confirme PAS. Le bail expire au bout de
                # 20 minutes et la ligne redevient réclamable — le rappel sera
                # retenté, il n'est pas perdu.
                logger.warning(
                    "Validation cron: email non délivré pour idea_id=%s — sera retenté",
                    row["idea_id"])
                errors += 1
                continue
            async with pool.acquire() as conn:
                await conn.execute(
                    sql("validation/confirm_sent.sql"),
                    row["idea_id"], row["user_id"], row["lease_token"], row["email"],
                )
            sent += 1
        except Exception:  # noqa: BLE001
            logger.exception(
                "Validation cron: échec d'envoi pour idea_id=%s user_id=%s", row["idea_id"], row["user_id"],
            )
            errors += 1
            # NOTE: en cas d'échec, le bail (lease_until) expire naturellement
            # après 20 minutes (posé par claim_reminders.sql) et la ligne
            # redevient réclamable au cycle suivant — aucune action corrective
            # supplémentaire n'est nécessaire ici (fidèle à l'original, qui
            # ne fait pas de rollback explicite du bail sur erreur SMTP).

    return {"claimed": len(rows), "sent": sent, "errors": errors}
