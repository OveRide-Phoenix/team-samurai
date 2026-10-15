ALTER TABLE "{{schema}}".samurai_knowledge_chunks
    ADD CONSTRAINT ck_samurai_knowledge_exactly_one_source
    CHECK ((file_id IS NOT NULL)::integer + (artifact_id IS NOT NULL)::integer = 1)
    NOT VALID;

ALTER TABLE "{{schema}}".samurai_knowledge_chunks
    VALIDATE CONSTRAINT ck_samurai_knowledge_exactly_one_source;

DO $migration$
DECLARE
    source_unique_name text;
BEGIN
    SELECT constraint_record.conname INTO source_unique_name
    FROM pg_constraint AS constraint_record
    WHERE constraint_record.conrelid = '"{{schema}}".samurai_knowledge_chunks'::regclass
      AND constraint_record.contype = 'u'
      AND (
          SELECT array_agg(attribute_record.attname ORDER BY source_column.ordinality)
          FROM unnest(constraint_record.conkey) WITH ORDINALITY
              AS source_column(attnum, ordinality)
          JOIN pg_attribute AS attribute_record
            ON attribute_record.attrelid = constraint_record.conrelid
           AND attribute_record.attnum = source_column.attnum
      ) = ARRAY['workspace_id', 'content_sha256', 'ordinal']::name[];
    IF source_unique_name IS NULL THEN
        RAISE EXCEPTION 'knowledge content uniqueness constraint is missing';
    END IF;
    EXECUTE format(
        'ALTER TABLE %%I.samurai_knowledge_chunks DROP CONSTRAINT %%I',
        '{{schema}}',
        source_unique_name
    );
END
$migration$;

CREATE UNIQUE INDEX uq_samurai_knowledge_file_content
    ON "{{schema}}".samurai_knowledge_chunks
    (workspace_id, file_id, content_sha256, ordinal)
    WHERE file_id IS NOT NULL;

CREATE UNIQUE INDEX uq_samurai_knowledge_artifact_content
    ON "{{schema}}".samurai_knowledge_chunks
    (workspace_id, artifact_id, content_sha256, ordinal)
    WHERE artifact_id IS NOT NULL;
