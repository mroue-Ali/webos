import json
import time
from typing import Any

import pytest
from sqlalchemy import select

from tests.conftest import SERVER_IP, Env
from webos import deployer as deployer_module
from webos.agent_client import AgentError
from webos.compose_override import ServiceChoice, generate_override, suggest
from webos.models import AuditEvent, Deployment, Project

COMPOSE = "backend/docker-compose.yml"
SECRET_ENV = "POSTGRES_PASSWORD=hunter2\nADMIN_TOKEN=s3cret-token\n"


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    answers: dict[str, list[str]] = {}

    async def resolve(name: str) -> list[str]:
        return answers.get(name, [SERVER_IP])

    monkeypatch.setattr(deployer_module, "resolve", resolve)
    monkeypatch.setattr("webos.routers.sites.resolve", resolve)
    return answers


def wait_for(env: Env, deployment_id: int, timeout: float = 5) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        detail = env.client.get(f"/api/deployments/{deployment_id}").json()
        if detail["status"] != "running":
            return dict(detail)
        time.sleep(0.02)
    raise AssertionError("deployment didn't finish")


def start_wizard(env: Env) -> dict[str, Any]:
    """Clone, inspect and preview, the way the wizard does."""
    created = env.client.post(
        "/api/sites", json={"name": "t30", "repo": "git@github.com:me/t30.git", "branch": "main"}
    )
    assert created.status_code == 201, created.text
    inspect = env.client.get(f"/api/sites/t30/inspect?compose_file={COMPOSE}")
    assert inspect.status_code == 200, inspect.text
    suggestion = inspect.json()["suggestion"]
    config = {
        "compose_file": COMPOSE,
        "web_service": suggestion["web_service"],
        "container_port": suggestion["container_port"],
        "services": {
            name: {"keep_volumes": c["keep_volumes"], "use_image_command": c["use_image_command"]}
            for name, c in suggestion["services"].items()
        },
    }
    preview = env.client.post("/api/sites/t30/preview", json=config)
    assert preview.status_code == 200, preview.text
    return {"config": config, "inspect": inspect.json(), "preview": preview.json()}


def deploy(env: Env, wizard: dict[str, Any], **extra: Any) -> dict[str, Any]:
    body = {
        **wizard["config"],
        "domain": "t30.example.com",
        "override": wizard["preview"]["override"],
        "env": SECRET_ENV,
        **extra,
    }
    started = env.client.post("/api/sites/t30/deploy", json=body)
    assert started.status_code == 200, started.text
    return wait_for(env, started.json()["deployment_id"])


def test_agent_status(authed: Env) -> None:
    status = authed.client.get("/api/agent").json()
    assert status["available"] is True and status["host_ips"] == [SERVER_IP]
    authed.agent.available = False
    status = authed.client.get("/api/agent").json()
    assert status["available"] is False and "isn't running" in status["error"]


