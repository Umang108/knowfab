"""Standalone browser UI for the MCP-connected TCS Knowledge Fabric agent."""

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode

import httpx
import jwt
import psycopg
from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

try:
    from graphbase_agent.keycloak import KeycloakSession, LoginError
except ModuleNotFoundError as exc:
    if exc.name != "graphbase_agent":
        raise
    from keycloak import KeycloakSession, LoginError

log = logging.getLogger("graphbase.agent.web")
STATIC_DIR = Path(os.getenv("AGENT_STATIC_DIR", str(Path(__file__).parent / "static")))
if not STATIC_DIR.is_dir():
    STATIC_DIR = Path(__file__).resolve().parents[1] / "ui" / "dist"
SESSION_COOKIE = "graphbase_agent_session"
STATE_COOKIE = "graphbase_agent_oauth_state"
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "graphbase"
KEYCLOAK_URL = "http://localhost:8080"

class ChatAgent(Protocol):
    session: KeycloakSession

    async def ask(self, question: str) -> str: ...


_agents: dict[str, ChatAgent] = {}
_agent_locks: dict[str, asyncio.Lock] = {}


def _env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if not value:
        if default is not None:
            return default
        raise RuntimeError(f"Set {name} in the environment")
    return value


def _bool_env(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes"}


def _dsn() -> str:
    dsn = os.getenv("POSTGRES_DSN")
    if dsn:
        return dsn
    return psycopg.conninfo.make_conninfo(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=_env("POSTGRES_DB", "graphbase"),
        user=_env("POSTGRES_USER", "postgres"),
        password=_env("POSTGRES_PASSWORD", "postgres"),
    )


def _connect():
    return psycopg.connect(
        _dsn(), connect_timeout=int(os.getenv("POSTGRES_CONNECT_TIMEOUT_SECONDS", "5")), row_factory=dict_row
    )


def _ensure_schema() -> None:
    with _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS graphbase_agent_sessions (
                id text PRIMARY KEY,
                user_id text NOT NULL,
                display_name text NOT NULL,
                email text,
                kc_access_token text NOT NULL,
                kc_refresh_token text NOT NULL,
                kc_access_expires_at timestamptz NOT NULL,
                expires_at timestamptz NOT NULL,
                idle_expires_at timestamptz NOT NULL,
                revoked_at timestamptz,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                modified_by text NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS graphbase_agent_oidc_requests (
                state text PRIMARY KEY,
                nonce text NOT NULL,
                code_verifier text NOT NULL,
                expires_at timestamptz NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                modified_by text NOT NULL DEFAULT 'system'
            )"""
        )
        conn.execute(
            """CREATE OR REPLACE FUNCTION graphbase_agent_touch_updated_at() RETURNS trigger AS $$
               BEGIN NEW.updated_at = now(); RETURN NEW; END; $$ LANGUAGE plpgsql"""
        )
        for table in ("graphbase_agent_sessions", "graphbase_agent_oidc_requests"):
            conn.execute(f"DROP TRIGGER IF EXISTS {table}_touch_updated_at ON {table}")
            conn.execute(
                f"""CREATE TRIGGER {table}_touch_updated_at BEFORE UPDATE ON {table}
                    FOR EACH ROW EXECUTE FUNCTION graphbase_agent_touch_updated_at()"""
            )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _ensure_schema()
    yield
    _agents.clear()
    _agent_locks.clear()


app = FastAPI(title="TCS Knowledge Fabric Agent", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.middleware("http")
async def protect_cookie_mutations(request: Request, call_next):
    if (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and request.url.path.startswith("/api/")
        and request.headers.get(CSRF_HEADER) != CSRF_VALUE
    ):
        return JSONResponse({"detail": "Missing CSRF header"}, status_code=403)
    return await call_next(request)


def _keycloak() -> KeycloakSession:
    return KeycloakSession(
        _env("KEYCLOAK_URL"),
        _env("KEYCLOAK_REALM"),
        os.getenv("AGENT_CLIENT_ID", "graphbase-agent"),
        os.getenv("AGENT_CLIENT_SECRET") or None,
        scope=os.getenv("AGENT_SCOPE", "openid profile email"),
        verify=os.getenv("KEYCLOAK_CA_BUNDLE") or True,
        internal_url=os.getenv("KEYCLOAK_INTERNAL_URL") or None,
    )


def _fernet() -> Fernet:
    key = hashlib.sha256(_env("SECRET_KEY").encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _seal(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def _unseal(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise HTTPException(401, "Agent session is no longer valid; sign in again") from exc


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _mcp_url() -> str:
    """Resolve the MCP endpoint from the Knowledge Fabric backend configuration.

    In Compose, MCP_PUBLIC_URL is the backend's configured public/service URL. The
    legacy GRAPHBASE_MCP_URL remains supported for existing local deployments.
    The URL is used server-side only; the browser never receives or calls MCP directly.
    """
    configured = os.getenv("MCP_PUBLIC_URL")
    if configured:
        base = configured.rstrip("/")
        return base if base.endswith("/mcp") else f"{base}/mcp"
    legacy = _env("GRAPHBASE_MCP_URL", "http://localhost:8100/mcp")
    return legacy.rstrip("/")


def _redirect_uri() -> str:
    return os.getenv("AGENT_REDIRECT_URI") or (
        f"{_env('AGENT_UI_URL', 'http://localhost:8005').rstrip('/')}/auth/callback"
    )


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _authorize_url(kc: KeycloakSession, state: str, nonce: str, verifier: str) -> str:
    params = {
        "client_id": kc.client_id,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": kc.scope,
        "state": state,
        "nonce": nonce,
        "code_challenge": _pkce_challenge(verifier),
        "code_challenge_method": "S256",
    }
    return f"{kc.endpoints['authorization_endpoint']}?{urlencode(params)}"


def _verify_id_token(token: str, kc: KeycloakSession, nonce: str) -> dict:
    try:
        jwks_url = f"{kc.internal_issuer}/protocol/openid-connect/certs"
        response = httpx.get(jwks_url, verify=kc.verify, timeout=15)
        response.raise_for_status()
        jwks = jwt.PyJWKSet.from_dict(response.json())
        kid = jwt.get_unverified_header(token).get("kid")
        key = next((item for item in jwks.keys if item.key_id == kid), None)
        if key is None:
            raise jwt.InvalidTokenError("Signing key not found")
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=kc.client_id,
            issuer=kc.issuer,
            options={"require": ["sub", "exp", "iss", "aud"]},
        )
    except (httpx.HTTPError, jwt.PyJWKClientConnectionError) as exc:
        raise HTTPException(503, "Keycloak is unreachable") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Invalid Keycloak ID token") from exc
    if claims.get("typ", "ID") != "ID" or not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise HTTPException(401, "Sign-in response did not match the request")
    if not claims.get("preferred_username"):
        raise HTTPException(401, "Keycloak token has no preferred_username")
    return claims


def _save_session(user: dict, tokens: dict) -> str:
    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    maximum = timedelta(hours=int(os.getenv("AGENT_SESSION_MAX_HOURS", "12")))
    idle = timedelta(minutes=int(os.getenv("AGENT_SESSION_IDLE_MINUTES", "60")))
    access_expires = now + timedelta(seconds=int(tokens.get("expires_in", 300)))
    with _connect() as conn:
        conn.execute(
            """INSERT INTO graphbase_agent_sessions
               (id, user_id, display_name, email, kc_access_token, kc_refresh_token, kc_access_expires_at,
                expires_at, idle_expires_at, modified_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                _hash_token(raw_token),
                user["user_id"],
                user.get("name") or user["user_id"],
                user.get("email"),
                _seal(tokens["access_token"]),
                _seal(tokens["refresh_token"]),
                access_expires,
                now + maximum,
                now + min(idle, maximum),
                user["user_id"],
            ),
        )
    return raw_token


def _session(request: Request) -> tuple[str, dict]:
    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token:
        raise HTTPException(401, "Sign in to continue")
    session_id = _hash_token(raw_token)
    now = datetime.now(UTC)
    ended = False
    with _connect() as conn:
        row = conn.execute(
            """SELECT * FROM graphbase_agent_sessions
               WHERE id = %s AND revoked_at IS NULL AND expires_at > %s AND idle_expires_at > %s""",
            (session_id, now, now),
        ).fetchone()
        if row is None:
            conn.execute(
                """UPDATE graphbase_agent_sessions SET revoked_at = now(), modified_by = 'system'
                   WHERE id = %s AND revoked_at IS NULL AND (expires_at <= %s OR idle_expires_at <= %s)""",
                (session_id, now, now),
            )
            ended = True
        else:
            max_idle = timedelta(minutes=int(os.getenv("AGENT_SESSION_IDLE_MINUTES", "60")))
            conn.execute(
                """UPDATE graphbase_agent_sessions SET idle_expires_at = least(expires_at, %s), modified_by = %s
                   WHERE id = %s""",
                (now + max_idle, row["user_id"], session_id),
            )
    if ended:
        raise HTTPException(401, "Your session has ended; sign in again")
    return session_id, row


def _store_tokens(session_id: str, kc: KeycloakSession) -> None:
    tokens = kc.tokens
    if not tokens.get("access_token") or not tokens.get("refresh_token"):
        raise LoginError("Keycloak session ended; sign in again")
    with _connect() as conn:
        conn.execute(
            """UPDATE graphbase_agent_sessions SET kc_access_token = %s, kc_refresh_token = %s,
                   kc_access_expires_at = %s, modified_by = 'system'
               WHERE id = %s AND revoked_at IS NULL""",
            (_seal(tokens["access_token"]), _seal(tokens["refresh_token"]),
             datetime.fromtimestamp(kc.expires_at, UTC), session_id),
        )


def _session_cookie(response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=_bool_env("AGENT_COOKIE_SECURE"),
        samesite="lax",
        path="/",
        max_age=int(os.getenv("AGENT_SESSION_MAX_HOURS", "12")) * 3600,
    )


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@app.get("/auth/login")
def login():
    kc = _keycloak()
    state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    expires = datetime.now(UTC) + timedelta(minutes=10)
    with _connect() as conn:
        conn.execute("DELETE FROM graphbase_agent_oidc_requests WHERE expires_at < now()")
        conn.execute(
            """INSERT INTO graphbase_agent_oidc_requests (state, nonce, code_verifier, expires_at)
               VALUES (%s, %s, %s, %s)""",
            (state, nonce, verifier, expires),
        )
    response = RedirectResponse(_authorize_url(kc, state, nonce, verifier), status_code=302)
    response.set_cookie(
        STATE_COOKIE, state, httponly=True, secure=_bool_env("AGENT_COOKIE_SECURE"),
        samesite="lax", path="/auth/callback", max_age=600,
    )
    return response


@app.get("/auth/callback")
def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    state_cookie = request.cookies.get(STATE_COOKIE, "")
    if error:
        return RedirectResponse("/?error=Keycloak+sign-in+was+not+completed", status_code=303)
    if not code or not state or not state_cookie or not hmac.compare_digest(state, state_cookie):
        return RedirectResponse("/?error=Invalid+sign-in+response", status_code=303)
    with _connect() as conn:
        pending = conn.execute(
            """DELETE FROM graphbase_agent_oidc_requests WHERE state = %s AND expires_at > now()
               RETURNING nonce, code_verifier""",
            (state,),
        ).fetchone()
    if pending is None:
        return RedirectResponse("/?error=Sign-in+request+expired", status_code=303)

    kc = _keycloak()
    try:
        tokens = kc._token_request(
            {"grant_type": "authorization_code", "code": code, "redirect_uri": _redirect_uri(),
             "code_verifier": pending["code_verifier"]}
        )
    except LoginError as exc:
        log.info("Keycloak agent sign-in failed: %s", exc)
        return RedirectResponse("/?error=Sign-in+failed", status_code=303)
    if not tokens.get("access_token") or not tokens.get("refresh_token"):
        raise HTTPException(401, "Keycloak did not return an access and refresh token")
    claims = _verify_id_token(tokens.get("id_token", ""), kc, pending["nonce"])
    user = {
        "user_id": claims["preferred_username"],
        "name": claims.get("name") or claims["preferred_username"],
        "email": claims.get("email"),
    }
    raw_token = _save_session(user, tokens)
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(STATE_COOKIE, path="/auth/callback", httponly=True, samesite="lax")
    _session_cookie(response, raw_token)
    return response


@app.get("/api/session")
def session_status(request: Request):
    try:
        _session_id, row = _session(request)
    except HTTPException as exc:
        if exc.status_code == 401:
            return {"authenticated": False}
        raise
    return {"authenticated": True, "user": {
        "user_id": row["user_id"], "display_name": row["display_name"], "email": row["email"]
    }}


@app.post("/api/chat")
async def chat(body: ChatRequest, request: Request):
    if not body.message.strip():
        raise HTTPException(422, "Message cannot be blank")
    session_id, row = _session(request)
    lock = _agent_locks.setdefault(session_id, asyncio.Lock())
    async with lock:
        try:
            from graphbase_agent.agent import GraphbaseAgent, get_llm
        except ModuleNotFoundError as exc:
            if exc.name != "graphbase_agent":
                raise
            from agent import GraphbaseAgent, get_llm

        kc = _keycloak()
        tokens = {
            "access_token": _unseal(row["kc_access_token"]),
            "refresh_token": _unseal(row["kc_refresh_token"]),
        }
        kc.restore_tokens(tokens, row["kc_access_expires_at"].timestamp())
        bot = _agents.get(session_id)
        if bot is None:
            bot = GraphbaseAgent(
                kc,
                _mcp_url(),
                get_llm(),
                verify=os.getenv("KEYCLOAK_CA_BUNDLE") or True,
            )
            _agents[session_id] = bot
        else:
            bot.session = kc
        try:
            result = await bot.ask(body.message.strip())
            answer = result if isinstance(result, str) else "".join(
                item.get("text", "") for item in result if isinstance(item, dict)
            )
            if not answer:
                answer = str(result)
            return {"answer": answer}
        except LoginError as exc:
            _agents.pop(session_id, None)
            with _connect() as conn:
                conn.execute(
                    "UPDATE graphbase_agent_sessions SET revoked_at = now(), modified_by = %s WHERE id = %s",
                    (row["user_id"], session_id),
                )
            raise HTTPException(401, "Keycloak session ended; sign in again") from exc
        except Exception as exc:
            log.exception("Agent chat failed for user %s", row["user_id"])
            raise HTTPException(502, "The agent could not complete the request") from exc
        finally:
            if kc.signed_in:
                _store_tokens(session_id, kc)


@app.post("/api/logout")
def logout(request: Request):
    raw_token = request.cookies.get(SESSION_COOKIE)
    if raw_token:
        session_id = _hash_token(raw_token)
        with _connect() as conn:
            row = conn.execute(
                """UPDATE graphbase_agent_sessions SET revoked_at = now(), modified_by = user_id
                   WHERE id = %s AND revoked_at IS NULL RETURNING user_id, kc_refresh_token""",
                (session_id,),
            ).fetchone()
        if row:
            _agents.pop(session_id, None)
            _agent_locks.pop(session_id, None)
            try:
                kc = _keycloak()
                kc.restore_tokens({"refresh_token": _unseal(row["kc_refresh_token"])}, 0)
                kc.logout()
            except (LoginError, HTTPException):
                log.warning("Keycloak logout failed for agent user %s; local session was revoked", row["user_id"])
    response = JSONResponse({"signed_out": True})
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, secure=_bool_env("AGENT_COOKIE_SECURE"),
                           samesite="lax")
    return response


@app.get("/")
def index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.is_file():
        raise HTTPException(503, "Agent UI assets are not built; run npm run build in agent/ui")
    return FileResponse(index_file)


if (STATIC_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")
