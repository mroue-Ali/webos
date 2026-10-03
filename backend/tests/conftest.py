import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pyotp
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from webos import migrate
from webos.config import Settings
from webos.docker_api import DockerClient
from webos.main import create_app
from webos.models import User
from webos.security.passwords import hash_password

SECRET_KEY = "test-secret-key-that-is-long-enough-0123456789"
ORIGIN = "https://testserver"
USERNAME = "ali"
PASSWORD = "correct horse battery staple"
TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"

APP_ID = "a" * 64
DB_ID = "b" * 64
STRAY_ID = "c" * 64
SELF_ID = "d" * 64


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def raw_container(
    cid: str,
    name: str,
    project: str | None,
    *,
    state: str = "running",
    status: str = "Up 2 hours",
    ports: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    labels = {}
    if project:
        labels = {
            "com.docker.compose.project": project,
            "com.docker.compose.service": name.split("-")[1] if "-" in name else name,
            "com.docker.compose.project.working_dir": f"/home/ali/apps/{project}",
        }
    return {
        "Id": cid,
        "Names": [f"/{name}"],
        "Image": f"{name}:latest",
        "State": state,
        "Status": status,
        "Labels": labels,
        "Ports": ports or [],
    }


def log_frame(stream: int, text: str) -> bytes:
    payload = text.encode()
    return bytes([stream, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload


@dataclass
class FakeDocker:
    """Answers the handful of Engine API calls webos makes, and records them."""

    containers: list[dict[str, Any]] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)
    log_bytes: bytes = b""

    def __post_init__(self) -> None:
        self.containers = [
            raw_container(
                APP_ID,
                "shop-web",
                "shop",
                ports=[{"IP": "127.0.0.1", "PrivatePort": 80, "PublicPort": 8001, "Type": "tcp"}],
            ),
            raw_container(
                DB_ID,
                "shop-db",
                "shop",
                ports=[{"IP": "0.0.0.0", "PrivatePort": 3306, "PublicPort": 3306, "Type": "tcp"}],
            ),
            raw_container(STRAY_ID, "stray", None, state="exited", status="Exited (1) 3 min ago"),
            raw_container(SELF_ID, "webos-webos", "webos"),
        ]
        self.log_bytes = log_frame(1, "2026-10-01T10:00:00.000000001Z GET / 200\n") + log_frame(
            2, "2026-10-01T10:00:01.5Z Traceback (most recent call last)\n"
        )

    def find(self, cid: str) -> dict[str, Any] | None:
        return next((c for c in self.containers if c["Id"].startswith(cid)), None)

    def posts(self) -> list[str]:
        return [path for method, path in self.calls if method == "POST"]

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        if path == "/version":
            return httpx.Response(200, json={"Version": "28.1.1"})
        if path == "/containers/json":
            return httpx.Response(200, json=self.containers)
        if path == "/events":
            event = {"Action": "start", "Actor": {"ID": APP_ID, "Attributes": {"name": "shop-web"}}}
            return httpx.Response(200, content=json.dumps(event).encode() + b"\n")
        match = re.fullmatch(r"/containers/([a-f0-9]+)/(json|start|stop|restart|logs)", path)
        if match:
            container = self.find(match[1])
            if container is None:
                return httpx.Response(404, json={"message": "No such container"})
            if match[2] == "json":
                exit_code = 1 if container["State"] == "exited" else 0
                return httpx.Response(
                    200,
                    json={
                        "RestartCount": 2,
                        "State": {
                            "ExitCode": exit_code,
                            "OOMKilled": False,
                            "StartedAt": "2026-10-01T08:00:00Z",
                        },
                        "Config": {"Tty": False, "Env": ["DB_PASSWORD=hunter2"]},
                    },
                )
            if match[2] == "logs":
                return httpx.Response(200, content=self.log_bytes)
            return httpx.Response(204)
        return httpx.Response(404, json={"message": "page not found"})


@dataclass
class Env:
    app: FastAPI
    client: TestClient
    docker: FakeDocker
    clock: FakeClock

    def db(self) -> Session:
        return self.app.state.ctx.sessionmaker()  # type: ignore[no-any-return]

    def code(self, offset_steps: int = 0) -> str:
        return str(pyotp.TOTP(TOTP_SECRET).at(self.clock.now + offset_steps * 30))

    def login(self, code: str | None = None) -> httpx.Response:
        return self.client.post(
            "/api/auth/login",
            json={"username": USERNAME, "password": PASSWORD, "code": code or self.code()},
        )


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    settings = Settings(
        secret_key=SECRET_KEY,
        database_url=f"sqlite:///{tmp_path / 'webos.db'}",
        allowed_origins=[ORIGIN],
        docker_url="http://docker.test",
        _env_file=None,  # type: ignore[call-arg]
    )
    migrate.upgrade(settings.database_url)
    docker = FakeDocker()
    clock = FakeClock()
    app = create_app(
        settings,
        docker=DockerClient("http://docker.test", transport=httpx.MockTransport(docker.handler)),
        clock=clock,
    )
    with app.state.ctx.sessionmaker() as db:
        db.add(
            User(
                username=USERNAME,
                password_hash=hash_password(PASSWORD),
                totp_secret_enc=app.state.ctx.secrets.seal(TOTP_SECRET),
            )
        )
        db.commit()
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN, "X-WebOS": "1"}) as client:
        yield Env(app=app, client=client, docker=docker, clock=clock)


@pytest.fixture
def authed(env: Env) -> Env:
    assert env.login().status_code == 200
    return env
