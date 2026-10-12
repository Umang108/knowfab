"""Hybrid ingestion and chat orchestration, with the existing retrievers stubbed."""

from contextlib import nullcontext
from io import BytesIO
from threading import Barrier, current_thread
from types import SimpleNamespace

import pytest
from fastapi import UploadFile

from app import chat, pipelines
from app.api import kbs as kbs_api
from app.auth import CurrentUser


@pytest.mark.parametrize(
    ("kb_type", "uploads", "expected_jobs"),
    [
        ("graph", [("rows.csv", b"id,name\n1,Acme\n")], ["graph_extract"]),
        ("rag", [("policy.txt", b"Return within 30 days.")], ["rag_ingest"]),
        (
            "hybrid",
            [("rows.xlsx", b"fake workbook"), ("policy.pdf", b"fake document")],
            ["hybrid_ingest"],
        ),
    ],
)
def test_create_routes_graph_document_and_hybrid_upload_modes(
    kb_type, uploads, expected_jobs, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        kbs_api,
        "get_settings",
        lambda: SimpleNamespace(upload_dir=str(tmp_path), upload_max_mb=5),
    )
    catalog = []
    submitted = []
    job_id = iter(range(1, 10))
    created_jobs = []
    monkeypatch.setattr(kbs_api.kb, "create", lambda *args: catalog.append(args))
    monkeypatch.setattr(
        kbs_api.jobs,
        "create",
        lambda *args: created_jobs.append(args) or next(job_id),
    )
    monkeypatch.setattr(kbs_api.jobs, "submit", lambda ident, fn, *args, **kwargs: submitted.append((ident, fn)))
    monkeypatch.setattr(
        kbs_api,
        "GraphStore",
        lambda name: SimpleNamespace(storage_ref=f"label:KB_{name}"),
    )
    files = [UploadFile(filename=name, file=BytesIO(data)) for name, data in uploads]

    result = kbs_api.create_kb(
        kb_name=f"Test_{kb_type}",
        kb_type=kb_type,
        domain="Test",
        sub_domain="Hybrid",
        session_id=None,
        files=files,
        user=CurrentUser("owner", "Owner", None),
    )

    assert result["kb_name"] == f"Test_{kb_type}"
    assert catalog[0][2] == kb_type
    assert [fn.__name__ for _, fn in submitted] == expected_jobs
    if kb_type == "hybrid":
        assert [args[1] for args in created_jobs] == ["hybrid_ingest"]
        assert len(created_jobs[0][2]) == len(pipelines.HYBRID_CREATE_STEPS)
        assert created_jobs[0][2][:len(pipelines.RAG_STEPS)] == pipelines.RAG_STEPS
        assert created_jobs[0][2][len(pipelines.RAG_STEPS):] == pipelines.EXTRACT_STEPS
        assert "turboquant:Test_hybrid" in catalog[0][-1]
        assert "label:KB_Test_hybrid" in catalog[0][-1]
    elif kb_type == "graph":
        assert catalog[0][-1] == "label:KB_Test_graph"
    else:
        assert catalog[0][-1] == "turboquant:Test_rag"


def test_hybrid_ingest_finishes_rag_before_starting_graph(monkeypatch):
    order = []
    monkeypatch.setattr(
        pipelines,
        "rag_ingest",
        lambda job_id, kb_name, files, user_id, run_type: order.append(("rag", run_type)),
    )
    monkeypatch.setattr(
        pipelines,
        "graph_extract",
        lambda job_id, kb_name, path, name: order.append(("graph", name)),
    )

    pipelines.hybrid_ingest(
        12,
        "Hybrid_Test",
        [("policy.pdf", "policy.pdf")],
        "rows.csv",
        "rows.csv",
        "owner",
    )

    assert order == [("rag", "hybrid_rag_ingest"), ("graph", "rows.csv")]


def test_retrying_failed_hybrid_restarts_document_ingest_before_graph(monkeypatch, tmp_path):
    kb_name = "Hybrid_Retry"
    folder = tmp_path / kb_name
    folder.mkdir()
    graph_file = folder / "01234567_rows.xlsx"
    graph_file.write_bytes(b"workbook")
    document_file = folder / "89abcdef_policy.pdf"
    document_file.write_bytes(b"document")
    catalog = {"kb_type": "hybrid", "status": "failed"}
    created = []
    submitted = []

    class JobQuery:
        def fetchone(self):
            return {"job_type": "hybrid_ingest", "source_file": "rows.xlsx"}

    monkeypatch.setattr(kbs_api.kb, "require_access", lambda *args, **kwargs: catalog)
    monkeypatch.setattr(kbs_api, "get_settings", lambda: SimpleNamespace(upload_dir=str(tmp_path)))
    monkeypatch.setattr(
        kbs_api,
        "get_conn",
        lambda: nullcontext(SimpleNamespace(execute=lambda *args: JobQuery())),
    )
    monkeypatch.setattr(kbs_api.kb, "set_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        kbs_api.jobs,
        "create",
        lambda *args: created.append(args) or 43,
    )
    monkeypatch.setattr(
        kbs_api.jobs,
        "submit",
        lambda job_id, fn, *args, **kwargs: submitted.append((job_id, fn, args, kwargs)),
    )

    result = kbs_api.rerun_extraction(
        kb_name,
        user=CurrentUser("owner", "Owner", None),
    )

    assert result == {"job_id": 43}
    assert created[0][1:3] == ("hybrid_ingest", pipelines.HYBRID_CREATE_STEPS)
    assert submitted[0][1] is pipelines.hybrid_ingest
    assert submitted[0][2] == (
        kb_name,
        [(str(document_file), "policy.pdf")],
        str(graph_file),
        "rows.xlsx",
        "owner",
    )


