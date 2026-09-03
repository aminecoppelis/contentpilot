-- Les sujets supprimés ne conservent plus d'idées orphelines.
-- Nettoie aussi les données créées avant ce correctif et annule toute publication différée.
WITH orphan_ideas AS MATERIALIZED (
  SELECT pi.id, pi.workspace_id
  FROM public.post_ideas pi
  JOIN public.post_requests pr ON pr.id = pi.request_id
  WHERE pr.deleted_at IS NOT NULL
    AND pi.deleted_at IS NULL
), cancelled_publications AS (
  UPDATE public.post_publications pp
  SET status = 'cancelled',
      error_message = 'Sujet supprimé.',
      updated_at = now(),
      response = COALESCE(pp.response, '{}'::jsonb) || jsonb_build_object(
        'cancelled_reason', 'subject_deleted',
        'cancelled_at', now()::text
      )
  FROM orphan_ideas oi
  WHERE pp.idea_id = oi.id
    AND pp.workspace_id = oi.workspace_id
    AND lower(COALESCE(pp.status, '')) IN ('scheduled','processing','pending','queued')
  RETURNING pp.id
), deleted_ideas AS (
  UPDATE public.post_ideas pi
  SET deleted_at = COALESCE(pi.deleted_at, now()),
      status = 'deleted',
      current_version_id = NULL,
      updated_at = now()
  FROM orphan_ideas oi
  WHERE pi.id = oi.id
  RETURNING pi.id
)
SELECT
  (SELECT COUNT(*) FROM deleted_ideas)::int AS deleted_idea_count,
  (SELECT COUNT(*) FROM cancelled_publications)::int AS cancelled_publication_count;
