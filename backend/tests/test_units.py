import pyotp
import pytest
from sqlalchemy import exc, text

from tests.conftest import TOTP_SECRET, Env, log_frame
from webos.docker_api import (
    DockerError,
    PortBinding,
    _Demuxer,
    _LineSplitter,
    check_container_id,
    timestamp_to_since,
)
from webos.security import totp
from webos.security.throttle import LoginThrottle


def test_audit_log_is_append_only(authed: Env) -> None:
    with authed.db() as db:
        for statement in ("UPDATE audit_events SET outcome = 'ok'", "DELETE FROM audit_events"):
            with pytest.raises(exc.DBAPIError, match="append-only"):
                db.execute(text(statement))
            db.rollback()


def test_audit_endpoint_paginates(authed: Env) -> None:
    for _ in range(3):
        authed.client.get("/api/auth/me")
        authed.client.post("/api/auth/logout")
        authed.login(authed.code(offset_steps=1))
        authed.clock.advance(30)
    first = authed.client.get("/api/audit?limit=2").json()
    assert len(first["items"]) == 2 and first["next_before"]
    second = authed.client.get(f"/api/audit?limit=2&before={first['next_before']}").json()
    assert second["items"][0]["id"] < first["items"][-1]["id"]
    assert all(
        e["action"].startswith("auth.")
        for e in authed.client.get("/api/audit?action=auth.").json()["items"]
    )


def test_totp_accepts_drift_but_not_replays() -> None:
    now = 1_800_000_000.0
    code = pyotp.TOTP(TOTP_SECRET).at(now - 30)
    step = totp.verify(TOTP_SECRET, code, last_step=0, now=now)
    assert step == int(now // 30) - 1
    assert totp.verify(TOTP_SECRET, code, last_step=step, now=now) is None
    assert (
        totp.verify(TOTP_SECRET, pyotp.TOTP(TOTP_SECRET).at(now - 90), last_step=0, now=now) is None
    )
    assert totp.verify(TOTP_SECRET, "12345a", last_step=0, now=now) is None


def test_throttle_backs_off_then_forgets() -> None:
    now = [0.0]
    throttle = LoginThrottle(clock=lambda: now[0])
    for _ in range(5):
        assert throttle.retry_after("ip") == 0
        throttle.record_failure("ip")
    assert throttle.retry_after("ip") == 30
    throttle.record_failure("ip")
    assert throttle.retry_after("ip") == 60
    for _ in range(4):
        throttle.record_failure("ip")
    assert throttle.retry_after("ip") == 900
    assert throttle.retry_after("other-ip") == 0
    now[0] += 3601
    assert throttle.retry_after("ip") == 0


def test_demuxer_handles_frames_split_across_chunks() -> None:
    data = log_frame(1, "hello\n") + log_frame(2, "oops\n")
    demuxer = _Demuxer()
    frames = demuxer.feed(data[:5]) + demuxer.feed(data[5:17]) + demuxer.feed(data[17:])
    assert frames == [(1, b"hello\n"), (2, b"oops\n")]


def test_line_splitter_keeps_partial_lines() -> None:
    splitter = _LineSplitter()
    assert splitter.feed(b"one\ntw") == ["one"]
    assert splitter.feed(b"o\r\n") == ["two"]


def test_timestamp_to_since() -> None:
    assert timestamp_to_since("2026-10-01T10:00:00Z") == "1790848800.000000001"
    assert timestamp_to_since("2026-10-01T10:00:00.999999999Z") == "1790848801.000000000"
    assert timestamp_to_since("not a timestamp") is None


def test_container_ids_are_validated() -> None:
    check_container_id("a" * 12)
    for bad in ("../create", "a" * 11, "A" * 12, "a" * 65):
        with pytest.raises(DockerError):
            check_container_id(bad)


def test_port_exposure() -> None:
    assert PortBinding("0.0.0.0", 3306, 3306, "tcp").public
    assert PortBinding("::", 3306, 3306, "tcp").public
    assert not PortBinding("127.0.0.1", 80, 8001, "tcp").public
    assert not PortBinding("", 80, None, "tcp").public
