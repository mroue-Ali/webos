#!/usr/bin/env python3
"""webos-agent: the one part of webos that runs as root on the host.

The panel runs in an unprivileged container. A few steps of deploying a site need the
host itself: cloning into the apps folder, running `docker compose` there, writing an nginx
site and getting a certificate. This agent does exactly those steps and nothing else.

- It listens on a Unix socket that only the `webos-agent` group (the panel) can open.
- It accepts a fixed list of verbs (VERBS below) and validates every argument.
- It runs commands as argument lists, never through a shell, and runs git and docker as
  the apps user, not root.
- It never touches SSH, the firewall or systemd. Its systemd unit makes /etc/ssh, ~/.ssh
  and systemd's control sockets inaccessible to it; nginx is reloaded with a signal.
- It never overwrites an nginx site it didn't create.

Protocol: one JSON request per connection, {"verb": "...", "args": {...}}, answered by JSON
lines: {"log": "..."} while working, then {"ok": true, "result": ...} or
{"ok": false, "error": "..."}.

Standard library only, so it runs on the host's own python3 with nothing installed.
"""

from __future__ import annotations

import argparse
import configparser
import contextlib
import json
import logging
import os
import re
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

VERSION = "1"
CONFIG_PATH = Path("/etc/webos-agent.conf")
SOCKET_PATH = Path("/run/webos-agent/agent.sock")
OVERRIDE_FILE = "docker-compose.webos.yml"
SITE_MARKER = "# managed by webos: regenerated on changes, edit through the panel"
MAX_TEXT = 64 * 1024

NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
DOMAIN = re.compile(r"(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")
BRANCH = re.compile(r"[A-Za-z0-9._][A-Za-z0-9._/-]{0,99}")
REPO = re.compile(
    r"https://[A-Za-z0-9.-]+(:[0-9]+)?/[A-Za-z0-9._~/-]+"
    r"|git@[A-Za-z0-9.-]+:[A-Za-z0-9._~/-]+"
)
MISSING_ENV = re.compile(r"env file (\S+) not found")
REL_PATH = re.compile(r"[A-Za-z0-9._-][A-Za-z0-9._/-]{0,199}")
COMPOSE_NAMES = {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}
SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Run as the apps user by Host.write_file: an atomic write (temp file in the same folder,
# then rename) with the requested mode. Content arrives on stdin.
USER_WRITE = """
import os, sys, tempfile
path, mode = sys.argv[1], int(sys.argv[2], 8)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".webos-")
with os.fdopen(fd, "w", encoding="utf-8", newline="\\n") as handle:
    handle.write(sys.stdin.read())
os.chmod(tmp, mode)
os.replace(tmp, path)
"""

log = logging.getLogger("webos-agent")
Emit = Callable[[str], None]


class AgentError(Exception):
    """A refusal or failure explained to the panel."""


def is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


@dataclass(frozen=True)
class Config:
    apps_root: Path
    user: str
    socket_path: Path = SOCKET_PATH
    socket_group: str = "webos-agent"
    nginx_available: Path = Path("/etc/nginx/sites-available")
    nginx_enabled: Path = Path("/etc/nginx/sites-enabled")
    nginx_conf_d: Path = Path("/etc/nginx/conf.d")
    certbot_email: str = ""
    # Test-only switches (the integration test runs on a laptop without a public domain).
    fake_certbot: bool = False
    allow_file_repos: bool = False

    @property
    def keys_dir(self) -> Path:
        return self.apps_root / ".webos" / "keys"


def load_config(path: Path = CONFIG_PATH) -> Config:
    parser = configparser.ConfigParser()
    if not parser.read(path):
        raise SystemExit(f"missing {path}; run agent/install.sh")
    section = parser["agent"]
    config = Config(apps_root=Path(section["apps_root"]), user=section["user"])
    return replace(
        config,
        socket_path=Path(section.get("socket_path", str(config.socket_path))),
        socket_group=section.get("socket_group", config.socket_group),
        certbot_email=section.get("certbot_email", ""),
        fake_certbot=section.getboolean("fake_certbot", fallback=False),
        allow_file_repos=section.getboolean("allow_file_repos", fallback=False),
    )


# --- validation ------------------------------------------------------------------------


def text_arg(args: dict[str, Any], key: str, pattern: re.Pattern[str] | None = None) -> str:
    value = args.get(key)
    if not isinstance(value, str) or (pattern is not None and not pattern.fullmatch(value)):
        raise AgentError(f"invalid {key}")
    return value


def port_arg(args: dict[str, Any], key: str = "port") -> int:
    value = args.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or not 1024 <= value <= 65535:
        raise AgentError(f"invalid {key}")
    return value


def repo_arg(args: dict[str, Any], config: Config) -> str:
    repo = args.get("repo")
    if isinstance(repo, str) and config.allow_file_repos and repo.startswith("file:///"):
        return repo
    return text_arg(args, "repo", REPO)


def domains_arg(args: dict[str, Any]) -> list[str]:
    domain = text_arg(args, "domain", DOMAIN)
    aliases = args.get("aliases") or []
    if not isinstance(aliases, list) or len(aliases) > 5:
        raise AgentError("invalid aliases")
    for alias in aliases:
        if not isinstance(alias, str) or not DOMAIN.fullmatch(alias):
            raise AgentError("invalid aliases")
    return [domain, *aliases]


def inside(base: Path, rel: str) -> Path:
    """`base/rel`, refusing anything that resolves outside `base` (.., absolute, symlinks)."""
    if not REL_PATH.fullmatch(rel) or ".." in rel.split("/"):
        raise AgentError("invalid path")
    path = (base / rel).resolve()
    if not path.is_relative_to(base.resolve()):
        raise AgentError("path leaves the project folder")
    return path


# --- running commands --------------------------------------------------------------------


class Host:
    """Everything that touches the system, so tests can swap it out."""

    def __init__(self, config: Config) -> None:
        self.config = config

    def user_ids(self) -> tuple[int, int, list[int], str]:
        import pwd

        entry = pwd.getpwnam(self.config.user)
        groups = os.getgrouplist(self.config.user, entry.pw_gid)
        return entry.pw_uid, entry.pw_gid, groups, entry.pw_dir

    def run(
        self,
        cmd: list[str],
        *,
        emit: Emit | None = None,
        cwd: Path | None = None,
        as_user: bool = True,
        env: dict[str, str] | None = None,
        timeout: float = 600,
        check: bool = True,
    ) -> tuple[int, str]:
        """Run without a shell; stream lines to `emit`; return (exit code, output)."""
        full_env = {"PATH": SAFE_PATH, "LANG": "C.UTF-8", "GIT_TERMINAL_PROMPT": "0"}
        full_env, kwargs = self._environment(as_user, env)

        proc = subprocess.Popen(  # noqa: S603 - argument list, never a shell
            cmd,
            cwd=cwd,
            env=full_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            **kwargs,
        )
        lines: list[str] = []
        deadline = time.monotonic() + timeout
        if proc.stdout is None:
            raise AgentError(f"couldn't read output of {cmd[0]}")
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            lines.append(line)
            if emit:
                emit(line)
            if time.monotonic() > deadline:
                proc.kill()
                raise AgentError(f"{cmd[0]} took longer than {int(timeout)}s")
        code = proc.wait()
        output = "\n".join(lines)
        if check and code != 0:
            tail = "\n".join(lines[-15:])
            raise AgentError(f"{' '.join(cmd[:3])} failed (exit {code}):\n{tail}")
        return code, output

    def capture(
        self, cmd: list[str], *, cwd: Path | None = None, timeout: float = 60
    ) -> tuple[int, str, str]:
        """Run as the apps user and return (exit code, stdout, stderr) separately."""
        env, kwargs = self._environment(True, None)
        done = subprocess.run(  # noqa: S603 - argument list, never a shell
            cmd,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
            **kwargs,
        )
        return done.returncode, done.stdout, done.stderr

    def _environment(
        self, as_user: bool, extra: dict[str, str] | None
    ) -> tuple[dict[str, str], dict[str, Any]]:
        env = {"PATH": SAFE_PATH, "LANG": "C.UTF-8", "GIT_TERMINAL_PROMPT": "0"}
        kwargs: dict[str, Any] = {}
        if as_user and is_root():
            uid, gid, groups, home = self.user_ids()
            kwargs = {"user": uid, "group": gid, "extra_groups": groups}
            env["HOME"] = home
        else:
            env["HOME"] = os.environ.get("HOME", "/root")
        env.update(extra or {})
        return env, kwargs

    def write_file(self, path: Path, content: str, *, mode: int, owner_user: bool) -> None:
        """Write atomically (temp file + rename).

        Files that belong to the apps user are written *as* that user, never by root: a
        root write into a folder the user controls could be redirected with a symlink.
        Root writes only into root-owned places (/etc/nginx).
        """
        if owner_user and is_root():
            env, kwargs = self._environment(True, None)
            subprocess.run(  # noqa: S603 - argument list, never a shell
                [sys.executable, "-c", USER_WRITE, str(path), oct(mode)],
                input=content,
                text=True,
                env=env,
                check=True,
                timeout=30,
                **kwargs,
            )
            return
        tmp = path.with_name(f".{path.name}.webos-tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.chmod(tmp, mode)
        os.replace(tmp, path)

    def make_user_dir(self, path: Path, mode: int) -> None:
        """Create a folder owned by the apps user, as that user (see write_file)."""
        if is_root():
            self.run(["install", "-d", "-m", oct(mode)[2:], str(path)], timeout=30)
            return
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, mode)


# --- pure helpers (unit-tested) --------------------------------------------------------------


def parse_listening_ports(ss_output: str) -> list[int]:
    """Ports from `ss -Htln`: 'LISTEN 0 511 127.0.0.1:8000 0.0.0.0:*' -> 8000."""
    ports = set()
    for line in ss_output.splitlines():
        fields = line.split()
        if len(fields) >= 4:
            port = fields[3].rsplit(":", 1)[-1]
            if port.isdigit():
                ports.add(int(port))
    return sorted(ports)


def policy_violations(config: dict[str, Any], project_dir: Path) -> list[str]:
    """What webos refuses to run, read from `docker compose config --format json`."""
    problems = []
    root = project_dir.resolve()
    for name, service in sorted((config.get("services") or {}).items()):
        for port in service.get("ports") or []:
            published = port.get("published") if isinstance(port, dict) else None
            host_ip = (port.get("host_ip") or "") if isinstance(port, dict) else ""
            if published and host_ip not in ("127.0.0.1", "::1"):
                problems.append(
                    f"{name}: port {published} would be open to the internet (Docker bypasses "
                    f"ufw). Publish it on 127.0.0.1 or not at all."
                )
        if service.get("privileged"):
            problems.append(f"{name}: privileged containers are not allowed")
        for key in ("network_mode", "pid", "ipc", "userns_mode", "uts"):
            if service.get(key) == "host":
                problems.append(f"{name}: {key}: host is not allowed")
        if service.get("cap_add"):
            problems.append(f"{name}: extra capabilities (cap_add) are not allowed")
        if service.get("devices"):
            problems.append(f"{name}: host devices are not allowed")
        for option in service.get("security_opt") or []:
            if "unconfined" in str(option):
                problems.append(f"{name}: security_opt {option} is not allowed")
        for volume in service.get("volumes") or []:
            if not isinstance(volume, dict) or volume.get("type") != "bind":
                continue
            source = str(volume.get("source", ""))
            if source.endswith("docker.sock"):
                problems.append(f"{name}: mounting the Docker socket is not allowed")
            elif not Path(source).resolve().is_relative_to(root):
                problems.append(f"{name}: mounts {source}, outside the project folder")
    return problems


def summarize_config(config: dict[str, Any]) -> dict[str, Any]:
    """The parts of a compose config the panel needs. Environment values never leave."""
    services = {}
    for name, service in sorted((config.get("services") or {}).items()):
        services[name] = {
            "image": service.get("image"),
            "build": "build" in service,
            "command": service.get("command"),
            "ports": [
                {
                    "target": p.get("target"),
                    "published": p.get("published"),
                    "host_ip": p.get("host_ip"),
                }
                for p in service.get("ports") or []
                if isinstance(p, dict)
            ],
            "volumes": [
                {"type": v.get("type"), "source": v.get("source"), "target": v.get("target")}
                for v in service.get("volumes") or []
                if isinstance(v, dict)
            ],
            "expose": service.get("expose") or [],
            "healthcheck": bool(service.get("healthcheck")),
        }
    return {"services": services}


def render_site(names: list[str], port: int, project: str, max_body_mb: int) -> str:
    return f"""{SITE_MARKER}
# Project {project}: proxies to 127.0.0.1:{port}. certbot adds the HTTPS parts below.
server {{
    listen 80;
    listen [::]:80;
    server_name {" ".join(names)};

    client_max_body_size {max_body_mb}m;

    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $webos_connection_upgrade;
        proxy_read_timeout 300s;
    }}
}}
"""


UPGRADE_MAP = f"""{SITE_MARKER}
# WebSocket support for webos-managed sites.
map $http_upgrade $webos_connection_upgrade {{
    default upgrade;
    ''      close;
}}
"""


def sites_serving(enabled_dir: Path, name: str, skip: Path | None = None) -> list[str]:
    """Enabled nginx sites that already list `name` in a server_name."""
    pattern = re.compile(r"server_name\s[^;]*(?<![\w.-])" + re.escape(name) + r"(?![\w.-])")
    found = []
    for entry in sorted(enabled_dir.iterdir()) if enabled_dir.is_dir() else []:
        target = entry.resolve()
        if skip is not None and target == skip.resolve():
            continue
        try:
            if pattern.search(target.read_text(errors="replace")):
                found.append(entry.name)
        except OSError:
            continue
    return found


# --- verbs -------------------------------------------------------------------------------------


class Agent:
    def __init__(self, config: Config, host: Host | None = None) -> None:
        self.config = config
        self.host = host or Host(config)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def lock(self, key: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    def project_dir(self, args: dict[str, Any], *, must_exist: bool = True) -> tuple[str, Path]:
        name = text_arg(args, "name", NAME)
        path = self.config.apps_root / name
        if must_exist and not (path / ".git").is_dir():
            raise AgentError(f"project {name} has not been cloned")
        return name, path

    def compose_location(self, args: dict[str, Any]) -> tuple[str, Path, Path]:
        name, project = self.project_dir(args)
        compose = inside(project, text_arg(args, "compose_file"))
        if compose.name not in COMPOSE_NAMES and not compose.name.startswith("docker-compose."):
            raise AgentError("compose_file must be a compose file")
        if not compose.is_file():
            raise AgentError(f"{args['compose_file']} not found in the repository")
        return name, project, compose

    def compose_cmd(self, name: str, compose: Path, *extra: str) -> list[str]:
        files = ["-f", compose.name]
        if (compose.parent / OVERRIDE_FILE).is_file():
            files += ["-f", OVERRIDE_FILE]
        return ["docker", "compose", "-p", name, *files, *extra]

    def git_ssh_command(self, name: str) -> str:
        keys = self.config.keys_dir
        return (
            f"ssh -F /dev/null -i {keys / (name + '_ed25519')} -o IdentitiesOnly=yes "
            f"-o UserKnownHostsFile={keys / 'known_hosts'} -o StrictHostKeyChecking=yes "
            f"-o BatchMode=yes"
        )

    # Each verb takes (args, emit) and returns a JSON-able result.

    def v_ping(self, args: dict[str, Any], emit: Emit) -> dict[str, Any]:
        _, compose_version = self.host.run(
            ["docker", "compose", "version", "--short"], check=False, timeout=30
        )
        return {
            "version": VERSION,
            "apps_root": str(self.config.apps_root),
            "user": self.config.user,
            "host_ips": self.host_ips(),
            "compose_version": compose_version.strip(),
            "nginx": shutil.which("nginx", path=SAFE_PATH) is not None,
            "certbot": self.config.fake_certbot
            or shutil.which("certbot", path=SAFE_PATH) is not None,
        }

    def host_ips(self) -> list[str]:
        code, output = self.host.run(
            ["ip", "-j", "addr", "show", "scope", "global"], as_user=False, check=False, timeout=10
        )
        if code != 0:
            return []
        ips = []
        for link in json.loads(output or "[]"):
            for addr in link.get("addr_info", []):
                if addr.get("local") and not str(link.get("ifname", "")).startswith(
                    ("docker", "br-", "veth")
                ):
                    ips.append(addr["local"])
        return ips

    def v_ports(self, args: dict[str, Any], emit: Emit) -> dict[str, Any]:
        _, output = self.host.run(["ss", "-Htln"], as_user=False, timeout=10)
        return {"listening": parse_listening_ports(output)}

    def v_deploy_key(self, args: dict[str, Any], emit: Emit) -> dict[str, Any]:
        """A per-project read-only key, to add as a Deploy key on the repository."""
        name = text_arg(args, "name", NAME)
        keys = self.config.keys_dir
        self.host.make_user_dir(keys.parent, 0o700)
        self.host.make_user_dir(keys, 0o700)
        key = keys / f"{name}_ed25519"
        if not key.exists():
            comment = f"webos-{name}@{socket.gethostname()}"
            self.host.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", comment, "-f", str(key)]
            )
        return {"public_key": Path(f"{key}.pub").read_text().strip()}

    def ensure_known_host(self, repo: str, emit: Emit) -> None:
        """Pin github.com's SSH keys from GitHub's API (over TLS) instead of trusting blindly."""
        if not repo.startswith("git@github.com:"):
            if repo.startswith("git@"):
                raise AgentError("SSH clone is supported for github.com; use an https URL")
            return
        known = self.config.keys_dir / "known_hosts"
        if known.exists() and "github.com " in known.read_text():
            return
        emit("Fetching GitHub's SSH host keys from api.github.com/meta")
        with urllib.request.urlopen("https://api.github.com/meta", timeout=20) as response:
            keys = json.load(response).get("ssh_keys") or []
        if not keys:
            raise AgentError("couldn't get GitHub's SSH host keys")
        self.host.make_user_dir(self.config.keys_dir, 0o700)
        lines = "".join(f"github.com {k}\n" for k in keys)
        self.host.write_file(known, lines, mode=0o644, owner_user=True)

    def v_clone(self, args: dict[str, Any], emit: Emit) -> dict[str, Any]:
        name, target = self.project_dir(args, must_exist=False)
        repo = repo_arg(args, self.config)
        branch = text_arg(args, "branch", BRANCH)
        if target.exists():
            raise AgentError(f"{target} already exists")
        env = {}
        if repo.startswith("git@"):
            if not (self.config.keys_dir / f"{name}_ed25519").exists():
                raise AgentError("no deploy key for this project yet")
            self.ensure_known_host(repo, emit)
            env["GIT_SSH_COMMAND"] = self.git_ssh_command(name)
        self.host.make_user_dir(self.config.apps_root, 0o755)
        emit(f"Cloning {repo} ({branch}) into {target}")
        self.host.run(
            [
                "git",
                "clone",
                "--progress",
                "--branch",
                branch,
                "--single-branch",
                "--",
                repo,
                str(target),
            ],
            emit=emit,
            env=env,
            timeout=900,
        )
        if repo.startswith("git@"):
            self.host.run(
                ["git", "-C", str(target), "config", "core.sshCommand", env["GIT_SSH_COMMAND"]]
            )
        exclude = target / ".git" / "info" / "exclude"
        exclude.parent.mkdir(exist_ok=True)
        existing = exclude.read_text() if exclude.exists() else ""
        self.host.write_file(exclude, f"{existing}\n{OVERRIDE_FILE}\n", mode=0o644, owner_user=True)
        self.host.write_file(
            target / ".git" / "webos-project", name + "\n", mode=0o644, owner_user=True
        )
        return self.head(target)

    def head(self, project: Path) -> dict[str, str]:
        _, out = self.host.run(
            ["git", "-C", str(project), "log", "-1", "--format=%H%x1f%s%x1f%an%x1f%cI"]
        )
        sha, subject, author, date = [*out.strip().split("\x1f"), "", "", "", ""][:4]
        return {"commit": sha, "subject": subject, "author": author, "date": date}

    def v_head(self, args: dict[str, Any], emit: Emit) -> dict[str, Any]:
        _, project = self.project_dir(args)
        return self.head(project)

    def v_pull(self, args: dict[str, Any], emit: Emit) -> dict[str, Any]:
        """Make the working tree match the remote branch exactly (.env and the override stay)."""
        _, project = self.project_dir(args)
        branch = text_arg(args, "branch", BRANCH)
        emit(f"Fetching {branch}")
        self.host.run(
            ["git", "-C", str(project), "fetch", "--progress", "origin", f"refs/heads/{branch}"],
            emit=emit,
            timeout=600,
        )
        self.host.run(["git", "-C", str(project), "reset", "--hard", "FETCH_HEAD"], emit=emit)
        return self.head(project)

    def v_remote_head(self, args: dict[str, Any], emit: Emit) -> dict[str, Any]:
        _, project = self.project_dir(args)
        branch = text_arg(args, "branch", BRANCH)
        _, out = self.host.run(
            ["git", "-C", str(project), "ls-remote", "origin", f"refs/heads/{branch}"], timeout=60
        )
        sha = out.split()[0] if out.split() else ""
        return {"commit": sha}

    def v_find_compose(self, args: dict[str, Any], emit: Emit) -> dict[str, Any]:
        _, project = self.project_dir(args)
        found = []
        skip = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}
        for root, dirs, files in os.walk(project):
            depth = len(Path(root).relative_to(project).parts)
            dirs[:] = [] if depth >= 3 else sorted(d for d in dirs if d not in skip)
            for file in files:
                is_compose = file in COMPOSE_NAMES or (
                    file.startswith("docker-compose.")
                    and file.endswith((".yml", ".yaml"))
                    and file != OVERRIDE_FILE
                )
                if is_compose:
                    found.append((Path(root) / file).relative_to(project).as_posix())
        return {"files": sorted(found, key=lambda f: (f.count("/"), f))}

    def v_compose_config(self, args: dict[str, Any], emit: Emit) -> dict[str, Any]:
        """Optionally write the override, then return the merged config and policy problems."""
        name, project, compose = self.compose_location(args)
        override = args.get("override")
        if override is not None:
            if not isinstance(override, str) or len(override) > MAX_TEXT or "\x00" in override:
                raise AgentError("invalid override")
            target = compose.parent / OVERRIDE_FILE
            if override.strip():
                self.host.write_file(target, override, mode=0o644, owner_user=True)
            elif target.exists():
                target.unlink()
        config = self.merged_config(name, compose)
        return {
            **summarize_config(config),
            "violations": policy_violations(config, project),
            "has_env_example": (compose.parent / ".env.example").is_file(),
        }

    def merged_config(self, name: str, compose: Path) -> dict[str, Any]:
        project = self.config.apps_root / name
        for _attempt in range(3):
            code, out, err = self.host.capture(
                self.compose_cmd(name, compose, "config", "--format", "json"), cwd=compose.parent
            )
            missing = MISSING_ENV.search(err)
            if code != 0 and missing:
                # A compose file that names `env_file: .env` can't even be read before the
                # .env exists. Create it empty (owner-only); the wizard fills it in.
                env_file = Path(missing.group(1))
                if not env_file.resolve().is_relative_to(project.resolve()):
                    raise AgentError(f"env file {env_file} is outside the project folder")
                self.host.write_file(env_file, "", mode=0o600, owner_user=True)
                continue
            if code != 0:
                raise AgentError("docker compose can't read this compose file:\n" + err[-1500:])
            try:
                return dict(json.loads(out))
            except ValueError as exc:
                raise AgentError("docker compose config returned something unreadable") from exc
        raise AgentError("docker compose config kept failing")

    def env_path(self, args: dict[str, Any]) -> Path:
        _, project, compose = self.compose_location(args)
        rel_compose_dir = compose.parent.relative_to(project.resolve()).as_posix()
        env_rel = text_arg(args, "env_file")
        joined = env_rel if rel_compose_dir == "." else f"{rel_compose_dir}/{env_rel}"
        return inside(project, joined)

    def v_env_example(self, args: dict[str, Any], emit: Emit) -> dict[str, Any]:
        _, _, compose = self.compose_location(args)
        example = compose.parent / ".env.example"
        text = example.read_text(errors="replace")[:MAX_TEXT] if example.is_file() else ""
        return {"content": text}

    def v_read_env(self, args: dict[str, Any], emit: Emit) -> dict[str, Any]:
        path = self.env_path(args)
        return {
            "content": path.read_text(errors="replace") if path.is_file() else "",
            "exists": path.is_file(),
        }

    def v_write_env(self, args: dict[str, Any], emit: Emit) -> dict[str, Any]:
        path = self.env_path(args)
        content = args.get("content")
        if not isinstance(content, str) or len(content) > MAX_TEXT or "\x00" in content:
            raise AgentError("invalid content")
        self.host.write_file(
            path,
            content if content.endswith("\n") or not content else content + "\n",
            mode=0o600,
            owner_user=True,
        )
        return {"written": True}

    def v_up(self, args: dict[str, Any], emit: Emit) -> dict[str, Any]:
        name, project, compose = self.compose_location(args)
        config = self.merged_config(name, compose)
        problems = policy_violations(config, project)
        if problems:
            raise AgentError("refused by the safety check:\n" + "\n".join(problems))
        emit("Building and starting containers")
        self.host.run(
            self.compose_cmd(name, compose, "up", "-d", "--build", "--remove-orphans"),
            emit=emit,
            cwd=compose.parent,
            timeout=1800,
            env={
                "COMPOSE_ANSI": "never",
                "COMPOSE_PROGRESS": "plain",
                "BUILDKIT_PROGRESS": "plain",
            },
        )
        return {"started": True}

    def v_down(self, args: dict[str, Any], emit: Emit) -> dict[str, Any]:
        name, _, compose = self.compose_location(args)
        extra = ["down", "--remove-orphans"] + (
            ["--volumes"] if args.get("volumes") is True else []
        )
        self.host.run(
            self.compose_cmd(name, compose, *extra),
            emit=emit,
            cwd=compose.parent,
            timeout=300,
            env={"COMPOSE_ANSI": "never", "COMPOSE_PROGRESS": "plain"},
        )
        return {"stopped": True}

    def v_http_check(self, args: dict[str, Any], emit: Emit) -> dict[str, Any]:
        """Wait until something answers HTTP on 127.0.0.1:port (any status counts)."""
        port = port_arg(args)
        wait = min(int(args.get("timeout") or 90), 300)
        deadline = time.monotonic() + wait
        last = ""
        emit(f"Waiting for the app to answer on 127.0.0.1:{port}")
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
                    return {"status": response.status}
            except urllib.error.HTTPError as exc:
                return {"status": exc.code}
            except OSError as exc:
                last = str(exc)
                time.sleep(2)
        raise AgentError(f"nothing answered on 127.0.0.1:{port} within {wait}s ({last})")

    def v_nginx_site(self, args: dict[str, Any], emit: Emit) -> dict[str, Any]:
        names = domains_arg(args)
        port = port_arg(args)
        project = text_arg(args, "name", NAME)
        max_body = args.get("max_body_mb", 25)
        if not isinstance(max_body, int) or not 1 <= max_body <= 1024:
            raise AgentError("invalid max_body_mb")
        domain = names[0]
        site = self.config.nginx_available / domain
        previous = site.read_text() if site.exists() else None
        if previous is not None and SITE_MARKER not in previous:
            raise AgentError(f"{site} exists and wasn't created by webos; webos won't touch it")
        if previous is not None and not args.get("replace"):
            emit(f"{site} already exists; keeping it (its HTTPS settings included)")
            return {"site": str(site), "changed": False}
        for name in names:
            if others := sites_serving(self.config.nginx_enabled, name, skip=site):
                raise AgentError(f"{name} is already served by nginx site {', '.join(others)}")

        upgrade_map = self.config.nginx_conf_d / "webos.conf"
        if not upgrade_map.exists():
            self.host.write_file(upgrade_map, UPGRADE_MAP, mode=0o644, owner_user=False)
        link = self.config.nginx_enabled / domain
        emit(f"Writing {site}")
        self.host.write_file(
            site, render_site(names, port, project, max_body), mode=0o644, owner_user=False
        )
        if not link.is_symlink() and not link.exists():
            link.symlink_to(site)
        code, output = self.host.run(["nginx", "-t"], as_user=False, check=False, timeout=30)
        if code != 0:
            if previous is None:
                link.unlink(missing_ok=True)
                site.unlink(missing_ok=True)
            else:
                self.host.write_file(site, previous, mode=0o644, owner_user=False)
            raise AgentError(
                "nginx rejected the config, so nothing was changed:\n" + output[-1500:]
            )
        self.host.run(["nginx", "-s", "reload"], as_user=False, emit=emit, timeout=30)
        emit("nginx reloaded")
        return {"site": str(site), "changed": True}

    def v_nginx_remove(self, args: dict[str, Any], emit: Emit) -> dict[str, Any]:
        domain = text_arg(args, "domain", DOMAIN)
        site = self.config.nginx_available / domain
        if not site.exists():
            return {"removed": False}
        if SITE_MARKER not in site.read_text():
            raise AgentError(f"{site} wasn't created by webos; webos won't remove it")
        (self.config.nginx_enabled / domain).unlink(missing_ok=True)
        site.unlink()
        self.host.run(["nginx", "-t"], as_user=False, timeout=30)
        self.host.run(["nginx", "-s", "reload"], as_user=False, emit=emit, timeout=30)
        return {"removed": True}

    def v_certbot(self, args: dict[str, Any], emit: Emit) -> dict[str, Any]:
        names = domains_arg(args)
        if self.config.fake_certbot:
            emit(f"(test mode) skipping certbot for {', '.join(names)}")
            return {"issued": False, "fake": True}
        cmd = [
            "certbot",
            "--nginx",
            "--non-interactive",
            "--agree-tos",
            "--redirect",
            "--keep-until-expiring",
            "--cert-name",
            names[0],
        ]
        cmd += (
            ["-m", self.config.certbot_email]
            if self.config.certbot_email
            else ["--register-unsafely-without-email"]
        )
        for name in names:
            cmd += ["-d", name]
        emit(f"Requesting a certificate for {', '.join(names)}")
        self.host.run(cmd, as_user=False, emit=emit, timeout=300)
        return {"issued": True}

    def v_cert_delete(self, args: dict[str, Any], emit: Emit) -> dict[str, Any]:
        domain = text_arg(args, "domain", DOMAIN)
        if self.config.fake_certbot:
            return {"deleted": False, "fake": True}
        code, _ = self.host.run(
            ["certbot", "delete", "--non-interactive", "--cert-name", domain],
            as_user=False,
            emit=emit,
            check=False,
            timeout=120,
        )
        return {"deleted": code == 0}

    def v_discard(self, args: dict[str, Any], emit: Emit) -> dict[str, Any]:
        """Delete a project folder webos cloned. Refused while any of its containers exist."""
        name, project = self.project_dir(args)
        marker = project / ".git" / "webos-project"
        if not marker.is_file() or marker.read_text().strip() != name:
            raise AgentError(f"{project} wasn't cloned by webos; webos won't delete it")
        _, running = self.host.run(
            ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={name}"],
            timeout=30,
        )
        if running.strip():
            raise AgentError("its containers still exist; remove the site's containers first")
        shutil.rmtree(project)
        key = self.config.keys_dir / f"{name}_ed25519"
        for path in (key, Path(f"{key}.pub")):
            path.unlink(missing_ok=True)
        return {"deleted": str(project)}


