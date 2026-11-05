ALTER TABLE public.user_table_preferences
    DROP CONSTRAINT IF EXISTS user_table_preferences_view_key_check;
ALTER TABLE public.user_table_preferences
    ADD CONSTRAINT user_table_preferences_view_key_check CHECK
    (view_key IN ('posts','publications','strategies','networks','users','members','invitations','publication_calendar'));
