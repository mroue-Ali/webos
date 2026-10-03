# syntax=docker/dockerfile:1

# 1. Build the React frontend.
FROM node:26-alpine AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2. Install the backend and its locked dependencies into a virtualenv.
FROM python:3.12-slim AS backend
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev --no-editable

# 3. Runtime: the virtualenv and the built frontend, nothing else.
FROM python:3.12-slim
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WEBOS_STATIC_DIR=/app/static \
    WEBOS_DATABASE_URL=sqlite:////data/webos.db
COPY --from=backend /opt/venv /opt/venv
COPY --from=frontend /src/dist /app/static
WORKDIR /app
# Overridden by docker-compose.yml (WEBOS_UID/WEBOS_GID); never root.
USER 1001:1001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
CMD ["webos-admin", "serve"]
