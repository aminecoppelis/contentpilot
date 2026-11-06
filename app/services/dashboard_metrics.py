"""Workspace-scoped dashboard aggregates; dates follow the account timezone."""

SUMMARY_SQL = """SELECT status, count(*)::int AS total
    FROM public.post_publications WHERE workspace_id=$1::uuid GROUP BY status"""

HISTORY_SQL = """WITH days AS (
    SELECT generate_series((now() AT TIME ZONE $2)::date - 13,
                           (now() AT TIME ZONE $2)::date, interval '1 day')::date AS day
), counts AS (
    SELECT (COALESCE(published_at,scheduled_at,created_at) AT TIME ZONE $2)::date AS day,
           count(*)::int AS total
    FROM public.post_publications
    WHERE workspace_id=$1::uuid AND status='published'
      AND COALESCE(published_at,scheduled_at,created_at) >=
          (((now() AT TIME ZONE $2)::date - 13)::timestamp AT TIME ZONE $2)
      AND COALESCE(published_at,scheduled_at,created_at) <= now()
    GROUP BY 1
) SELECT days.day::text AS day, COALESCE(counts.total,0)::int AS total
FROM days LEFT JOIN counts USING(day) ORDER BY day"""

UPCOMING_SQL = """SELECT pp.id::text, pp.scheduled_at, pp.platform, pi.title,
                          pi.id::text AS idea_id, pr.id::text AS request_id
    FROM public.post_publications pp
    JOIN public.post_ideas pi ON pi.id=pp.idea_id AND pi.workspace_id=pp.workspace_id
    JOIN public.post_requests pr ON pr.id=pi.request_id AND pr.workspace_id=pp.workspace_id
    WHERE pp.workspace_id=$1::uuid AND pp.status='scheduled' AND pp.scheduled_at >= now()
      AND pi.deleted_at IS NULL AND pr.deleted_at IS NULL
    ORDER BY pp.scheduled_at,pp.id LIMIT 5"""

OPERATIONS_SQL = """SELECT
    count(*) FILTER (WHERE pp.status='scheduled' AND pp.scheduled_at >= now())::int AS scheduled,
    count(*) FILTER (WHERE pp.status='scheduled' AND pp.scheduled_at < now())::int AS overdue,
    count(*) FILTER (WHERE pp.status='failed')::int AS failed
    FROM public.post_publications pp
    JOIN public.post_ideas pi ON pi.id=pp.idea_id AND pi.workspace_id=pp.workspace_id
    JOIN public.post_requests pr ON pr.id=pi.request_id AND pr.workspace_id=pp.workspace_id
    WHERE pp.workspace_id=$1::uuid AND pi.deleted_at IS NULL AND pr.deleted_at IS NULL"""

ACTION_GROUPS_SQL = """SELECT s.id::text AS strategy_id,s.title,
    count(*) FILTER (WHERE c.status IN ('scheduled','retry') AND c.planned_for >= now())::int AS upcoming,
    count(*) FILTER (WHERE c.status IN ('scheduled','retry','pending_reschedule') AND c.planned_for < now())::int AS overdue,
    count(*) FILTER (WHERE c.status='failed')::int AS failed
    FROM public.app_growth_strategy_action_calendar c
    JOIN public.app_growth_strategies s ON s.id=c.strategy_id AND s.workspace_id=c.workspace_id
    WHERE c.workspace_id=$1::uuid AND s.status='active'
      AND COALESCE(c.payload->>'kind','') <> 'adaptive_checkpoint'
      AND NOT EXISTS (SELECT 1 FROM public.post_requests pr
          WHERE pr.id=c.request_id AND pr.workspace_id=c.workspace_id AND pr.deleted_at IS NULL)
    GROUP BY s.id,s.title ORDER BY s.title,s.id"""

NEXT_ACTIONS_SQL = """SELECT c.id::text,c.strategy_id::text,c.planned_for,
    COALESCE(a.title,c.payload->>'action_title',s.title) AS title
    FROM public.app_growth_strategy_action_calendar c
    JOIN public.app_growth_strategies s ON s.id=c.strategy_id AND s.workspace_id=c.workspace_id
    LEFT JOIN public.app_growth_strategy_actions a ON a.id=c.action_id AND a.workspace_id=c.workspace_id
    WHERE c.workspace_id=$1::uuid AND s.status='active'
      AND c.status IN ('scheduled','retry') AND c.planned_for >= now()
      AND COALESCE(c.payload->>'kind','') <> 'adaptive_checkpoint'
      AND NOT EXISTS (SELECT 1 FROM public.post_requests pr
          WHERE pr.id=c.request_id AND pr.workspace_id=c.workspace_id AND pr.deleted_at IS NULL)
    ORDER BY c.planned_for,c.id LIMIT 5"""


async def load_dashboard_metrics(conn, workspace_id, timezone):
    summary = await conn.fetch(SUMMARY_SQL, workspace_id)
    history = await conn.fetch(HISTORY_SQL, workspace_id, timezone)
    upcoming = await conn.fetch(UPCOMING_SQL, workspace_id)
    operations = await conn.fetchrow(OPERATIONS_SQL, workspace_id)
    action_groups = await conn.fetch(ACTION_GROUPS_SQL, workspace_id)
    next_actions = await conn.fetch(NEXT_ACTIONS_SQL, workspace_id)
    return {
        "statuses": {row["status"]: row["total"] for row in summary},
        "history": [{"day": row["day"], "total": row["total"]} for row in history],
        "upcoming": [dict(row) for row in upcoming],
        "operations": dict(operations),
        "action_groups": [dict(row) for row in action_groups],
        "next_actions": [dict(row) for row in next_actions],
    }
