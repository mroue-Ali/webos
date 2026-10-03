from fastapi.testclient import TestClient

from tests.conftest import ORIGIN, Env


def bare_client(env: Env) -> TestClient:
    """A client without the default Origin / X-WebOS headers (and no lifespan)."""
    return TestClient(env.app, base_url=ORIGIN)


def test_post_without_origin_is_refused(env: Env) -> None:
    response = bare_client(env).post("/api/auth/login", json={}, headers={"X-WebOS": "1"})
    assert response.status_code == 403


def test_post_from_other_origin_is_refused(env: Env) -> None:
    response = env.client.post(
        "/api/auth/login", json={}, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403


def test_sibling_subdomain_is_refused(env: Env) -> None:
    # SameSite=Strict would let this through; the exact-origin check doesn't.
    response = env.client.post(
        "/api/auth/logout",
        headers={"Origin": "https://blog.testserver", "Sec-Fetch-Site": "same-site"},
    )
    assert response.status_code == 403


def test_post_without_custom_header_is_refused(env: Env) -> None:
    response = bare_client(env).post("/api/auth/login", json={}, headers={"Origin": ORIGIN})
    assert response.status_code == 403


def test_cross_site_get_is_refused(env: Env) -> None:
    response = env.client.get("/api/auth/me", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403


def test_same_origin_get_without_origin_header_is_allowed(env: Env) -> None:
    # Browsers omit Origin on same-origin GETs such as EventSource.
    response = bare_client(env).get("/api/auth/me", headers={"Sec-Fetch-Site": "same-origin"})
    assert response.status_code == 401  # reached the app; just not signed in


def test_security_headers(env: Env) -> None:
    response = env.client.get("/api/auth/me")
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert len(response.headers["x-request-id"]) == 32


def test_api_docs_are_off_by_default(env: Env) -> None:
    assert env.client.get("/api/openapi.json").status_code == 404
