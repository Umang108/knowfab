# Knowledge Fabric multi-KB chat and workspace update

## Changes

- Workspace no longer presents a Graph-only / Documents-only mode selector.
- The upload panels can be used together. Uploading one structured CSV/XLSX and one or more supported documents infers a hybrid knowledge base; a single source type retains its existing graph or document ingestion workflow.
- Chat searches every selected, accessible, ready knowledge base. A knowledge base is considered contributing only when its retrieval returns evidence (graph rows for graph KBs, retrieved sources for document KBs, either for hybrid KBs).
- Relevant answers from multiple KBs are synthesized into one grounded response; when only one KB contributes, its answer is returned directly.
- Chat shows selected KB names while composing and shows contributing KB names with each answer. KBs with no relevant evidence are identified.
- Multi-KB metadata is saved with conversation messages and restored when reopening a conversation. Follow-up turns can change the selected KBs without breaking the saved conversation.
- Existing graph/document ingestion and individual KB chat endpoints are retained.

## Validation

- Python source compilation passed (`python -m compileall -q backend/app`).
- Targeted pytest collection could not run in this environment because backend dependencies are not installed (`langchain_core` missing; test invocation also requires running from the backend directory for `app` imports).
- Frontend production build was not run because `frontend/node_modules` is not installed.
- End-to-end validation still requires the project's configured PostgreSQL, graph/vector stores, and LLM provider.
