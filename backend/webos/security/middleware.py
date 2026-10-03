"""Pure ASGI middleware (no BaseHTTPMiddleware, which buffers streaming responses)."""

import json
import uuid
from collections.abc import Iterable

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'"
)
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_api = scope["path"].startswith("/api")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Content-Security-Policy"] = CSP
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                headers["Cross-Origin-Opener-Policy"] = "same-origin"
                headers["Cross-Origin-Resource-Policy"] = "same-origin"
                headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                if self.hsts:
                    headers["Strict-Transport-Security"] = "max-age=31536000"
                if is_api:
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RequestIdMiddleware:
    """Tags each request with an id, shared by its audit rows and the X-Request-ID header."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        await self.app(scope, receive, send_with_id)


class OriginGuardMiddleware:
    """Refuses cross-site requests to /api: CSRF and cross-site WebSocket hijacking.

    SameSite=Strict alone is not enough: it is per *site*, so a page on any sibling
    subdomain (say, another project on the same domain) still counts as same-site.
    So we check the exact Origin as well:

    - Sec-Fetch-Site, when the browser sends it, must be same-origin or none.
    - Origin, when present, must be one of the allowed origins.
    - State-changing requests and WebSocket handshakes must carry an allowed Origin,
      and state-changing requests also need `X-WebOS: 1` (which forces a CORS preflight
      that we never answer).
    """

    def __init__(self, app: ASGIApp, *, allowed_origins: Iterable[str]) -> None:
        self.app = app
        self.allowed = frozenset(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or not scope["path"].startswith("/api"):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        fetch_site = headers.get("sec-fetch-site")
        origin = headers.get("origin")
        is_websocket = scope["type"] == "websocket"
        mutating = is_websocket or scope["method"] not in SAFE_METHODS

        refused = (
            (fetch_site is not None and fetch_site not in ("same-origin", "none"))
            or (origin is not None and origin not in self.allowed)
            or (mutating and origin is None)
            or (mutating and not is_websocket and headers.get("x-webos") != "1")
        )
        if not refused:
            await self.app(scope, receive, send)
        elif is_websocket:
            await send({"type": "websocket.close", "code": 4403})
        else:
            body = json.dumps({"detail": "Cross-origin request refused"}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