def test_wizard_end_to_end(authed: Env) -> None:
    key = authed.client.post("/api/sites/deploy-key", json={"name": "t30"})
    assert key.json() == {"public_key": "ssh-ed25519 AAAAfake webos-t30@vps"}

    wizard = start_wizard(authed)
    inspect, preview = wizard["inspect"], wizard["preview"]
    assert inspect["domain_suggestion"] == "t30.example.com"
    assert inspect["env_example"].startswith("POSTGRES_PASSWORD=")
    assert len(inspect["violations"]) == 2  # the repo's dev compose as it is
    assert wizard["config"]["web_service"] == "api"
    assert wizard["config"]["container_port"] == 8000
    assert wizard["config"]["services"]["api"] == {"keep_volumes": [], "use_image_command": True}
    # 8000 and 8001 are taken (agent + Docker); 3306 is outside the range.
    assert preview["port"] == 8002
    assert '"127.0.0.1:8002:8000"' in preview["override"]
    assert preview["violations"] == []

    result = deploy(authed, wizard)
    assert result["status"] == "ok", result
    assert result["commit"] == "a" * 40
    steps = [line for line in result["log"].splitlines() if line.startswith("==> ")]
    assert steps == [
        "==> Read the current commit",
        "==> Write the environment file",
        "==> Check the compose file",
        "==> Build and start the containers",
        "==> Health check",
        "==> Check DNS",
        "==> nginx site",
        "==> HTTPS certificate",
        "==> Done",
    ]
    [env_write] = authed.agent.args_of("write_env")
    assert env_write["content"] == SECRET_ENV and env_write["env_file"] == ".env"
    [site] = authed.agent.args_of("nginx_site")
    assert site == {"name": "t30", "domain": "t30.example.com", "aliases": [], "port": 8002}

    with authed.db() as db:
        project = db.scalar(select(Project).where(Project.slug == "t30"))
        assert project is not None
        assert (project.state, project.managed, project.port) == ("active", True, 8002)
        assert project.deployed_commit == "a" * 40
        # Secrets went to the agent only: nowhere in the database.
        stored = json.dumps(
            [p.override for p in db.scalars(select(Project))]
            + [d.log for d in db.scalars(select(Deployment))]
            + [a.params for a in db.scalars(select(AuditEvent))]
        )
        assert "hunter2" not in stored and "s3cret-token" not in stored
        env_keys = [
            json.loads(a.params)
            for a in db.scalars(select(AuditEvent).where(AuditEvent.action == "site.create"))
        ]
        assert env_keys[0]["env_keys"] == ["POSTGRES_PASSWORD", "ADMIN_TOKEN"]

    overview = authed.client.get("/api/overview").json()
    [t30] = [p for p in overview["projects"] if p["slug"] == "t30"]
    assert t30["managed"] is True and t30["domain"] == "t30.example.com"


def test_names_that_are_taken(authed: Env) -> None:
    authed.client.post("/api/projects", json={"compose_project": "shop"})
    for name in ("shop", "webos"):
        response = authed.client.post(
            "/api/sites", json={"name": name, "repo": "https://github.com/me/x", "branch": "main"}
        )
        assert response.status_code == 409
    assert "clone" not in authed.agent.names()


def test_bad_repo_urls_never_reach_the_agent(authed: Env) -> None:
    for repo in ("ext::sh -c id", "--upload-pack=id", "file:///etc", "https://x.com/a b"):
        response = authed.client.post(
            "/api/sites", json={"name": "t30", "repo": repo, "branch": "main"}
        )
        assert response.status_code == 422
    assert authed.agent.calls == []


def test_safety_check_failure_keeps_the_site_a_draft(authed: Env) -> None:
    wizard = start_wizard(authed)
    authed.agent.answers["compose_config"] = {
        "services": {"api": {}},
        "violations": ["api: privileged containers are not allowed"],
    }
    result = deploy(authed, wizard)
    assert result["status"] == "failed"
    assert "safety check" in result["error"]
    assert "refused: api: privileged" in result["log"]
    assert "up" not in authed.agent.names()
    with authed.db() as db:
        project = db.scalar(select(Project).where(Project.slug == "t30"))
        assert project is not None and project.state == "draft"


def test_dns_must_point_here_before_certbot(authed: Env, fake_dns: dict[str, list[str]]) -> None:
    wizard = start_wizard(authed)
    fake_dns["t30.example.com"] = ["198.51.100.7"]
    result = deploy(authed, wizard)
    assert result["status"] == "failed"
    assert "points to 198.51.100.7, not this server" in result["error"]
    assert "nginx_site" not in authed.agent.names()
    # Retrying after fixing DNS works: every step is idempotent.
    fake_dns.pop("t30.example.com")
    assert deploy(authed, wizard)["status"] == "ok"


def test_agent_failure_is_reported(authed: Env) -> None:
    wizard = start_wizard(authed)
    authed.agent.answers["up"] = AgentError("docker compose up failed (exit 1):\nbuild error")
    result = deploy(authed, wizard)
    assert result["status"] == "failed" and "build error" in result["log"]


