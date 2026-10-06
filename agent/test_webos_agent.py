"""Tests for webos_agent, with the host faked so nothing real runs.

Run from backend/:  uv run pytest ../agent
"""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import webos_agent as wa


class FakeHost(wa.Host):
    """Records commands and answers them from a table instead of running anything."""

    def __init__(self, config: wa.Config, answers: dict[str, tuple[int, str]] | None = None):
        super().__init__(config)
        self.answers = answers or {}
        self.commands: list[list[str]] = []

    def _answer(self, cmd: list[str]) -> tuple[int, str]:
        self.commands.append(cmd)
        joined = " ".join(cmd)
        for prefix, answer in self.answers.items():
            if joined.startswith(prefix):
                return answer
        return 0, ""

    def run(self, cmd: list[str], *, emit: Any = None, check: bool = True, **_: Any):  # type: ignore[override]
        code, out = self._answer(cmd)
        if check and code != 0:
            raise wa.AgentError(f"{cmd[0]} failed: {out}")
        return code, out

    def capture(self, cmd: list[str], **_: Any):  # type: ignore[override]
        code, out = self._answer(cmd)
        return (0, out, "") if code == 0 else (code, "", out)

    def make_user_dir(self, path: Path, mode: int) -> None:
        path.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def setup(tmp_path: Path) -> tuple[wa.Agent, FakeHost, wa.Config]:
    config = wa.Config(
        apps_root=tmp_path / "apps",
        user="ali",
        nginx_available=tmp_path / "nginx" / "sites-available",
        nginx_enabled=tmp_path / "nginx" / "sites-enabled",
        nginx_conf_d=tmp_path / "nginx" / "conf.d",
    )
    for path in (
        config.apps_root,
        config.nginx_available,
        config.nginx_enabled,
        config.nginx_conf_d,
    ):
        path.mkdir(parents=True)
    host = FakeHost(config)
    return wa.Agent(config, host), host, config


def make_project(config: wa.Config, name: str = "shop") -> Path:
    project = config.apps_root / name
    (project / ".git" / "info").mkdir(parents=True)
    (project / "backend").mkdir()
    (project / "backend" / "docker-compose.yml").write_text("services: {}\n")
    return project


def call(agent: wa.Agent, verb: str, args: dict[str, Any]) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    wa.handle_request(agent, json.dumps({"verb": verb, "args": args}).encode(), out.append)
    return out[-1]


# --- validation ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["t30", "my-shop", "a"])
def test_names_accepted(name: str) -> None:
    assert wa.text_arg({"name": name}, "name", wa.NAME) == name


@pytest.mark.parametrize("name", ["", "-x", "Shop", "a/b", "..", "a" * 41, "x;rm"])
def test_names_refused(name: str) -> None:
    with pytest.raises(wa.AgentError):
        wa.text_arg({"name": name}, "name", wa.NAME)


@pytest.mark.parametrize(
    "repo",
    [
        "https://github.com/MhmdShd/T30-app.git",
        "git@github.com:MhmdShd/T30-app.git",
        "https://gitlab.com/group/sub/project",
    ],
)
def test_repos_accepted(repo: str, setup: Any) -> None:
    _, _, config = setup
    assert wa.repo_arg({"repo": repo}, config) == repo


@pytest.mark.parametrize(
    "repo",
    [
        "ext::sh -c touch% /tmp/x",
        "--upload-pack=touch /tmp/x",
        "file:///etc",
        "http://x.com/a",
        "https://github.com/a b",
        "git@github.com:a;b",
    ],
)
def test_repos_refused(repo: str, setup: Any) -> None:
    _, _, config = setup
    with pytest.raises(wa.AgentError):
        wa.repo_arg({"repo": repo}, config)


@pytest.mark.parametrize("branch", ["-x", "--upload-pack=x", "", "a b"])
def test_branches_refused(branch: str) -> None:
    with pytest.raises(wa.AgentError):
        wa.text_arg({"branch": branch}, "branch", wa.BRANCH)


def test_paths_stay_inside_the_project(tmp_path: Path) -> None:
    assert (
        wa.inside(tmp_path, "backend/docker-compose.yml")
        == (tmp_path / "backend" / "docker-compose.yml").resolve()
    )
    for bad in ("../x", "a/../../x", "/etc/passwd", "a//..//b", ""):
        with pytest.raises(wa.AgentError):
            wa.inside(tmp_path, bad)


def test_domains() -> None:
    assert wa.domains_arg({"domain": "t30.example.com", "aliases": ["www.t30.example.com"]}) == [
        "t30.example.com",
        "www.t30.example.com",
    ]
    for bad in ("localhost", "-a.com", "a..com", "A.com", "a.com;"):
        with pytest.raises(wa.AgentError):
            wa.domains_arg({"domain": bad})


def test_ports() -> None:
    assert wa.port_arg({"port": 8002}) == 8002
    for bad in (80, 70000, "8002", True, None):
        with pytest.raises(wa.AgentError):
            wa.port_arg({"port": bad})


# --- pure helpers ---------------------------------------------------------------------------