VERBS: dict[str, Callable[[Agent, dict[str, Any], Emit], dict[str, Any]]] = {
    name[2:]: getattr(Agent, name) for name in dir(Agent) if name.startswith("v_")
}


def handle_request(agent: Agent, line: bytes, write: Callable[[dict[str, Any]], None]) -> None:
    """Run one request, streaming {"log"} lines and ending with {"ok": ...}."""
    alive = True

    def emit(message: str) -> None:
        nonlocal alive
        if alive:
            try:
                write({"log": message})
            except OSError:
                alive = False  # the panel went away; finish the job anyway

    try:
        request = json.loads(line)
        verb = request.get("verb")
        args = request.get("args") or {}
        if verb not in VERBS or not isinstance(args, dict):
            raise AgentError(f"unknown verb {verb!r}")
        project = args.get("name") if isinstance(args.get("name"), str) else "-"
        log.info("verb=%s project=%s", verb, project)
        with agent.lock(project if verb not in {"ping", "ports"} else f"_{verb}"):
            result = VERBS[verb](agent, args, emit)
        response: dict[str, Any] = {"ok": True, "result": result}
    except AgentError as exc:
        log.warning("refused: %s", str(exc).splitlines()[0])
        response = {"ok": False, "error": str(exc)}
    except (ValueError, KeyError, TypeError) as exc:
        response = {"ok": False, "error": f"bad request: {exc}"}
    except Exception:
        log.exception("verb failed")
        response = {"ok": False, "error": "internal error; see `journalctl -u webos-agent`"}
    with contextlib.suppress(OSError):
        write(response)


