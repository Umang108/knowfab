ALTER TABLE kb_catalog DROP CONSTRAINT IF EXISTS kb_catalog_kb_type_check;
ALTER TABLE kb_catalog ADD CONSTRAINT kb_catalog_kb_type_check
    CHECK (kb_type IN ('graph', 'rag', 'hybrid'));

ALTER TABLE knowledge_bases DROP CONSTRAINT IF EXISTS knowledge_bases_kb_type_check;
ALTER TABLE knowledge_bases ADD CONSTRAINT knowledge_bases_kb_type_check
    CHECK (kb_type IN ('graph', 'rag', 'hybrid'));
