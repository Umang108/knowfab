"""Regressions for graph-build connectivity and dynamic schema-property lookups."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from app import chat, jobs, loader, pipelines


def test_graph_build_refuses_to_mark_row_entity_with_zero_accepted_rows_ready():
    plan = SimpleNamespace(
        matches=[SimpleNamespace(schema_sheet="ITSM_Records", file_sheet=SimpleNamespace(rows=[{}]))],
        node_rows={"PriorityGuideline": {"1": {}}},
    )
    schema = {
        "nodes": [
            {"label": "Incident", "sheet": "ITSM_Records", "role": "row"},
            {"label": "PriorityGuideline", "sheet": "Priority_Guidelines", "role": "row"},
        ]
    }

    with pytest.raises(loader.LoadError, match="No rows were accepted.*Incident"):
        pipelines._require_row_entities(plan, schema)


def test_graph_build_records_neo4j_connection_failure(monkeypatch):
    failed_runs = []
    catalog = {
        "approved_schema": {
            "source_file": "incidents.csv",
            "source_path": "incidents.csv",
        },
        "kb_type": "graph",
    }

    class OfflineGraphStore:
        def __init__(self, kb_name):
            self.kb_name = kb_name

        def ensure_storage(self):
            pass

        def read_internal(self, query, **params):
            assert query == "RETURN 1 AS connected"
            raise ConnectionError("Neo4j is not reachable")

    monkeypatch.setattr(pipelines.kb, "get_catalog", lambda _kb: catalog)
    monkeypatch.setattr(pipelines, "GraphStore", OfflineGraphStore)
    monkeypatch.setattr(pipelines, "start_run", lambda *args: 17)
    monkeypatch.setattr(
        pipelines,
        "finish_run",
        lambda run_id, status, **fields: failed_runs.append((run_id, status, fields)),
    )
    monkeypatch.setattr(pipelines.jobs, "step", lambda *args, **kwargs: None)

    with pytest.raises(ConnectionError, match="Neo4j is not reachable"):
        pipelines.graph_build(1, "test_graph", "owner")

    assert len(failed_runs) == 1
    assert failed_runs[0][0:2] == (17, "failed")
    assert "Neo4j is not reachable" in failed_runs[0][2]["summary"]


def test_graph_build_connection_failure_is_saved_on_job(monkeypatch):
    updates = []
    notifications = []

    class Result:
        rowcount = 1

        def fetchone(self):
            return {
                "started_by": "owner",
                "kb_name": "test_graph",
                "job_type": "graph_build",
                "source_file": "incidents.csv",
            }

    class Connection:
        def execute(self, query, params=None):
            updates.append((query, params))
            return Result()

    class InlineExecutor:
        def submit(self, fn):
            fn()

    def unavailable(_job_id):
        raise ConnectionError("Neo4j is not reachable")

    class ConnectionContext:
        def __enter__(self):
            return Connection()

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(jobs, "get_conn", ConnectionContext)
    monkeypatch.setattr(jobs, "_executor", InlineExecutor())
    monkeypatch.setattr(jobs, "trace_context", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(jobs, "get_settings", lambda: type("Settings", (), {"job_error_max_chars": 500})())

    jobs.submit(23, unavailable, on_error=notifications.append)

    failed_update = next(call for call in updates if "status = 'failed'" in call[0])
    assert failed_update[1] == ("ConnectionError: Neo4j is not reachable", 23)
    assert notifications == ["ConnectionError: Neo4j is not reachable"]


def test_value_hints_use_dynamic_property_lookup():
    calls = []

    class QueryStore:
        def label(self, label):
            return f"`{label}`"

        def read_internal(self, query, **params):
            calls.append((query, params))
            return [{"v": "Open"}]

    schema = {
        "nodes": [
            {
                "label": "Incident",
                "key": {"name": "incident_id"},
                "properties": [{"name": "state", "type": "string"}],
            }
        ]
    }

    hints = chat.value_hints(QueryStore(), schema)

    prop_query, params = calls[1]
    assert "n[$property]" in prop_query
    assert "n.`state`" not in prop_query
    assert params == {"property": "state", "limit": 13}
    assert hints[("Incident", "state")] == ["Open"]
