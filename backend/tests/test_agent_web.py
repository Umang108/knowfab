"""Focused checks for the standalone agent UI's browser authentication boundary."""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agent"))
from graphbase_agent import web


class FakeConnection:
    def __init__(self):
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, statement, params=None):
        self.statements.append((statement, params))


class FakeKeycloak:
    client_id = "graphbase-agent"
    scope = "openid profile email"

    @property
    def endpoints(self):
        return {"authorization_endpoint": "https://identity.example/auth"}


def test_login_redirect_starts_pkce_and_binds_oauth_state(monkeypatch):
    monkeypatch.setattr(web, "_ensure_schema", lambda: None)
    monkeypatch.setattr(web, "_connect", FakeConnection)
    monkeypatch.setattr(web, "_keycloak", FakeKeycloak)
    monkeypatch.setenv("AGENT_UI_URL", "https://agent.example")

    with TestClient(web.app) as client:
        response = client.get("/auth/login", follow_redirects=False)

    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["client_id"] == ["graphbase-agent"]
    assert query["redirect_uri"] == ["https://agent.example/auth/callback"]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == [response.cookies[web.STATE_COOKIE]]
    cookie_header = response.headers["set-cookie"].lower()
    assert "httponly" in cookie_header
    assert "samesite=lax" in cookie_header


def test_api_mutations_require_csrf_and_chat_requires_login(monkeypatch):
    monkeypatch.setattr(web, "_ensure_schema", lambda: None)
    with TestClient(web.app) as client:
        denied_csrf = client.post("/api/chat", json={"message": "hello"})
        denied_auth = client.post(
            "/api/chat",
            json={"message": "hello"},
            headers={web.CSRF_HEADER: web.CSRF_VALUE},
        )
        status = client.get("/api/session")

    assert denied_csrf.status_code == 403
    assert denied_auth.status_code == 401
    assert status.json() == {"authenticated": False}


def test_session_tokens_are_encrypted_at_rest(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-only-secret")
    encrypted = web._seal("opaque-access-token")

    assert encrypted != "opaque-access-token"
    assert web._unseal(encrypted) == "opaque-access-token"


def test_web_module_imports_from_the_agent_package_directory():
    agent_dir = Path(__file__).resolve().parents[2] / "agent" / "graphbase_agent"
    result = subprocess.run(
        [sys.executable, "-c", "from uvicorn.importer import import_from_string; import_from_string('web:app')"],
        cwd=agent_dir,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
