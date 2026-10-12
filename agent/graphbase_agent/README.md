# TCS Knowledge Fabric Agent UI

The standalone agent UI signs users in through Keycloak, then sends chat requests from the server to the
existing MCP server. Keycloak tokens are encrypted in PostgreSQL; the browser receives only an HttpOnly
session cookie.

## Local development

1. For the Vite development UI, ensure the `graphbase-agent` Keycloak client allows the redirect URI
   `http://localhost:8006/auth/callback` and has Standard Flow enabled with PKCE S256. The Docker-hosted UI
   instead uses `http://localhost:8005/auth/callback`.
2. Configure `KEYCLOAK_URL`, `KEYCLOAK_INTERNAL_URL`, `KEYCLOAK_REALM`, `SECRET_KEY`, Postgres settings,
   `AGENT_UI_URL=http://localhost:8006` for Vite development (or `http://localhost:8005` for Docker), and
   `MCP_PUBLIC_URL=http://localhost:8100` (the backend-configured MCP base URL) or legacy `GRAPHBASE_MCP_URL=http://localhost:8100/mcp` in the environment. `KEYCLOAK_URL` should point to the
   browser-facing Keycloak host, such as `http://localhost:8080`; Vite proxies both `/api` and `/auth` to the
   agent backend on port 8005.
   The agent client must issue an access token whose audience contains `graphbase-mcp`.
3. Build the UI and start the API:

   ```powershell
   Set-Location agent\ui
   npm install
   npm run build
   Set-Location ..
   uv run --project graphbase_agent uvicorn graphbase_agent.web:app --env-file graphbase_agent/.env --host 0.0.0.0 --port 8005
   ```

   For live frontend development, run `npm run dev` in `agent\ui`; Vite serves the UI at port 8006 and sends
   both API and auth requests to the agent backend at port 8005.

   If already in `agent\graphbase_agent` with its virtual environment active, the equivalent direct command
   is `uvicorn web:app --env-file .env --reload --port 8005`. Both import styles are supported.

## Docker Compose

Start `agent-ui` alongside the regular services, then open `http://localhost:8005`. The `AGENT_UI_URL` value is
the browser-facing address and must be registered as the Keycloak client's callback URL. Set
`AGENT_COOKIE_SECURE=true` when serving the UI over HTTPS.

The UI never receives an access or refresh token. Chat and logout API requests require the same custom CSRF
header as the main application. Agent sessions have idle and absolute expiry and are revoked at logout.


## Ports and authorization

- Agent API: `http://localhost:8005`
- Agent UI (Vite development): `http://localhost:8006`
- In Docker, the built UI is served by the agent API on port `8005`; the Vite dev server is not needed.
- The agent sends the signed-in user's Keycloak access token to the MCP server. MCP verifies issuer, signature, audience, expiry, and required scopes; each tool also checks the user's Knowledge Fabric permissions for the requested KB. Do not expose MCP directly to the browser or use a shared service token for user queries.
- For Vite development, set `AGENT_UI_URL=http://localhost:8006` in the agent backend environment and register `http://localhost:8006/auth/callback` in the Keycloak client. For Docker, use `AGENT_UI_URL=http://localhost:8005` and register the port-8005 callback.