class Handler(socketserver.StreamRequestHandler):
    agent: Agent

    def handle(self) -> None:
        def write(obj: dict[str, Any]) -> None:
            self.wfile.write((json.dumps(obj) + "\n").encode())
            self.wfile.flush()

        handle_request(self.agent, self.rfile.readline(1_000_000), write)


def serve(config: Config) -> None:
    import grp

    # Defined here because Unix sockets don't exist on Windows, where the tests also run.
    class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
        daemon_threads = True

    path = config.socket_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    Handler.agent = Agent(config)
    server = Server(str(path), Handler)
    os.chown(path, 0, grp.getgrnam(config.socket_group).gr_gid)
    os.chmod(path, 0o660)
    log.info(
        "webos-agent %s listening on %s (apps in %s, as %s)",
        VERSION,
        path,
        config.apps_root,
        config.user,
    )
    server.serve_forever()


def call(socket_path: Path, verb: str, args: dict[str, Any]) -> int:
    """Debug client: `webos_agent.py call ping '{}'`."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(str(socket_path))
        sock.sendall((json.dumps({"verb": verb, "args": args}) + "\n").encode())
        for raw in sock.makefile("r"):
            message = json.loads(raw)
            if "log" in message:
                print(message["log"])
            else:
                print(json.dumps(message, indent=2))
                return 0 if message.get("ok") else 1
    return 1


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)
    parser = argparse.ArgumentParser(description="webos host agent")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve")
    caller = sub.add_parser("call")
    caller.add_argument("verb")
    caller.add_argument("args", nargs="?", default="{}")
    options = parser.parse_args()
    config = load_config(options.config)
    if options.command == "serve":
        serve(config)
        return 0
    return call(config.socket_path, options.verb, json.loads(options.args))


if __name__ == "__main__":
    sys.exit(main())
