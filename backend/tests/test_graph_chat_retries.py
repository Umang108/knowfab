from app import chat


SCHEMA = {
    "nodes": [
        {
            "label": "IncidentRecord",
            "key": {"name": "number"},
            "properties": [{"name": "record_type", "type": "string"}],
        }
    ],
    "relationships": [],
}


class FakeGraphStore:
    def __init__(self, results):
        self.results = iter(results)
        self.executed = []

    def run_readonly(self, cypher):
        self.executed.append(cypher)
        return cypher, next(self.results)


def test_graph_chat_retries_when_query_returns_no_rows(monkeypatch):
    prompts = []
    responses = iter(
        [
            {"cypher": "MATCH (n:IncidentRecord) WHERE n.number = 'INC202600001' RETURN n.record_type AS type"},
            {"cypher": "MATCH (n:IncidentRecord) RETURN n.record_type AS type"},
        ]
    )
    store = FakeGraphStore([[], [{"type": "Incident"}]])

    def ask_json(system, prompt):
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr(chat, "ask_json", ask_json)
    result = chat.build_graph_chat(store, SCHEMA, synthesize=False).invoke(
        {
            "question": "Give record type of INC202600001",
            "history": [],
            "schema_text": ("schema", "examples"),
        }
    )

    assert result["rows"] == [{"type": "Incident"}]
    assert len(store.executed) == 2
    assert "returned zero rows" in prompts[1]
    assert "unique id property" in prompts[1]


def test_graph_chat_does_not_execute_a_schema_invalid_query_after_retry(monkeypatch):
    prompts = []
    query = {"cypher": "MATCH (n:ItsmRecord) RETURN n.record_type AS type"}
    store = FakeGraphStore([])

    def ask_json(system, prompt):
        prompts.append(prompt)
        return query

    monkeypatch.setattr(chat, "ask_json", ask_json)
    result = chat.build_graph_chat(store, SCHEMA, synthesize=False).invoke(
        {
            "question": "Give record type of INC202600001",
            "history": [],
            "schema_text": ("schema", "examples"),
        }
    )

    assert store.executed == []
    assert result["attempts"] == 2
    assert "Unknown node label ItsmRecord" in result["error"]
