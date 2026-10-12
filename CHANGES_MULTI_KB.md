# Knowledge Fabric changes: multi-knowledge-base chat

## What changed
- Removed the Hybrid option from the Workspace knowledge-base creation selector. Graph-only and Documents-only creation remain available. Existing Hybrid knowledge bases remain supported for backwards compatibility.
- Added checkbox selection to Chat's Knowledge bases menu, including Select all. All ready knowledge bases are selected by default.
- Added `POST /api/chat/multi`, which checks access/readiness for each selected knowledge base, runs its existing graph/RAG/hybrid retrieval path, and synthesizes a single answer from successful results. Source metadata and per-KB results are returned; partial retrieval failures are reported as warnings.
- Existing single-KB chat endpoint and other application routes are retained.

## Validation
- Python syntax compilation passed with `python -m compileall -q backend/app`.
- Frontend production build could not be run in this environment because frontend dependencies (Vite) were not installed and dependency installation timed out.

## Notes
- `.env` secrets, Git internals, Python bytecode, and test caches are not included in this distribution. Configure your environment from `.env.example`.
