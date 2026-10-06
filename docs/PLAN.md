# webos — plan

Status: **milestone 1 implemented** (2026-10-01) and tested locally against Docker
Desktop; not deployed yet. Covers the architecture, the security setup and milestone 1 in
detail, and milestones 2–4 in outline.

Decisions since the first draft:
- **No Tailscale for now.** The panel is reached through an SSH tunnel (§3, §11). That
  keeps it off the internet with no new software. Tailscale is still an option later.
- MIT licence. No `mobile/` app: the web UI works on a phone. Backend managed with uv.

webos is a self-hosted panel for one VPS (Docker Compose stacks on
loopback ports behind the host's nginx and certbot). It replaces the manual "add a site"
routine and puts day-to-day operations in the browser.

---

## 1. Principles

1. **Root-equivalent by design, so access is the main defense.** The panel talks to the
   Docker API, and milestone 4 adds a terminal. Anyone who fully logs in can eventually get
   root. The panel can't be reached from the internet, and getting in takes SSH access to
   the server (for the tunnel), a password and a TOTP code.
2. **Each milestone adds only the privilege it needs.** Milestone 1 never touches the raw
   Docker socket or any host path. Every later privilege comes in through a mechanism that
   is easy to see and audit.
3. **Live state is read live.** Containers, logs, nginx and git are always fetched from
   the server and never cached in the database.
4. **The panel never touches SSH or the firewall.** It doesn't change sshd config,
   `ssh.socket`, `ssh.service` or ufw rules. Where
   possible this is enforced by mechanism, not just by keeping the code free of it
   (see §8 and §12).
5. **Project secrets stay in each project's `.env` on disk.** They never go into the
   database, the audit log or an API response unless you explicitly ask to see them.

---

## 2. Architecture

```
 laptop ── ssh -L 9000:127.0.0.1:9000 ──┐   (browser: http://localhost:9000)
                                        ▼
 VPS host       sshd (unchanged, as today)
                    │
                    ▼  127.0.0.1:9000   (loopback only — no nginx block, no public bind)
 ┌─ compose project "webos" ────────────────────────────────────────┐
 │  webos         uid 1001 · read-only rootfs · cap_drop ALL         │
 │                FastAPI + built React SPA · SQLite in ./data       │
 │                   │  http://socket-proxy:2375  (internal network) │
 │                   ▼                                               │
 │  socket-proxy  allows  GET containers / events / info / version,  │
 │                        POST start / stop / restart                │
 │                denies  create, exec, build, images, volumes, ...  │
 └──────────────────┬───────────────────────────────────────────────┘
                    ▼  /var/run/docker.sock
                 dockerd ── the sites' compose stacks

 M2+: webos-agent — host systemd service on /run/webos/agent.sock, fixed verbs only
```

| Milestone | New privilege | Comes in through |
|---|---|---|
| 1 Dashboard | Read containers, events, logs, stats, disk usage; start/stop/restart | Filtered Docker socket proxy; read-only host `/proc/1/net/dev` |
| 2 New site | Write nginx sites, run certbot, compose up/build, deploy keys | Host agent, fixed verb set |
| 3 Git + files | Read/write inside `~/apps/<project>` | Path-confined bind mount; git via agent |
| 4 Terminal | Interactive shell | Host agent PTY, step-up auth |

Decisions:

- **Same origin.** FastAPI serves the built SPA as static files, so there's no CORS and
  no second server.
- **One uvicorn worker.** The login throttle and the live-event fan-out live in memory,
  which is fine for a single user.
- **Thin async Docker client** (`httpx` against the Engine API, about 8 functions) instead
  of docker-py. The module lists every endpoint the panel calls, which is the same list the
  proxy allows. Log frames are demultiplexed by hand: an 8-byte header, then stdout or
  stderr.
- **Live updates use Server-Sent Events** for status and logs. A WebSocket is used only
  for the terminal (milestone 4).
- **The database holds four things:** the user's login, projects, deployments (milestone 2)
  and the audit log. There is no sessions table (§4).

---

## 3. Network exposure

- The container publishes **only `127.0.0.1:9000`**. This is outside the 8000+ range the
  wizard will hand out to projects. Add it to the port registry.
- **Access is an SSH tunnel:** `ssh -L 9000:127.0.0.1:9000 you@your-server`,
  then open `http://localhost:9000`. It reuses the SSH you already have, needs no new
  software, and changes nothing on the server. That origin is the default in
  `WEBOS_ALLOWED_ORIGINS`, and browsers accept `Secure` cookies on localhost.
- **No nginx server block for the panel.** Even with wildcard DNS (so `webos.example.com`
  resolves), nginx has nothing to serve under that name.
- Docker must be version 28 or later. Older engines let hosts on the same L2 segment reach
  ports published on `127.0.0.1`.

**Decision (2026-10-03): the panel is served publicly on a subdomain**, behind host nginx
and certbot like the other sites, using `deploy/nginx-site.conf`. On top of the app's own
protections, that file rate-limits `/api/auth/login` and overwrites `X-Forwarded-For`, and
webos trusts that header only from Docker's bridge range (`WEBOS_FORWARDED_ALLOW_IPS`).
That way the throttle and the audit log see real client IPs, and a stranger can't lock the
owner out. Turning on 2FA is strongly recommended. The SSH tunnel keeps working as a
fallback, because `http://localhost:9000` stays in the allowed origins.

**Other options considered:**

- **Tailscale.** `tailscale serve` gives a private HTTPS address that only your devices
  can reach. Join with a plain `tailscale up` (never `--ssh`), never enable Funnel, and
  don't follow Tailscale's "secure an Ubuntu server" guide past installation. That guide
  removes the public SSH rule, and GitHub Actions deploys need public port 22.
- **A public subdomain** behind host nginx and certbot like any other project. Only do this
  with an extra lock in front: nginx client certificates, or at least nginx basic auth so
  bots never reach the app's own login code. Also set `WEBOS_FORWARDED_ALLOW_IPS` so the
  login throttle sees real client IPs. Note that the exact-origin check matters here:
  SameSite cookies treat every `*.example.com` site as same-site.

---

## 4. Authentication and sessions

- **Single user, created from the CLI inside the container**
  (`webos-admin create-user`). There's no signup route and no "first visitor becomes
  admin" race.
- **2FA is optional, off by default** (changed 2026-10-03, while testing). Sign-in is
  username + password. `webos-admin enable-totp` adds a code from a phone app: the login
  form asks for it only after the right password. Behind the SSH tunnel, password-only is
  reasonable, since reaching the panel already needs SSH access to the server. **Turn 2FA
  on before exposing the panel any other way** (Tailscale or a public address).
- **Passwords** use argon2id (argon2-cffi). **TOTP** uses RFC 6238 via pyotp with a ±1
  step window. The last used step is stored so a code can't be replayed.
- **Login is one request** with username, password and code. It returns a generic error.
  If the user doesn't exist, a dummy hash is still checked so the timing doesn't reveal it.
- **Throttling** is in memory, per client IP. After 5 failures there's a delay that
  doubles each time, and after 10 the login locks for 15 minutes. There's deliberately no
  global lock: TOTP already makes guessing hopeless, and a global lock would let anyone
  lock the owner out. Every evaluated attempt is audited, including which factor failed
  (`bad_code` means someone has the password). Throttled attempts go to stdout only, so a
  flood can't fill the disk.
- **The session is a signed cookie**, `__Host-webos` (HttpOnly, Secure, SameSite=Strict,
  Path=/). Its payload is `{uid, ver, iat, seen}`. It expires after 30 minutes idle and
  12 hours absolute. `ver` must equal `users.session_version`, which is bumped on "log out
  everywhere", a password change or a TOTP reset. That ends every session without a
  sessions table.
- **The TOTP secret is encrypted at rest** (Fernet). The key is derived from
  `WEBOS_SECRET_KEY` in the panel's own `.env`, so a leaked SQLite backup alone is not
  enough.
- **Recovery** is `webos-admin reset-password` / `disable-totp` over SSH. SSH is the
  recovery path, so there are no recovery codes.
- **Long-lived streams end with the session.** Log and event streams re-check the
  session every 30 seconds. They close at the idle or absolute deadline, or as soon as
  "log out everywhere" bumps the version.

---

## 5. Request protections

- **CSRF and cross-site WebSocket hijacking:** SameSite=Strict, plus the `Origin` header
  must be in `WEBOS_ALLOWED_ORIGINS` on every non-GET request, SSE stream and WebSocket
  handshake. Mutations also require an `X-WebOS: 1` header. That forces a CORS
  preflight, and no CORS is configured, so cross-site pages can't send one.
- **XSS: treat log lines as hostile input.** Anyone on the internet can write text into a
  public site's access log. The same goes for container names, labels and nginx errors.
  Everything is rendered as text, with no `dangerouslySetInnerHTML`. ANSI colors are
  turned into styled spans by a small parser of our own, which is unit-tested. CSP:
  `default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none';
  frame-ancestors 'none'`.
- **Other headers:** HSTS, `nosniff`, `Referrer-Policy: no-referrer`, and
  `Cache-Control: no-store` on `/api`. OpenAPI and `/docs` are disabled outside dev.
- **Input validation:** container IDs must match `^[a-f0-9]{12,64}$` and project slugs
  `^[a-z0-9][a-z0-9-]{0,39}$`. Both are checked before going into a Docker API URL, so a
  value like `../create` can't reach the engine.
- **Secrets in container inspect:** `GET /containers/{id}/json` returns `Config.Env`,
  which includes everything a project loads from its `.env`. The Docker client strips it
  first, so no other code ever sees it.

---

## 6. Destructive actions

| Tier | Examples | UI | Server requires |
|---|---|---|---|
| Read | List, inspect, logs | — | Session |
| Change | Start, import project | — | Session + origin check, audited |
| Disruptive | Stop, restart, unregister project | Confirm dialog naming the target | `confirm` field equal to the target name |
| Irreversible (M2+) | Delete project, remove volumes, remove nginx site, open terminal | Type the name, re-enter TOTP | `confirm` + TOTP verified in the last 5 min |

- The server checks `confirm`, so even a raw API call has to name its target.
- Actions only work on containers of **registered** projects. Unmanaged containers are
  view-only until imported.
- **Self-protection:** the panel refuses to stop or restart its own compose project.
  Doing so would take away the UI needed to bring it back.

---

## 7. Audit log

- Every mutating request, login attempt and logout writes a row: `ts, request_id, actor,
  action, target, params, outcome, error, ip, user_agent`. `params` keeps only allowlisted
  keys per action and never values from `.env`.
- Each action writes two rows, `started` and then `ok` or `error`, sharing a `request_id`.
  The table is append-only, so rows are never updated.
- **SQLite triggers `RAISE(ABORT)` on any UPDATE or DELETE** of `audit_events` (created in
  the Alembic migration). Each row is also written as a JSON line to stdout, so
  `docker logs` holds a second copy.
- To be honest about it: this guards against bugs and mistakes, not against root on the
  host.
- Milestone 1 ships an audit page with filters for action, target and date.

---

## 8. Container hardening

The actual file is [docker-compose.yml](../docker-compose.yml). In short: the panel runs as
uid 1001 with a read-only root filesystem, no capabilities and `no-new-privileges`, and it
mounts only `./data`. The proxy (linuxserver/socket-proxy, pinned by digest) sits on an
`internal` network with no route out.

**The proxy is the real filter.** `:ro` on a socket mount doesn't limit API calls. What
matters is what the proxy denies. With container create, exec and build blocked, the
milestone 1 panel can't turn the Docker socket into a host root shell (`docker run -v
/:/host`). This proxy version also refuses reading container filesystems (`archive`,
`export`) and `top` unless they're explicitly enabled, and webos doesn't enable them.

Verified locally from inside the panel container:
- **refused (403):** create (with a `/:/host` bind), exec, archive, export, build, images,
  volumes
- **allowed:** listing containers, and kill (`ALLOW_RESTARTS` covers stop, restart and
  kill)

---

## 9. Data model (milestone 1)

| Table | Columns |
|---|---|
| `users` (one row) | id, username, password_hash, totp_secret_enc, totp_last_step, session_version, created_at, password_changed_at |
| `projects` | id, slug, display_name, compose_project, working_dir, domain?, port?, repo_url?, created_at |
| `audit_events` | id, ts, request_id, actor, action, target, params_json, outcome, error, ip, user_agent |

`projects.port` is the **assigned** loopback port. It's configuration the wizard needs for
allocation, not live state. The ports actually bound are always read from Docker.
Milestone 2 adds `deployments`. Alembic runs with `render_as_batch=True` because SQLite
supports little ALTER.

---

## 10. Milestone 1 — dashboard

### Features

- **Login and logout**, including "log out everywhere".
- **Dashboard:** registered projects and their containers. Each shows state, health,
  uptime, restart count, last exit code, OOMKilled and published ports, with live updates
  from Docker events over SSE. Warning badges:
  - restarting / unhealthy / exited with a non-zero code
  - **port published on `0.0.0.0` or `::`**: it skips ufw entirely (the `-p 3306:3306`
    landmine)
- **Unmanaged section:** compose projects and containers that aren't registered, each with
  an **Import** button. Import pre-fills slug, compose project and working directory from
  the `com.docker.compose.*` labels, so existing sites come in on day one without
  reading any files.
- **Project page:** containers, with start/stop/restart for each container or for the whole
  project, plus the log viewer.
- **Log viewer:** SSE stream (follow, tail N, timestamps), with stdout and stderr kept
  apart. Has an "errors only" toggle (stderr plus `error|exception|traceback|fatal|panic|critical`),
  a text filter, pause/autoscroll, and a cap of 5,000 lines in the browser.
- **Audit page.**
- **Header:** Docker version and container counts.

Out of scope for milestone 1: compose up/down (it needs container create, which the proxy
denies), nginx, `.env` editing, git, files, terminal and deploy. "Start project" restarts
existing containers. If a stack was removed with `compose down`, bringing it back is
milestone 2.

### API

```
POST   /api/auth/login | /logout | /logout-all        GET /api/auth/me
GET    /api/overview                                   projects + containers + unmanaged
GET    /api/events                                     SSE: container state changes
POST   /api/projects                                   import
PATCH  /api/projects/{slug}       DELETE /api/projects/{slug}   (unregister only)
POST   /api/projects/{slug}/{start|stop|restart}
POST   /api/containers/{id}/{start|stop|restart}
GET    /api/containers/{id}/logs?tail=&since=          SSE
GET    /api/audit?action=&target=&before=
GET    /healthz                                        no auth, returns {"ok": true} only
```

### Layout

```
backend/
  pyproject.toml, uv.lock, alembic.ini, alembic/
  webos/
    main.py  config.py  db.py  models.py  audit.py  docker_api.py  cli.py
    security/  passwords.py  totp.py  sessions.py  origin.py  throttle.py
    routers/   auth.py  overview.py  projects.py  containers.py  audit.py
  tests/
frontend/
  src/  api/  pages/ (Login, Dashboard, Project, Audit)  components/ (ConfirmDialog, LogViewer, StatusBadge)
Dockerfile               multi-stage: node builds the SPA → python:3.12-slim runtime
docker-compose.yml       §8
docker-compose.dev.yml   local: hot reload, Vite proxy
docs/  architecture.md  security.md (threat model)  setup.md
.github/workflows/ci.yml lint, types, tests, audit, image build — no deploy job
README.md  SECURITY.md  LICENSE  .env.example
```

Backend dependencies: fastapi, uvicorn, sqlalchemy, alembic, pydantic-settings,
argon2-cffi, pyotp, itsdangerous, cryptography, httpx and segno (terminal QR code). Dev
adds pytest, respx, ruff and mypy. Frontend additions are kept small: react-router and
@tanstack/react-query, with plain CSS and no UI kit.

### Tests

Backend (Docker API faked with respx):
- wrong code, replayed code, lockout, idle and absolute expiry, version bump
- origin rejection on POST, SSE and WebSocket
- missing or wrong `confirm`
- malformed IDs never reaching the engine
- self-protection
- `Config.Env` stripped
- audit triggers refusing UPDATE and DELETE

Frontend: the ANSI and log parser, since it's security-relevant, plus tsc, eslint and
build.

### Verification and definition of done

1. **Locally first (done 2026-10-01):** the full stack on Docker Desktop against the local
   engine.
   - created a user with the real CLI, then signed in
   - imported a test stack and restarted a container; the audit log shows `started`,
     then `ok`
   - log lines carrying `<script>` and `<img onerror>` render as plain text, with no
     console errors
   - the socket proxy refuses dangerous calls (§8)
2. **On the server:**
   - reachable through the SSH tunnel
   - refused on `<server-ip>:9000` from outside
   - `webos.<your-domain>` doesn't serve it
   - the existing sites imported
   - a restart from the UI shows up in the audit log

---

## 10b. Server stats (added 2026-10-03, before the first deploy)

The Server page shows host CPU %, load, memory and swap, disk, network rates, Docker's
disk usage and each running container's CPU, memory and traffic.

- **CPU, memory, load and uptime come from `/proc` inside the container.** That already
  reports the host kernel, so no mount is needed.
- **Disk is the filesystem holding `./data`.** On the VPS that's the root disk.
- **Network needs the host's counters.** Network counters are per namespace, so compose
  mounts the host's `/proc/1/net/dev` read-only. It holds byte counters and nothing else.
  Loopback, `docker0`, `br-*` and `veth*` are skipped, so traffic isn't counted twice.
- **The proxy gained two read-only permissions.** Container `stats` (already covered by
  `CONTAINERS`) and `SYSTEM=1` for `GET /system/df`. Writes stay blocked by `POST=0`.
- **Caching.** A sampler reads the host every 5 s and keeps 30 minutes of history *in
  memory* (never in the database; a restart starts it afresh). Container stats are fetched
  on demand at most every 10 s, and `system df` (slow) at most every 60 s, so nothing
  loads Docker while nobody is looking.

Later (milestone 2, through the host agent): cleanup actions such as pruning unused
images and build cache.

## 11. Server setup for milestone 1

You run these; I'll give them one at a time when we get there. Here they are in order:

1. Push this repo to GitHub, then clone it into `~/apps/webos` on the server.
2. Create `.env` from `.env.example`: a fresh `WEBOS_SECRET_KEY`, UID/GID 1001.
3. Create `data/` (owned by ali, so uid 1001).
4. `docker compose up -d --build`.
5. `webos-admin create-user` inside the container, then scan the QR code with your phone.
6. From the laptop, open the SSH tunnel and sign in at `http://localhost:9000`.
7. Run the server checks from §10.
8. Record port 9000 in the port registry (I'll edit the notes file).

Never part of setup: sshd config, `ssh.socket`/`ssh.service`, ufw changes.

The panel itself isn't push-to-deployed, at least at first. A compromised GitHub account
would mean code running as the panel, so updates go through SSH: `git pull && docker
compose up -d --build`.

---

## 12. Later milestones (outline)

**2 — New site wizard. Implemented 2026-10-06.**

*The host agent* (`agent/webos_agent.py`): one stdlib-only Python file, run by systemd as
root and installed by `agent/install.sh`. It listens on `/run/webos-agent/agent.sock`,
mode 0660, group `webos-agent`; the panel gets that group through `group_add`. The
protocol is one JSON request per connection, answered with streamed log lines and a final
result. It accepts a fixed set of verbs:

- `ping`, `ports`
- `deploy_key`, `clone`, `head`, `pull`, `remote_head`
- `find_compose`, `compose_config`, `env_example`, `read_env`, `write_env`
- `up`, `down`, `http_check`
- `nginx_site`, `nginx_remove`, `certbot`, `cert_delete`, `discard`

How it stays safe:

- Every argument is validated: names, branches, repo URLs, domains, ports, and paths
  confined to the project folder.
- Commands run as argument lists, never through a shell, and git and docker run as the
  apps user.
- It never overwrites or removes an nginx site without its marker, refuses a domain
  another enabled site already serves, and rolls back when `nginx -t` fails. nginx is
  reloaded with a signal.
- Its systemd sandbox: `ProtectSystem=strict` with only the paths it needs writable, and
  `/etc/ssh`, `~/.ssh` and systemd's control sockets inaccessible.
- Docker access is still root-equivalent. That's why `up` re-runs the **safety check** on
  the merged `docker compose config`, refusing public ports, privileged mode, host
  namespaces, extra capabilities, devices, binds outside the project and the Docker
  socket.

*The production layer* (`webos/compose_override.py`). The repository stays untouched.
webos writes `docker-compose.webos.yml` next to the compose file, using Compose's
`!override` and `!reset` tags:

- the web service is published on `127.0.0.1:<assigned port>` only;
- every other service publishes nothing;
- everything restarts unless stopped;
- optionally, dev-only bind mounts (`.:/app`) and dev commands (`--reload`) are dropped.

The wizard suggests these choices. You can edit the layer, and it's stored in the
database; it contains no secrets.

*Deploy keys and push-to-deploy, decided.* Neither touches SSH on the server:

- **Private repos:** the agent creates a per-site key under `~/apps/.webos/keys` that git
  uses to *fetch*. The repo owner adds its public half as a read-only Deploy key on
  GitHub. GitHub's host keys are pinned from `api.github.com/meta` over TLS.
- **Push-to-deploy:** auto-deploy polls `git ls-remote` every minute and redeploys on a
  new commit. It doesn't retry a commit that failed, and needs no webhooks, Actions
  secrets or `authorized_keys` entries.

*Pipelines* (`webos/deployer.py`): one at a time per site, streamed live over SSE and
saved as history.

- **create:** write the env, safety check, build and start, health check on
  `127.0.0.1:<port>`, DNS must point at this server, nginx site, certificate. Safe to
  retry after a failure, because every step is idempotent.
- **manual / auto:** pull, check, build, health check.
- **env:** write the env, check, rebuild, health check.

*Secrets:* the env content goes from the browser straight to the agent, which writes the
file owner-only. The panel never stores or logs it; audit rows record key names only.
Reading the env back is itself audited. Removing a site requires the typed name, plus a
fresh code when 2FA is on.

*Tests:*

- Unit tests for the agent (validation, policy, nginx handling, rollback) and for the
  panel (wizard, pipelines, auto-deploy, secrecy), using a fake agent.
- An end-to-end run on Docker Desktop: the real agent as root in an Ubuntu container with
  real nginx, git and Compose deployed `docker/awesome-compose`'s flask app. The run
  covered clone, layer, build, health check, a real DNS check via nip.io, nginx, then
  redeploy, env edit and removal.
- On real files, the agent refused webos's own compose file (Docker socket, outside bind)
  and a `--upload-pack` injection.

**3 — Git and files.** Mount `~/apps` at the same path. Every path goes through
realpath and must stay under the project's `working_dir`; symlinks that escape it are
rejected. `.env` is masked, and revealing it is an audited action. Writes are atomic with
size limits. git runs via subprocess with argument lists and `--`. Push credentials are
decided in milestone 3.

**4 — Terminal.** xterm.js over WebSocket, with the PTY spawned by the agent. This is
root-equivalent by nature. Here "never touch SSH" becomes **policy, not mechanism**. It's
gated by a fresh TOTP, has an idle timeout, allows one session at a time, and records
start and stop in the audit log. Still to decide: run it as the admin user (who has sudo) or a
separate user without sudo, which is still root-equivalent if it's in the docker group.

---

## 13. Open questions

None blocking. Possible follow-ups: GitHub webhooks for instant deploys, now that the
panel is reachable publicly; static-site support, for a site with no compose file; and a
warning when a repository tracks its `.env` in git, since pulls would reset it.
