# webos

A self-hosted control panel for a single VPS that runs its sites as Docker Compose stacks
behind a host nginx. See what's running, start/stop/restart it, and follow live logs from
the browser, with every change written to an audit log.

> **Status: milestones 1 and 2** (dashboard, new-site wizard). Next up: git and a file
> editor, then a web terminal. See [docs/PLAN.md](docs/PLAN.md).

## What it does today

- **New site wizard:** give it a repository, a domain and the env vars; it clones the
  repo, puts the app on a free loopback port behind nginx, gets the HTTPS certificate and
  deploys, with the whole log streamed live. Private repositories get a read-only deploy
  key. The repository's compose file is used as it is, with a small production layer on
  top (loopback-only port, private databases, no dev mounts or `--reload`), checked by a
  safety check before anything starts.
- **Deployments:** "Deploy now", optional auto-deploy when the branch gets a new commit
  (checked every minute), full history with logs, an environment editor, and site removal.
- **Server page:** CPU, memory, swap, load, disk, and network in/out with 30-minute
  trend lines; how much disk Docker's images, volumes and build cache take; each running
  container's CPU, memory and traffic.
- **Dashboard:** every compose project and container on the host, with state, health,
  restarts, exit codes and published ports. Updates live from Docker events.
- **Warnings:** crash loops, failing health checks, OOM kills, and **ports published on
  `0.0.0.0`**. Docker writes its own iptables rules, so those ports bypass ufw.
- **Control:** start, stop and restart a container or a whole project. Stop and restart
  need confirmation. Only projects you've registered can be controlled; anything else is
  view-only.
- **Live logs:** follow any container's logs, with stdout and stderr kept apart, an
  errors-only filter, search, and ANSI colours.
- **Audit log:** every sign-in attempt and every change. Rows can't be edited or
  deleted, and each one is mirrored to `docker logs`.

## Security model

webos can control your containers. Later milestones add a terminal, so it is effectively
root on the server. The design follows from that:

- **Not on the internet by default.** The panel listens only on `127.0.0.1:9000`. Reach it
  through an SSH tunnel (or a private network such as Tailscale). There is no nginx site
  for it.
- **Password login** with argon2id hashing and login throttling, plus **optional 2FA** (a
  6-digit code from an authenticator app; turn it on with `webos-admin enable-totp`). The
  single user is created from the command line, so there's no signup page.
