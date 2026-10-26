-- Propage la langue choisie dans la stratégie vers les générations planifiées.
-- Corrige également les tâches existantes qui n'ont pas encore été exécutées.
UPDATE public.app_growth_strategy_action_calendar AS calendar
SET payload = COALESCE(calendar.payload, '{}'::jsonb) || jsonb_build_object(
      'language',
      CASE lower(COALESCE(NULLIF(strategy.form_data->>'language',''),'fr'))
        WHEN 'fr' THEN 'French' WHEN 'français' THEN 'French' WHEN 'francais' THEN 'French'
        WHEN 'en' THEN 'English' WHEN 'anglais' THEN 'English'
        WHEN 'es' THEN 'Spanish' WHEN 'espagnol' THEN 'Spanish'
        WHEN 'it' THEN 'Italian' WHEN 'italien' THEN 'Italian'
        WHEN 'de' THEN 'German' WHEN 'allemand' THEN 'German'
        WHEN 'ru' THEN 'Russian' WHEN 'russe' THEN 'Russian'
        WHEN 'ar' THEN 'Arabic' WHEN 'arabe' THEN 'Arabic'
        ELSE COALESCE(NULLIF(strategy.form_data->>'language',''),'French')
      END
    ),
    updated_at = now()
FROM public.app_growth_strategies AS strategy
WHERE calendar.strategy_id = strategy.id
  AND lower(COALESCE(calendar.status,'scheduled')) IN ('scheduled','retry');