def test_parse_listening_ports() -> None:
    output = (
        "LISTEN 0 511 0.0.0.0:80 0.0.0.0:*\n"
        "LISTEN 0 4096 127.0.0.1:8001 0.0.0.0:*\n"
        "LISTEN 0 511 [::]:443 [::]:*\n"
        "LISTEN 0 128 127.0.0.53%lo:53 0.0.0.0:*\n"
    )
    assert wa.parse_listening_ports(output) == [53, 80, 443, 8001]


def test_policy(tmp_path: Path) -> None:
    project = tmp_path / "shop"
    project.mkdir()
    config = {
        "services": {
            "web": {
                "ports": [{"target": 80, "published": "8002", "host_ip": "127.0.0.1"}],
                "volumes": [
                    {"type": "bind", "source": str(project / "static"), "target": "/static"},
                    {"type": "volume", "source": "data", "target": "/data"},
                ],
            },
            "db": {"ports": [{"target": 5432, "published": "5433"}]},
            "bad": {
                "privileged": True,
                "network_mode": "host",
                "cap_add": ["SYS_ADMIN"],
                "devices": ["/dev/sda"],
                "security_opt": ["apparmor=unconfined"],
                "volumes": [
                    {"type": "bind", "source": "/var/run/docker.sock", "target": "/s"},
                    {"type": "bind", "source": "/etc", "target": "/host-etc"},
                ],
            },
        }
    }
    problems = wa.policy_violations(config, project)
    joined = "\n".join(problems)
    assert not any(p.startswith("web:") for p in problems)
    assert "db: port 5433 would be open to the internet" in joined
    for expected in (
        "privileged",
        "network_mode: host",
        "cap_add",
        "devices",
        "unconfined",
        "Docker socket",
        "outside the project",
    ):
        assert expected in joined


def test_summary_never_includes_environment() -> None:
    config = {
        "services": {
            "api": {"image": "x", "environment": {"SECRET": "hunter2"}, "ports": [{"target": 8000}]}
        }
    }
    summary = wa.summarize_config(config)
    assert "hunter2" not in json.dumps(summary)
    assert summary["services"]["api"]["ports"] == [
        {"target": 8000, "published": None, "host_ip": None}
    ]


def test_render_site() -> None:
    text = wa.render_site(["t30.example.com", "www.t30.example.com"], 8002, "t30", 25)
    assert text.startswith(wa.SITE_MARKER)
    assert "server_name t30.example.com www.t30.example.com;" in text
    assert "proxy_pass http://127.0.0.1:8002;" in text


def test_sites_serving_matches_whole_names(tmp_path: Path) -> None:
    (tmp_path / "main").write_text("server { server_name example.com www.example.com; }")
    assert wa.sites_serving(tmp_path, "example.com") == ["main"]
    assert wa.sites_serving(tmp_path, "t30.example.com") == []
    assert wa.sites_serving(tmp_path, "www.example.com") == ["main"]


# --- verbs through the request handler ------------------------------------------------------


def test_unknown_verb(setup: Any) -> None:
    agent, _, _ = setup
    assert call(agent, "rm_rf", {}) == {"ok": False, "error": "unknown verb 'rm_rf'"}


def test_bad_json_is_refused(setup: Any) -> None:
    agent, _, _ = setup
    out: list[dict[str, Any]] = []
    wa.handle_request(agent, b"not json", out.append)
    assert out[-1]["ok"] is False


def test_ports_verb(setup: Any) -> None:
    agent, host, _ = setup
    host.answers["ss -Htln"] = (0, "LISTEN 0 1 127.0.0.1:8001 0.0.0.0:*")
    assert call(agent, "ports", {}) == {"ok": True, "result": {"listening": [8001]}}


def test_clone_refuses_existing_folder(setup: Any) -> None:
    agent, _, config = setup
    make_project(config)
    result = call(
        agent, "clone", {"name": "shop", "repo": "https://github.com/a/b", "branch": "main"}
    )
    assert result["ok"] is False and "already exists" in result["error"]


def test_ssh_clone_needs_a_deploy_key(setup: Any) -> None:
    agent, _, _ = setup
    result = call(
        agent, "clone", {"name": "t30", "repo": "git@github.com:a/b.git", "branch": "main"}
    )
    assert result == {"ok": False, "error": "no deploy key for this project yet"}


def test_env_is_written_owner_only_inside_the_project(setup: Any) -> None:
    agent, _, config = setup
    project = make_project(config)
    args = {"name": "shop", "compose_file": "backend/docker-compose.yml", "env_file": ".env"}
    assert call(agent, "write_env", {**args, "content": "A=1"})["ok"]
    env = project / "backend" / ".env"
    assert env.read_text() == "A=1\n"
    if sys.platform != "win32":
        assert env.stat().st_mode & 0o777 == 0o600
    assert call(agent, "read_env", args)["result"] == {"content": "A=1\n", "exists": True}
    escape = call(agent, "write_env", {**args, "env_file": "../../x", "content": "A=1"})
    assert escape["ok"] is False


