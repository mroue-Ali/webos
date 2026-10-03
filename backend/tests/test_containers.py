import json

from sqlalchemy import select

from tests.conftest import APP_ID, DB_ID, SELF_ID, STRAY_ID, Env
from webos.models import AuditEvent, Project


def register(env: Env, compose_project: str = "shop") -> None:
    response = env.client.post("/api/projects", json={"compose_project": compose_project})
    assert response.status_code == 201, response.text


def test_overview_groups_and_flags(authed: Env) -> None:
    register(authed)
    response = authed.client.get("/api/overview")
    assert response.status_code == 200
    data = response.json()
    assert data["docker"] == {"version": "28.1.1", "running": 3, "total": 4}

    [project] = data["projects"]
    assert project["slug"] == "shop"
    containers = {c["name"]: c for c in project["containers"]}
    assert containers["shop-db"]["warnings"] == ["public_port"]
    assert containers["shop-web"]["warnings"] == []
    assert all(c["manageable"] for c in containers.values())

    unmanaged = {g["compose_project"]: g for g in data["unmanaged"]}
    assert unmanaged["webos"]["is_self"] is True
    assert unmanaged[None]["containers"][0]["warnings"] == ["exited_error"]
    assert not any(c["manageable"] for g in data["unmanaged"] for c in g["containers"])


def test_container_env_never_leaves_the_server(authed: Env) -> None:
    register(authed)
    assert "hunter2" not in authed.client.get("/api/overview").text


def test_stop_and_restart_need_the_container_name(authed: Env) -> None:
    register(authed)
    for body in ({}, {"confirm": "wrong"}):
        response = authed.client.post(f"/api/containers/{APP_ID}/restart", json=body)
        assert response.status_code == 400
    assert authed.docker.posts() == []


def test_restart_runs_and_is_audited(authed: Env) -> None:
    register(authed)
    response = authed.client.post(f"/api/containers/{APP_ID}/restart", json={"confirm": "shop-web"})
    assert response.status_code == 200
    assert authed.docker.posts() == [f"/containers/{APP_ID}/restart"]

    with authed.db() as db:
        rows = db.scalars(select(AuditEvent).where(AuditEvent.action == "container.restart")).all()
    assert [r.outcome for r in rows] == ["started", "ok"]
    assert rows[0].request_id == rows[1].request_id
    assert rows[0].actor == "ali" and rows[0].target == "shop-web"
    assert json.loads(rows[0].params) == {"project": "shop", "container_id": APP_ID[:12]}


def test_start_needs_no_confirmation(authed: Env) -> None:
    register(authed)
    assert authed.client.post(f"/api/containers/{DB_ID}/start", json={}).status_code == 200


def test_unregistered_containers_are_view_only(authed: Env) -> None:
    response = authed.client.post(f"/api/containers/{STRAY_ID}/start", json={})
    assert response.status_code == 403
    assert authed.docker.posts() == []


def test_webos_refuses_to_stop_itself(authed: Env) -> None:
    register(authed, "webos")
    response = authed.client.post(
        f"/api/containers/{SELF_ID}/stop", json={"confirm": "webos-webos"}
    )
    assert response.status_code == 403
    assert authed.docker.posts() == []


def test_malformed_ids_never_reach_docker(authed: Env) -> None:
    for bad in ("..%2Fcreate", "ABCDEF123456", "abc"):
        response = authed.client.post(f"/api/containers/{bad}/start", json={})
        assert response.status_code in (404, 422)
    assert authed.docker.posts() == []


def test_actions_require_login(env: Env) -> None:
    assert env.client.post(f"/api/containers/{APP_ID}/start", json={}).status_code == 401


def test_logs_stream_over_sse(authed: Env) -> None:
    with authed.client.stream("GET", f"/api/containers/{APP_ID}/logs?tail=10") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    events = [block for block in body.split("\n\n") if block.startswith("event:")]
    lines = [json.loads(e.split("data: ", 1)[1]) for e in events if e.startswith("event: line")]
    assert lines == [
        {"ts": "2026-10-01T10:00:00.000000001Z", "stream": "stdout", "text": "GET / 200"},
        {
            "ts": "2026-10-01T10:00:01.5Z",
            "stream": "stderr",
            "text": "Traceback (most recent call last)",
        },
    ]
    assert "id: 2026-10-01T10:00:01.5Z" in body
    assert events[-1] == 'event: end\ndata: {"reason":"eof"}'


def test_logs_resume_after_last_event_id(authed: Env) -> None:
    with authed.client.stream(
        "GET",
        f"/api/containers/{APP_ID}/logs",
        headers={"Last-Event-ID": "2026-10-01T10:00:00.000000001Z"},
    ) as response:
        "".join(response.iter_text())
    [logs_call] = [path for _, path in authed.docker.calls if path.endswith("/logs")]
    assert logs_call == f"/containers/{APP_ID}/logs"


def test_project_restart_restarts_each_container(authed: Env) -> None:
    register(authed)
    assert authed.client.post("/api/projects/shop/restart", json={}).status_code == 400
    response = authed.client.post("/api/projects/shop/restart", json={"confirm": "shop"})
    assert response.status_code == 200
    assert sorted(authed.docker.posts()) == sorted(
        [f"/containers/{APP_ID}/restart", f"/containers/{DB_ID}/restart"]
    )


def test_import_records_the_loopback_port(authed: Env) -> None:
    register(authed)
    with authed.db() as db:
        project = db.scalar(select(Project))
    assert project is not None
    assert (project.port, project.working_dir) == (8001, "/home/ali/apps/shop")
    duplicate = authed.client.post("/api/projects", json={"compose_project": "shop"})
    assert duplicate.status_code == 409


def test_unregister_needs_confirmation_and_leaves_containers_alone(authed: Env) -> None:
    register(authed)
    assert authed.client.request("DELETE", "/api/projects/shop", json={}).status_code == 400
    response = authed.client.request("DELETE", "/api/projects/shop", json={"confirm": "shop"})
    assert response.status_code == 200
    assert authed.docker.posts() == []
    assert authed.client.get("/api/overview").json()["projects"] == []


def test_update_project_fields(authed: Env) -> None:
    register(authed)
    response = authed.client.patch("/api/projects/shop", json={"domain": "shop.example.com"})
    assert response.status_code == 200
    [project] = authed.client.get("/api/overview").json()["projects"]
    assert project["domain"] == "shop.example.com"
    assert (
        authed.client.patch("/api/projects/shop", json={"domain": "not a domain"}).status_code
        == 422
    )
