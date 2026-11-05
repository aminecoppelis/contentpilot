ALTER TABLE public.user_table_preferences
    ADD COLUMN IF NOT EXISTS revision bigint NOT NULL DEFAULT 0;
