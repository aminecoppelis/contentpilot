from __future__ import annotations

import json
import logging

from app.database import get_pool
from app.models.auth import AuthUser

logger = logging.getLogger("worker.strategy_generation")


async def run_strategy_generation_cycle() -> dict:
    """Reprend une génération abandonnée par un redémarrage du processus web."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT s.id::text AS strategy_id, s.workspace_id::text, s.created_by::text,
                       s.form_data, COALESCE(u.email,'') AS email,
                       COALESCE(u.first_name,'') AS first_name,
                       COALESCE(u.last_name,'') AS last_name,
                       COALESCE(u.full_name,'') AS full_name,
                       COALESCE(u.role,'user') AS role,
                       COALESCE(u.timezone,'Europe/Paris') AS timezone
                FROM public.app_growth_strategies s
                JOIN public.app_users u ON u.id=s.created_by AND u.deleted_at IS NULL
                WHERE s.status='generating'
                  AND (
                    NOT (COALESCE(s.strategy_data,'{}'::jsonb) ? 'generation_started_at')
                    OR NULLIF(s.strategy_data->>'generation_started_at','')::timestamptz
                       < now() - interval '30 minutes'
                  )
                ORDER BY s.created_at
                FOR UPDATE OF s SKIP LOCKED
                LIMIT 1
                """
            )
            if row is None:
                return {"stage": "idle"}
            await conn.execute(
                "UPDATE public.app_growth_strategies SET updated_at=now(), strategy_data="
                "COALESCE(strategy_data,'{}'::jsonb)||jsonb_build_object("
                "'generation_started_at',now()::text,'generation_attempt',"
                "COALESCE((strategy_data->>'generation_attempt')::int,0)+1) "
                "WHERE id=$1::uuid",
                row["strategy_id"],
            )

    form_data = row["form_data"]
    payload = json.loads(form_data) if isinstance(form_data, str) else dict(form_data or {})
    user = AuthUser(
        id=row["created_by"], email=row["email"], first_name=row["first_name"],
        last_name=row["last_name"], full_name=row["full_name"], role=row["role"],
        timezone=row["timezone"], is_super_admin=str(row["role"]).lower() == "admin",
        session_id="", request_token="", active_workspace_id=row["workspace_id"],
        active_workspace_name="", active_workspace_role="", workspaces=[],
    )
    from app.routers.strategies import _generate_strategy_in_background
    await _generate_strategy_in_background(payload, user, row["strategy_id"])
    logger.info("Recovered strategy generation strategy_id=%s", row["strategy_id"])
    return {"stage": "processed", "strategy_id": row["strategy_id"]}
