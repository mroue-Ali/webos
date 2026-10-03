from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import HTTPConnection

from webos.config import Settings
from webos.docker_api import DockerClient
from webos.security.sessions import SessionCodec
from webos.security.throttle import LoginThrottle
from webos.security.totp import SecretBox


@dataclass
class AppContext:
    """Everything a request handler needs, built once in create_app."""

    settings: Settings
    sessionmaker: sessionmaker[Session]
    docker: DockerClient
    sessions: SessionCodec
    secrets: SecretBox
    throttle: LoginThrottle
    clock: Callable[[], float]

    @property
    def cookie_name(self) -> str:
        # The __Host- prefix makes the browser refuse the cookie unless it is Secure,
        # host-only and Path=/, so no subdomain can set or shadow it.
        return "__Host-webos" if self.settings.cookie_secure else "webos"


def get_context(conn: HTTPConnection) -> AppContext:
    return cast(AppContext, conn.app.state.ctx)
