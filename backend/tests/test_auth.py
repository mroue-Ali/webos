from sqlalchemy import select

from tests.conftest import Env
from webos.models import AuditEvent


def audit_errors(env: Env) -> list[str | None]:
    with env.db() as db:
        rows = db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.login")).all()
        return [r.error for r in rows if r.outcome == "error"]


def test_login_sets_hardened_cookie(env: Env) -> None:
    response = env.login()
    assert response.status_code == 200
    assert response.json() == {"username": "ali"}
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("__Host-webos=")
    for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/"):
        assert flag.lower() in cookie.lower()
    assert env.client.get("/api/auth/me").json() == {"username": "ali"}


def test_me_requires_login(env: Env) -> None:
    assert env.client.get("/api/auth/me").status_code == 401


def test_failures_are_generic_but_audited_by_factor(env: Env) -> None:
    bad_password = env.client.post(
        "/api/auth/login", json={"username": "ali", "password": "nope", "code": env.code()}
    )
    bad_code = env.login(code="000000" if env.code() != "000000" else "111111")
    unknown = env.client.post(
        "/api/auth/login", json={"username": "eve", "password": "x", "code": "123456"}
    )
    assert bad_password.status_code == bad_code.status_code == unknown.status_code == 401
    assert bad_password.json() == bad_code.json() == unknown.json()
    assert audit_errors(env) == ["bad_password", "bad_code", "unknown_user"]


def test_code_cannot_be_replayed(env: Env) -> None:
    code = env.code()
    assert env.login(code).status_code == 200
    env.client.cookies.clear()
    assert env.login(code).status_code == 401
    assert env.login(env.code(offset_steps=1)).status_code == 200


def test_throttle_after_repeated_failures(env: Env) -> None:
    for _ in range(5):
        assert env.login(code="999999").status_code == 401
    blocked = env.login()
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0


def test_idle_timeout_slides_with_activity(authed: Env) -> None:
    for _ in range(3):
        authed.clock.advance(20 * 60)
        assert authed.client.get("/api/auth/me").status_code == 200
    authed.clock.advance(31 * 60)
    assert authed.client.get("/api/auth/me").status_code == 401


def test_absolute_timeout(authed: Env) -> None:
    for _ in range(12 * 3):
        authed.clock.advance(20 * 60)
        authed.client.get("/api/auth/me")
    assert authed.client.get("/api/auth/me").status_code == 401


def test_logout_all_invalidates_existing_cookies(authed: Env) -> None:
    stolen = dict(authed.client.cookies)
    assert authed.client.post("/api/auth/logout-all").status_code == 204
    authed.client.cookies.clear()
    authed.client.cookies.update(stolen)
    assert authed.client.get("/api/auth/me").status_code == 401


def test_tampered_cookie_is_rejected(authed: Env) -> None:
    value = authed.client.cookies["__Host-webos"]
    authed.client.cookies.clear()
    authed.client.cookies.set("__Host-webos", value[:-2] + "xx")
    assert authed.client.get("/api/auth/me").status_code == 401
