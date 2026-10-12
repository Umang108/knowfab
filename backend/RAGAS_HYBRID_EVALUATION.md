# RAGAS evaluation for hybrid / multi-KB chat

The existing single-KB evaluator remains supported. To evaluate a knowledge base whose type is `hybrid`, pass its name as usual:

```bash
python -m app.cli eval-ragas --kb YOUR_HYBRID_KB --testset path/to/hybrid_test.csv
```

To evaluate the same multi-selected-KB chat flow used by `/api/chat/multi`, pass the selected KB names as a comma-separated list:

```bash
python -m app.cli eval-ragas --kb "DOCUMENT_KB,GRAPH_KB,HYBRID_KB" --testset path/to/hybrid_test.csv
```

The evaluator runs each question against every selected KB using the existing RAG, graph, or hybrid answer function. It then applies the same evidence-contribution checks as the multi-KB chat and synthesizes one answer from the contributing KBs. RAGAS scores that final answer against the combined evidence contexts and CSV reference answer.

CSV format:

```csv
id,question,reference
1,"Question requiring document and graph evidence","Ground-truth answer verified against the data"
```

Reports are written under `RAGAS_REPORT_DIR` (default `backend/reports/ragas`). Each report includes `results.csv`, `results.jsonl`, and `summary.json`. Keep references factual and independently verified; generic placeholder references make context recall and factual correctness scores misleading.
