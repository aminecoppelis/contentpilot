-- Parité n8n V90 : colonnes et contraintes utilisées par « BDD - Appliquer action stratégie ».
ALTER TABLE public.app_growth_strategy_action_calendar
  ADD COLUMN IF NOT EXISTS checkpoint_no integer;

UPDATE public.app_growth_strategy_action_calendar c
SET action_id = COALESCE(
  CASE
    WHEN COALESCE(c.payload#>>'{action,id}','') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    THEN (c.payload#>>'{action,id}')::uuid
    ELSE NULL
  END,
  (
    SELECT value::uuid
    FROM jsonb_array_elements_text(CASE WHEN jsonb_typeof(c.action_ids)='array' THEN c.action_ids ELSE '[]'::jsonb END) values_list(value)
    WHERE value ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    LIMIT 1
  )
)
WHERE c.action_id IS NULL;

UPDATE public.app_growth_strategy_action_calendar c
SET checkpoint_no = CASE
  WHEN COALESCE(c.payload#>>'{adaptive_checkpoint,checkpoint_no}','') ~ '^[0-9]{1,4}$'
  THEN (c.payload#>>'{adaptive_checkpoint,checkpoint_no}')::integer
  ELSE NULL
END
WHERE c.checkpoint_no IS NULL
  AND COALESCE(c.payload->>'kind','') = 'adaptive_checkpoint';

WITH ranked AS (
  SELECT c.id,
         ROW_NUMBER() OVER (
           PARTITION BY c.strategy_id, c.action_id
           ORDER BY CASE COALESCE(c.status,'scheduled')
                      WHEN 'done' THEN 1 WHEN 'generated' THEN 2 WHEN 'generating' THEN 3 WHEN 'scheduled' THEN 4 ELSE 5 END,
                    c.planned_for ASC NULLS LAST, c.created_at ASC NULLS LAST, c.id::text ASC
         ) AS rn
  FROM public.app_growth_strategy_action_calendar c
  WHERE c.action_id IS NOT NULL
    AND COALESCE(c.status,'scheduled') IN ('scheduled','generating','generated','done')
)
UPDATE public.app_growth_strategy_action_calendar c
SET status='skipped', updated_at=now(),
    error_message='Doublon historique supprimé automatiquement par la contrainte calendrier V43.'
FROM ranked r
WHERE c.id=r.id AND r.rn>1;

WITH ranked AS (
  SELECT c.id,
         ROW_NUMBER() OVER (
           PARTITION BY c.strategy_id, c.checkpoint_no
           ORDER BY CASE COALESCE(c.status,'scheduled')
                      WHEN 'done' THEN 1 WHEN 'generated' THEN 2 WHEN 'generating' THEN 3 WHEN 'scheduled' THEN 4 ELSE 5 END,
                    c.planned_for ASC NULLS LAST, c.created_at ASC NULLS LAST, c.id::text ASC
         ) AS rn
  FROM public.app_growth_strategy_action_calendar c
  WHERE c.checkpoint_no IS NOT NULL
    AND COALESCE(c.status,'scheduled') IN ('scheduled','generating','generated','done')
)
UPDATE public.app_growth_strategy_action_calendar c
SET status='skipped', updated_at=now(),
    error_message='Checkpoint dupliqué supprimé automatiquement par la contrainte calendrier V43.'
FROM ranked r
WHERE c.id=r.id AND r.rn>1;

CREATE UNIQUE INDEX IF NOT EXISTS app_growth_strategy_action_calendar_active_action_uq
  ON public.app_growth_strategy_action_calendar(strategy_id, action_id)
  WHERE action_id IS NOT NULL
    AND COALESCE(status,'scheduled') IN ('scheduled','generating','generated','done');

CREATE UNIQUE INDEX IF NOT EXISTS app_growth_strategy_action_calendar_active_checkpoint_uq
  ON public.app_growth_strategy_action_calendar(strategy_id, checkpoint_no)
  WHERE checkpoint_no IS NOT NULL
    AND COALESCE(status,'scheduled') IN ('scheduled','generating','generated','done');
