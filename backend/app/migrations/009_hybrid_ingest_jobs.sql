ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_job_type_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_job_type_check
    CHECK (job_type IN ('graph_extract', 'graph_build', 'rag_ingest', 'add_data', 'hybrid_rag_ingest'));
