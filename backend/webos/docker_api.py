"""A thin async client for the Docker Engine API.

Every endpoint webos calls is in this file, and it is the same list the socket proxy in
docker-compose.yml allows: list/inspect/logs/stats, start/stop/restart, events, version,
info and system df. Nothing here can create, exec into, or build a container.
"""

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

CONTAINER_ID_PATTERN = r"^[a-f0-9]{12,64}$"
_CONTAINER_ID = re.compile(CONTAINER_ID_PATTERN)
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z")

LABEL_PROJECT = "com.docker.compose.project"
LABEL_SERVICE = "com.docker.compose.service"
LABEL_WORKING_DIR = "com.docker.compose.project.working_dir"

MAX_LINE_CHARS = 16_000
_REQUEST_TIMEOUT = httpx.Timeout(15.0)
_STREAM_TIMEOUT = httpx.Timeout(15.0, read=None)  # follow streams stay open indefinitely


class DockerError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class PortBinding:
    ip: str
    private_port: int
    public_port: int | None
    protocol: str

    @property
    def public(self) -> bool:
        """Published on every interface. Docker's own iptables rules skip ufw for these."""
        return self.public_port is not None and self.ip in ("0.0.0.0", "::", "")  # noqa: S104


@dataclass(frozen=True)
class Container:
    id: str
    name: str
    image: str
    state: str
    status: str
    health: str | None
    compose_project: str | None
    compose_service: str | None
    working_dir: str | None
    ports: tuple[PortBinding, ...]


@dataclass(frozen=True)
class ContainerDetails:
    restart_count: int = 0
    exit_code: int | None = None
    oom_killed: bool = False
    started_at: str | None = None
    tty: bool = False


@dataclass(frozen=True)
class LogLine:
    ts: str
    stream: Literal["stdout", "stderr"]
    text: str


def check_container_id(container_id: str) -> None:
    """Validate before an id goes into a URL path, so `../create` can never reach the engine."""
    if not _CONTAINER_ID.fullmatch(container_id):
        raise DockerError(400, "Invalid container id")


def timestamp_to_since(ts: str) -> str | None:
    """Turn a log timestamp into Docker's `since` value, 1ns later (to resume after it)."""
    if not _TIMESTAMP.fullmatch(ts):
        return None
    whole, _, fraction = ts[:-1].partition(".")
    seconds = int(datetime.strptime(whole, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC).timestamp())
    nanos = int((fraction + "000000000")[:9]) + 1
    seconds, nanos = seconds + nanos // 1_000_000_000, nanos % 1_000_000_000
    return f"{seconds}.{nanos:09d}"


