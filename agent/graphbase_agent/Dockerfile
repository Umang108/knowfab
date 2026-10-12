FROM node:20-alpine AS ui-build
WORKDIR /ui
COPY agent/ui/package.json agent/ui/package-lock.json ./
RUN npm ci
COPY agent/ui/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.6 /uv /uvx /bin/
WORKDIR /app/agent/graphbase_agent
COPY agent/graphbase_agent/pyproject.toml agent/graphbase_agent/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY agent/graphbase_agent/README.md agent/graphbase_agent/__init__.py ./
COPY agent/graphbase_agent/agent.py agent/graphbase_agent/keycloak.py agent/graphbase_agent/web.py ./
COPY --from=ui-build /ui/dist ./static
ENV PATH="/app/agent/graphbase_agent/.venv/bin:$PATH"
ENV PYTHONPATH="/app/agent"
EXPOSE 8005
CMD ["uvicorn", "graphbase_agent.web:app", "--host", "0.0.0.0", "--port", "8005"]