- **No raw Docker socket.** The panel talks to Docker only through a
  [filtering proxy](https://github.com/linuxserver/docker-socket-proxy) that allows
  list/inspect/logs/stats/events, disk usage, and start/stop/restart. Creating containers, exec, builds,
  images, volumes and reading container filesystems are all refused, so a bug in webos
  can't become a root shell through Docker.
- **Hardened container:** runs as a non-root uid, read-only root filesystem, every Linux
  capability dropped, `no-new-privileges`. The only host paths it sees are its own data
  folder and, read-only, the host's network byte counters (`/proc/1/net/dev`).
- **Request protections:** exact-origin checks on every state-changing request (not just
  SameSite cookies), a strict CSP, and log lines always rendered as text, because anyone
  can write into a public site's logs.
- **Secrets stay out:** project `.env` values are stripped from container details before
  anything else sees them, and never stored or logged.
- **Deploying goes through a small host helper** (`agent/`), the only part that runs as
  root. It accepts a fixed list of actions, validates every argument, runs git and Docker
  as your normal user, never overwrites an nginx site it didn't create, and runs in a
  systemd sandbox where SSH config, SSH keys and systemd itself are out of reach.
- **It never touches SSH or the firewall.**

Details and the threat model are in [docs/PLAN.md](docs/PLAN.md). To report a
vulnerability, see [SECURITY.md](SECURITY.md).

## Running it on a server

Requires Docker with the Compose plugin (Docker 28 or later).

```bash
git clone https://github.com/mroue-Ali/webos.git && cd webos
cp .env.example .env        # then set WEBOS_SECRET_KEY, and WEBOS_UID/GID to your user
mkdir data                  # must be owned by WEBOS_UID
docker compose up -d --build
docker compose exec webos webos-admin create-user --username you
```

`create-user` asks for a password. Sign in with username and password.

Then, from your own machine:

```bash
ssh -L 9000:127.0.0.1:9000 you@your-server
```

and open <http://localhost:9000>.

| Command (inside the container) | What it does |
|---|---|
| `webos-admin create-user --username NAME` | Create the one user (only works once) |
| `webos-admin reset-password` | New password; ends every session |
| `webos-admin enable-totp` | Optional 2FA: also ask for a 6-digit code from a phone app (scan the QR it prints) |
| `webos-admin disable-totp` | Back to username + password only |
| `webos-admin migrate` | Apply database migrations (`serve` does this too) |

### Public address (optional)

To open it at `https://webos.your-domain` instead of through a tunnel, put it behind the
host's nginx with [deploy/nginx-site.conf](deploy/nginx-site.conf). That file also
rate-limits the login. In `.env`, add the address to `WEBOS_ALLOWED_ORIGINS` and set
`WEBOS_FORWARDED_ALLOW_IPS=172.16.0.0/12`, then run `docker compose up -d`. Then:

```bash
sed 's/webos.example.com/webos.your-domain/' deploy/nginx-site.conf | sudo tee /etc/nginx/sites-available/webos.your-domain
sudo ln -s /etc/nginx/sites-available/webos.your-domain /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d webos.your-domain
```

A public login page gets found and probed, so turn on 2FA (`webos-admin enable-totp`)
if you go this way.

### Deploying sites (the host helper)

The new-site wizard needs `webos-agent`, a small root service, installed once (it needs
python3, git, nginx and certbot on the host, which the platform pattern already has):

```bash
sudo sh agent/install.sh
```

It prints a `WEBOS_AGENT_GID=...` line: add it to `.env`, optionally with
`WEBOS_BASE_DOMAIN=your-domain` (the wizard then suggests `<name>.your-domain`), and run
`docker compose up -d`. Sites are cloned into `~/apps/<name>`. To update the helper later,
run the install command again after `git pull`.

**Back up `data/webos.db`.** It holds projects and the audit log. Live state is always
read from Docker, so losing it loses no server state.

## Configuration

All settings are environment variables, set in `.env` (see [.env.example](.env.example)).

| Variable | Default | |
|---|---|---|
| `WEBOS_SECRET_KEY` | — (required) | Signs sessions, encrypts the 2FA secret. 32+ characters. |
| `WEBOS_ALLOWED_ORIGINS` | `http://localhost:9000` | Exact origin(s) you open the panel at, comma-separated. |
| `WEBOS_UID` / `WEBOS_GID` | `1001` | Host user the container runs as. |
| `WEBOS_PORT` | `9000` | Loopback port. |
| `WEBOS_SESSION_IDLE_MINUTES` | `30` | Sign out after this long without activity. |
| `WEBOS_SESSION_MAX_HOURS` | `12` | Sign out after this long regardless. |
| `WEBOS_COOKIE_SECURE` | `true` | Only set to `false` for a plain-HTTP address other than localhost. |
| `WEBOS_FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxies trusted for `X-Forwarded-For`. |

## Development

Backend: Python 3.11+, FastAPI, SQLAlchemy + Alembic, SQLite, managed with
[uv](https://docs.astral.sh/uv/). Frontend: React, TypeScript and Vite.

```bash
# 1. The Docker socket proxy, exposed on 127.0.0.1:2375 for the dev backend
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d socket-proxy

# 2. Backend on :8000. backend/.env needs:
#      WEBOS_SECRET_KEY=<any 32+ chars>
#      WEBOS_DOCKER_URL=http://127.0.0.1:2375
#      WEBOS_ALLOWED_ORIGINS=http://localhost:5173
cd backend
uv sync
uv run webos-admin create-user --username dev
uv run uvicorn webos.main:create_app --factory --reload --port 8000

# 3. Frontend on :5173 (proxies /api to :8000)
cd frontend
npm install
npm run dev
```

Checks (CI runs the same):

```bash
cd backend  && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
cd frontend && npm run lint && npm test && npm run build
```

## Licence

[MIT](LICENSE)
