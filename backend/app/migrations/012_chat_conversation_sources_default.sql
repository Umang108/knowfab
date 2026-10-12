-- Normalize chat_conversations.sources to JSONB across databases created by
-- older versions of Knowledge Fabric (some installations used TEXT[]).
ALTER TABLE chat_conversations
    ADD COLUMN IF NOT EXISTS sources jsonb;

DO $$
DECLARE
    sources_udt text;
BEGIN
    SELECT c.udt_name
      INTO sources_udt
      FROM information_schema.columns AS c
     WHERE c.table_schema = current_schema()
       AND c.table_name = 'chat_conversations'
       AND c.column_name = 'sources';

    IF sources_udt = '_text' THEN
        ALTER TABLE chat_conversations
            ALTER COLUMN sources TYPE jsonb
            USING to_jsonb(sources);
    ELSIF sources_udt = 'text' THEN
        ALTER TABLE chat_conversations
            ALTER COLUMN sources TYPE jsonb
            USING CASE
                WHEN sources IS NULL OR btrim(sources) = '' THEN '[]'::jsonb
                ELSE sources::jsonb
            END;
    END IF;
END $$;

UPDATE chat_conversations
   SET sources = '[]'::jsonb
 WHERE sources IS NULL;

ALTER TABLE chat_conversations
    ALTER COLUMN sources SET DEFAULT '[]'::jsonb,
    ALTER COLUMN sources SET NOT NULL;