def _run_hybrid(monkeypatch, *, graph=None, passages=None, graph_error=None, vector_error=None):
    def graph_retrieval(*args):
        if graph_error:
            raise graph_error
        return graph or {"rows": [], "row_count": 0, "cypher": "MATCH (n) RETURN n", "path": []}

    def vector_retrieval(*args, **kwargs):
        if vector_error:
            raise vector_error
        return passages or []

    prompts = []
    monkeypatch.setattr(chat, "_hybrid_graph_retrieve", graph_retrieval)
    monkeypatch.setattr(chat, "retrieve", vector_retrieval)
    monkeypatch.setattr(chat, "ask_text", lambda system, prompt: prompts.append((system, prompt)) or "Grounded [1][2] [99].")
    result = chat.hybrid_answer(object(), {}, "v1", "kb", "What is the policy?", [])
    return result, prompts


def test_hybrid_retrieves_in_parallel_and_synthesizes_cited_evidence(monkeypatch):
    rendezvous = Barrier(2)
    threads = set()

    def graph_retrieval(*args):
        threads.add(current_thread().name)
        rendezvous.wait(timeout=3)
        return {"rows": [{"policy": "30 days"}], "row_count": 1, "cypher": "MATCH (n) RETURN n", "path": []}

    def vector_retrieval(*args, **kwargs):
        threads.add(current_thread().name)
        rendezvous.wait(timeout=3)
        return [{"text": "Returns are accepted within 30 days.", "source": "policy.pdf", "page": 2, "score": 0.9}]

    calls = []
    monkeypatch.setattr(chat, "_hybrid_graph_retrieve", graph_retrieval)
    monkeypatch.setattr(chat, "retrieve", vector_retrieval)
    monkeypatch.setattr(chat, "ask_text", lambda system, prompt: calls.append((system, prompt)) or "30 days [1][2] [99]")

    result = chat.hybrid_answer(object(), {}, "v1", "kb", "What is the policy?", [], include_contexts=True)

    assert len(threads) == 2
    assert result["retrieval_status"] == "complete"
    assert [source["kind"] for source in result["sources"]] == ["graph", "document"]
    assert result["sources"][1]["source"] == "policy.pdf" and result["sources"][1]["page"] == 2
    assert result["answer"] == "30 days [1][2] "
    assert "conflict" in calls[0][0].lower()
    assert "graph rows as authoritative" in calls[0][0].lower()
    assert "[1] (Knowledge graph, result row 1)" in calls[0][1]
    assert "- policy: 30 days" in calls[0][1]
    assert "- policy: 30 days" in result["contexts"][0]
    assert "[2] (policy.pdf, page 2)" in calls[0][1]


@pytest.mark.parametrize(
    ("graph_error", "vector_error", "graph", "passages", "warning"),
    [
        (RuntimeError("neo4j down"), None, None, [{"text": "30 days", "source": "p.txt", "page": None, "score": 0.8}], "Graph"),
        (None, RuntimeError("vector down"), {"rows": [{"count": 5}], "row_count": 1}, None, "Document"),
    ],
)
def test_hybrid_uses_available_retriever_and_reports_partial_failure(
    monkeypatch, graph_error, vector_error, graph, passages, warning
):
    result, prompts = _run_hybrid(
        monkeypatch,
        graph=graph,
        passages=passages,
        graph_error=graph_error,
        vector_error=vector_error,
    )
    assert result["retrieval_status"] == "partial"
    assert result["retrieval_warnings"] == [f"{warning} retrieval was unavailable."]
    assert result["sources"]
    assert "Retrieval warnings" in prompts[0][1]


def test_hybrid_fails_explicitly_when_both_retrievers_fail(monkeypatch):
    monkeypatch.setattr(chat, "_hybrid_graph_retrieve", lambda *args: (_ for _ in ()).throw(RuntimeError("neo4j")))
    monkeypatch.setattr(chat, "retrieve", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("vectors")))
    with pytest.raises(chat.HybridRetrievalError, match="Graph and document retrieval"):
        chat.hybrid_answer(object(), {}, "v1", "kb", "What is the policy?", [])