class DockerClient:
    def __init__(self, base_url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url, transport=transport, timeout=_REQUEST_TIMEOUT
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def version(self) -> dict[str, Any]:
        return dict((await self._request("GET", "/version")).json())

    async def info(self) -> dict[str, Any]:
        return dict((await self._request("GET", "/info")).json())

    async def system_df(self) -> dict[str, Any]:
        """Disk used by images, containers, volumes and build cache (`docker system df`)."""
        response = await self._request("GET", "/system/df", timeout=httpx.Timeout(60.0))
        return dict(response.json())

    async def stats(self, container_id: str) -> dict[str, Any]:
        """One stats reading. Docker samples twice about a second apart, so CPU % works."""
        check_container_id(container_id)
        response = await self._request(
            "GET", f"/containers/{container_id}/stats", params={"stream": "false"}
        )
        return dict(response.json())

    async def list_containers(self) -> list[Container]:
        response = await self._request("GET", "/containers/json", params={"all": "1"})
        return [_parse_container(raw) for raw in response.json()]

    async def details(self, container_id: str) -> ContainerDetails:
        data = await self.inspect(container_id)
        state = data.get("State") or {}
        started = state.get("StartedAt")
        return ContainerDetails(
            restart_count=int(data.get("RestartCount") or 0),
            exit_code=state.get("ExitCode"),
            oom_killed=bool(state.get("OOMKilled")),
            started_at=None if not started or started.startswith("0001-") else started,
            tty=bool((data.get("Config") or {}).get("Tty")),
        )

    async def inspect(self, container_id: str) -> dict[str, Any]:
        check_container_id(container_id)
        data = dict((await self._request("GET", f"/containers/{container_id}/json")).json())
        # Config.Env holds everything a project loads from its .env. Drop it here, first,
        # so no other code ever sees project secrets.
        (data.get("Config") or {}).pop("Env", None)
        return data

    async def start(self, container_id: str) -> None:
        check_container_id(container_id)
        await self._request("POST", f"/containers/{container_id}/start")

    async def stop(self, container_id: str, grace_seconds: int = 10) -> None:
        check_container_id(container_id)
        await self._request(
            "POST",
            f"/containers/{container_id}/stop",
            params={"t": str(grace_seconds)},
            timeout=httpx.Timeout(grace_seconds + 15.0),
        )

    async def restart(self, container_id: str, grace_seconds: int = 10) -> None:
        check_container_id(container_id)
        await self._request(
            "POST",
            f"/containers/{container_id}/restart",
            params={"t": str(grace_seconds)},
            timeout=httpx.Timeout(grace_seconds + 15.0),
        )

    async def logs(
        self, container_id: str, *, tail: int | str, since: str | None, tty: bool
    ) -> AsyncIterator[LogLine]:
        """Follow a container's logs, line by line, with stdout and stderr kept apart."""
        check_container_id(container_id)
        params = {"stdout": "1", "stderr": "1", "follow": "1", "timestamps": "1", "tail": str(tail)}
        if since:
            params["since"] = since
        async with self._http.stream(
            "GET", f"/containers/{container_id}/logs", params=params, timeout=_STREAM_TIMEOUT
        ) as response:
            await _raise_for_status(response)
            splitters = {1: _LineSplitter(), 2: _LineSplitter()}
            demuxer = None if tty else _Demuxer()
            async for chunk in response.aiter_bytes():
                frames = [(1, chunk)] if demuxer is None else demuxer.feed(chunk)
                for stream_type, payload in frames:
                    splitter = splitters.get(stream_type)
                    if splitter is None:
                        continue
                    name: Literal["stdout", "stderr"] = "stdout" if stream_type == 1 else "stderr"
                    for raw in splitter.feed(payload):
                        yield _parse_log_line(raw, name)

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Stream container lifecycle events (start, die, health_status, ...)."""
        params = {"filters": json.dumps({"type": ["container"]})}
        async with self._http.stream(
            "GET", "/events", params=params, timeout=_STREAM_TIMEOUT
        ) as response:
            await _raise_for_status(response)
            async for line in response.aiter_lines():
                if line.strip():
                    yield json.loads(line)

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise DockerError(502, "Docker API unreachable") from exc
        await _raise_for_status(response)
        return response


async def _raise_for_status(response: httpx.Response) -> None:
    # 304 means "already started/stopped": the desired state holds, so it is not an error.
    if response.status_code < 400:
        return
    if response.status_code == 403:
        raise DockerError(403, "Blocked by the Docker socket proxy")
    await response.aread()
    try:
        message = str(response.json().get("message") or response.reason_phrase)
    except (ValueError, AttributeError):
        message = response.reason_phrase
    raise DockerError(response.status_code, message)


def _parse_container(raw: dict[str, Any]) -> Container:
    labels: dict[str, str] = raw.get("Labels") or {}
    names: list[str] = raw.get("Names") or []
    status = str(raw.get("Status") or "")
    return Container(
        id=str(raw["Id"]),
        name=names[0].lstrip("/") if names else str(raw["Id"])[:12],
        image=str(raw.get("Image") or ""),
        state=str(raw.get("State") or "unknown"),
        status=status,
        health=_health_from_status(status),
        compose_project=labels.get(LABEL_PROJECT),
        compose_service=labels.get(LABEL_SERVICE),
        working_dir=labels.get(LABEL_WORKING_DIR),
        ports=tuple(
            PortBinding(
                ip=str(p.get("IP") or ""),
                private_port=int(p["PrivatePort"]),
                public_port=p.get("PublicPort"),
                protocol=str(p.get("Type") or "tcp"),
            )
            for p in raw.get("Ports") or []
        ),
    )


def _health_from_status(status: str) -> str | None:
    if "(healthy)" in status:
        return "healthy"
    if "(unhealthy)" in status:
        return "unhealthy"
    if "(health: starting)" in status:
        return "starting"
    return None


def _parse_log_line(raw: str, stream: Literal["stdout", "stderr"]) -> LogLine:
    ts, _, text = raw.partition(" ")
    if not _TIMESTAMP.fullmatch(ts):
        ts, text = "", raw
    return LogLine(ts=ts, stream=stream, text=text[:MAX_LINE_CHARS])


class _Demuxer:
    """Splits Docker's multiplexed (non-TTY) stream: 8-byte header, then the payload.

    Header: [stream type: 1=stdout, 2=stderr][0 0 0][payload size, big-endian uint32].
    """

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> list[tuple[int, bytes]]:
        self._buffer += chunk
        frames = []
        while len(self._buffer) >= 8:
            size = int.from_bytes(self._buffer[4:8], "big")
            if len(self._buffer) < 8 + size:
                break
            frames.append((self._buffer[0], bytes(self._buffer[8 : 8 + size])))
            del self._buffer[: 8 + size]
        return frames


class _LineSplitter:
    def __init__(self) -> None:
        self._partial = b""

    def feed(self, data: bytes) -> list[str]:
        *lines, self._partial = (self._partial + data).split(b"\n")
        if len(self._partial) > MAX_LINE_CHARS * 4:  # a runaway line with no newline
            lines.append(self._partial)
            self._partial = b""
        return [line.rstrip(b"\r").decode("utf-8", "replace") for line in lines]
