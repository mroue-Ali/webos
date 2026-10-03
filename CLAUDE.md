# webos

Self-hosted control panel for one Docker Compose VPS. It will be a public GitHub repo, so
keep it clean and documented. The design, threat model and milestones are in
`docs/PLAN.md`. Read it before changing anything security-related.

## Layout
- `backend/`: FastAPI app (package `webos`), SQLite via SQLAlchemy 2 + Alembic
  (migrations in `webos/migrations`), managed with uv. Admin CLI: `webos-admin`.
- `frontend/`: React + TypeScript + Vite. Built into the image and served by the backend
  (same origin, no CORS).
- `docker-compose.yml`: the panel plus a filtering Docker socket proxy.
  `docker-compose.dev.yml` exposes the proxy on 127.0.0.1:2375 for local development.

## Commands
- Backend (in `backend/`): `uv run pytest`, `uv run ruff check .`,
  `uv run ruff format .`, `uv run mypy`
- Frontend (in `frontend/`): `npm run lint`, `npm test`, `npm run build`
- Full stack: `docker compose up -d --build`, then http://localhost:9000

## Rules
- Never commit `.env`, `backend/.env`, `data/` or `*.env.local` (`dev-user.env.local`
  holds the local test login).
- The panel must never touch sshd config, `ssh.socket`/`ssh.service`, or ufw.
- Every Docker endpoint lives in `backend/webos/docker_api.py`, and the socket proxy env
  in `docker-compose.yml` must allow exactly those. Never widen the proxy casually.
- Server stats (`webos/metrics.py`) read the host via `/proc` and a read-only
  `/proc/1/net/dev` mount. History is in memory only, never in the database.
- Every state change is audited (`webos.audit.record_request` / `audited`). Disruptive
  actions require `confirm` = the target's name, checked on the server.
- The database stores only the user, projects, deployments and the audit log. Live state
  is read from Docker every time. Project secrets never reach the database, the logs or
  API responses (`inspect` strips `Config.Env`).
- `frontend/src/api/types.ts` mirrors `backend/webos/schemas.py`.
- Log text is attacker-controlled: render it as text through `lib/ansi.ts`, never with
  `dangerouslySetInnerHTML`.
- Pydantic patterns run on Rust regex, which has no look-around.
- Files are LF (`.gitattributes`). This is a Windows machine, so check after scripted
  edits.