def deployed(authed: Env) -> None:
    assert deploy(authed, start_wizard(authed))["status"] == "ok"
    authed.agent.calls.clear()


def test_redeploy_pulls_and_needs_confirmation(authed: Env) -> None:
    deployed(authed)
    assert authed.client.post("/api/projects/t30/deploy", json={}).status_code == 400
    started = authed.client.post("/api/projects/t30/deploy", json={"confirm": "t30"})
    result = wait_for(authed, started.json()["deployment_id"])
    assert result["status"] == "ok" and result["commit"] == "b" * 40
    assert authed.agent.names()[:2] == ["pull", "compose_config"]
    assert "nginx_site" not in authed.agent.names() and "certbot" not in authed.agent.names()
    history = authed.client.get("/api/projects/t30/deployments").json()
    assert [d["trigger"] for d in history] == ["manual", "create"]


def test_one_deployment_at_a_time(authed: Env) -> None:
    deployed(authed)
    authed.app.state.ctx.deployer._busy.add("t30")
    response = authed.client.post("/api/projects/t30/deploy", json={"confirm": "t30"})
    assert response.status_code == 409


def test_env_editor(authed: Env) -> None:
    deployed(authed)
    assert authed.client.get("/api/projects/t30/env").json() == {
        "content": "ADMIN_TOKEN=hunter2\n",
        "exists": True,
    }
    assert authed.client.put("/api/projects/t30/env", json={"content": "A=1"}).status_code == 400
    started = authed.client.put(
        "/api/projects/t30/env", json={"content": "NEW_SECRET=xyz\n", "confirm": "t30"}
    )
    assert wait_for(authed, started.json()["deployment_id"])["status"] == "ok"
    assert authed.agent.args_of("write_env")[-1]["content"] == "NEW_SECRET=xyz\n"
    with authed.db() as db:
        actions = {a.action: a.params for a in db.scalars(select(AuditEvent))}
    assert "env.read" in actions
    assert json.loads(actions["env.update"]) == {"keys": ["NEW_SECRET"]}
    assert "xyz" not in json.dumps(actions)


def test_auto_deploy_on_new_commit_once(authed: Env) -> None:
    deployed(authed)
    authed.client.patch("/api/projects/t30/site", json={"auto_deploy": True})
    deployer = authed.app.state.ctx.deployer
    portal = authed.client.portal
    assert portal is not None

    portal.call(deployer.check_for_updates)  # same commit: nothing to do
    assert "pull" not in authed.agent.names()

    authed.agent.answers["remote_head"] = {"commit": "c" * 40}
    authed.agent.answers["up"] = AgentError("broken build")
    portal.call(deployer.check_for_updates)
    [latest] = authed.client.get("/api/projects/t30/deployments").json()[:1]
    assert latest["trigger"] == "auto"
    assert wait_for(authed, latest["id"])["status"] == "failed"
    pulls = authed.agent.names().count("pull")
    portal.call(deployer.check_for_updates)  # the same broken commit isn't retried
    assert authed.agent.names().count("pull") == pulls


def test_remove_site(authed: Env) -> None:
    deployed(authed)
    assert authed.client.post("/api/projects/t30/remove", json={}).status_code == 400
    # 2FA is on for the test user, so removing a site needs a fresh code.
    without_code = authed.client.post("/api/projects/t30/remove", json={"confirm": "t30"})
    assert without_code.status_code == 400 and "authenticator" in without_code.text
    response = authed.client.post(
        "/api/projects/t30/remove",
        json={"confirm": "t30", "delete_files": True, "code": authed.code(offset_steps=1)},
    )
    assert response.status_code == 200, response.text
    assert authed.agent.names() == ["down", "nginx_remove", "cert_delete", "discard"]
    assert authed.agent.args_of("down")[0]["volumes"] is False
    assert all(p["slug"] != "t30" for p in authed.client.get("/api/overview").json()["projects"])


