ALTER TABLE pipeline_runs DROP CONSTRAINT IF EXISTS pipeline_runs_run_type_check;
ALTER TABLE pipeline_runs ADD CONSTRAINT pipeline_runs_run_type_check
    CHECK (run_type IN ('initial_build', 'add_data', 'rag_ingest', 'hybrid_rag_ingest'));