def test_compose_config_creates_a_missing_env_file_and_reports_policy(setup: Any) -> None:
    agent, host, config = setup
    project = make_project(config)
    env_file = project / "backend" / ".env"
    calls = {"n": 0}

    def capture(cmd: list[str], **_: Any) -> tuple[int, str, str]:
        calls["n"] += 1
        if not env_file.exists():
            return 1, "", f"env file {env_file} not found: stat: no such file or directory"
        merged = {
            "services": {
                "db": {
                    "ports": [{"target": 5432, "published": "5433"}],
                    "environment": {"POSTGRES_PASSWORD": "pw"},
                }
            }
        }
        return 0, json.dumps(merged), ""

    host.capture = capture  # type: ignore[method-assign]
    result = call(
        agent,
        "compose_config",
        {
            "name": "shop",
            "compose_file": "backend/docker-compose.yml",
            "override": "services: {}\n",
        },
    )
    assert result["ok"], result
    assert env_file.exists() and env_file.read_text() == ""
    assert (project / "backend" / wa.OVERRIDE_FILE).read_text() == "services: {}\n"
    assert len(result["result"]["violations"]) == 1
    assert "pw" not in json.dumps(result)


def test_up_refuses_policy_violations(setup: Any) -> None:
    agent, host, config = setup
    make_project(config)
    bad = {"services": {"db": {"ports": [{"target": 5432, "published": "5432"}]}}}
    host.answers["docker compose -p shop"] = (0, json.dumps(bad))
    result = call(agent, "up", {"name": "shop", "compose_file": "backend/docker-compose.yml"})
    assert result["ok"] is False and "safety check" in result["error"]
    assert not any("up" in cmd for cmd in host.commands)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_nginx_site_lifecycle(setup: Any) -> None:
    agent, host, config = setup
    args = {"name": "t30", "domain": "t30.example.com", "port": 8002}
    assert call(agent, "nginx_site", args)["ok"]
    site = config.nginx_available / "t30.example.com"
    assert wa.SITE_MARKER in site.read_text()
    assert (config.nginx_enabled / "t30.example.com").is_symlink()
    assert ["nginx", "-s", "reload"] in host.commands
    # Existing managed site: kept as is (certbot's HTTPS parts live in it).
    assert call(agent, "nginx_site", args)["result"]["changed"] is False
    assert call(agent, "nginx_remove", {"domain": "t30.example.com"})["result"] == {"removed": True}
    assert not site.exists()


def test_nginx_site_never_touches_handmade_configs(setup: Any) -> None:
    agent, _, config = setup
    (config.nginx_available / "example.com").write_text("server { server_name example.com; }")
    result = call(agent, "nginx_site", {"name": "x", "domain": "example.com", "port": 8002})
    assert result["ok"] is False and "wasn't created by webos" in result["error"]
    result = call(agent, "nginx_remove", {"domain": "example.com"})
    assert result["ok"] is False


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_nginx_site_refuses_names_served_elsewhere(setup: Any) -> None:
    agent, _, config = setup
    other = config.nginx_available / "portfolio"
    other.write_text("server { server_name example.com www.example.com; }")
    (config.nginx_enabled / "portfolio").symlink_to(other)
    result = call(agent, "nginx_site", {"name": "x", "domain": "www.example.com", "port": 8002})
    assert result["ok"] is False and "already served" in result["error"]


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_nginx_site_rolls_back_when_nginx_rejects_it(setup: Any) -> None:
    agent, host, config = setup
    host.answers["nginx -t"] = (1, "emerg: something")
    result = call(agent, "nginx_site", {"name": "t30", "domain": "t30.example.com", "port": 8002})
    assert result["ok"] is False and "nothing was changed" in result["error"]
    assert not (config.nginx_available / "t30.example.com").exists()
    assert not (config.nginx_enabled / "t30.example.com").is_symlink()


def test_discard_only_webos_clones(setup: Any) -> None:
    agent, host, config = setup
    project = make_project(config)
    assert call(agent, "discard", {"name": "shop"})["ok"] is False
    (project / ".git" / "webos-project").write_text("shop\n")
    host.answers["docker ps"] = (0, "abc123\n")
    assert "still exist" in call(agent, "discard", {"name": "shop"})["error"]
    host.answers["docker ps"] = (0, "")
    assert call(agent, "discard", {"name": "shop"})["ok"]
    assert not project.exists()


def test_fake_certbot_mode(setup: Any) -> None:
    agent, host, config = setup
    agent.config = wa.replace(config, fake_certbot=True)
    assert call(agent, "certbot", {"domain": "t30.example.com"})["result"]["fake"] is True
    assert host.commands == []


def test_certbot_command(setup: Any) -> None:
    agent, host, _ = setup
    assert call(
        agent, "certbot", {"domain": "t30.example.com", "aliases": ["www.t30.example.com"]}
    )["ok"]
    [cmd] = host.commands
    assert cmd[:2] == ["certbot", "--nginx"] and "--non-interactive" in cmd
    assert cmd[-4:] == ["-d", "t30.example.com", "-d", "www.t30.example.com"]