def test_discard_draft(authed: Env) -> None:
    start_wizard(authed)
    authed.agent.calls.clear()
    assert (
        authed.client.request("DELETE", "/api/sites/t30", json={"confirm": "t30"}).status_code
        == 200
    )
    assert authed.agent.names() == ["discard"]


def test_deployment_log_stream(authed: Env) -> None:
    deployed(authed)
    [deployment] = authed.client.get("/api/projects/t30/deployments").json()
    with authed.client.stream("GET", f"/api/deployments/{deployment['id']}/stream") as response:
        body = "".join(response.iter_text())
    assert '"text":"==> Done"' in body
    assert body.rstrip().endswith('data: {"reason":"eof"}')


def test_check_domain(authed: Env, fake_dns: dict[str, list[str]]) -> None:
    assert authed.client.get("/api/sites/check-domain?domain=t30.example.com").json()["ok"] is True
    fake_dns["x.example.com"] = []
    assert authed.client.get("/api/sites/check-domain?domain=x.example.com").json()["ok"] is False


def test_sites_need_login(env: Env) -> None:
    assert env.client.post("/api/sites/deploy-key", json={"name": "t30"}).status_code == 401
    assert env.client.get("/api/agent").status_code == 401


# --- the production layer -------------------------------------------------------------------

SERVICES = {
    "api": {
        "build": True,
        "command": ["uvicorn", "main:app", "--reload"],
        "ports": [{"target": 8000}],
        "volumes": [
            {"type": "bind", "source": "/srv/apps/t30/backend", "target": "/app"},
            {"type": "bind", "source": "/srv/apps/t30/backend/uploads", "target": "/up"},
        ],
    },
    "db": {
        "ports": [{"target": 5432}],
        "volumes": [{"type": "volume", "source": "pgdata", "target": "/var/lib/postgresql/data"}],
    },
    "worker": {"build": True, "command": "python worker.py"},
}


def test_suggestions() -> None:
    result = suggest(
        SERVICES, project_dir="/srv/apps/t30", compose_file="backend/docker-compose.yml"
    )
    assert (result["web_service"], result["container_port"]) == ("api", 8000)
    api = result["services"]["api"]
    assert api["dev_mounts"] == ["/app"] and api["keep_volumes"] == ["/up"]
    assert api["use_image_command"] is True
    assert result["services"]["db"]["keep_volumes"] is None
    assert result["services"]["worker"]["use_image_command"] is False


def test_generated_override() -> None:
    text = generate_override(
        compose_file="backend/docker-compose.yml",
        services=SERVICES,
        web_service="api",
        container_port=8000,
        host_port=8002,
        choices={"api": ServiceChoice(keep_volumes=("/up",), use_image_command=True)},
    )
    assert text == (
        "# Written by webos: production settings layered on backend/docker-compose.yml.\n"
        "# Change them in webos (project page); redeploys rewrite this file.\n"
        "services:\n"
        "  api:\n"
        "    restart: unless-stopped\n"
        "    ports: !override\n"
        '      - "127.0.0.1:8002:8000"\n'
        "    command: !reset null\n"
        "    volumes: !override\n"
        '      - type: "bind"\n'
        '        source: "/srv/apps/t30/backend/uploads"\n'
        '        target: "/up"\n'
        "  db:\n"
        "    restart: unless-stopped\n"
        "    ports: !reset []\n"
        "  worker:\n"
        "    restart: unless-stopped\n"
    )


def test_override_refuses_unknown_services() -> None:
    with pytest.raises(ValueError):
        generate_override(
            compose_file="c.yml",
            services=SERVICES,
            web_service="nope",
            container_port=80,
            host_port=8002,
            choices={},
        )
    with pytest.raises(ValueError):
        generate_override(
            compose_file="c.yml",
            services={"bad name\n": {}},
            web_service="bad name\n",
            container_port=80,
            host_port=8002,
            choices={},
        )
