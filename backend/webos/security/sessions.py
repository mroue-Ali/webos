"""Stateless sessions: a signed cookie, invalidated by bumping users.session_version."""

from dataclasses import dataclass
from typing import Any

from itsdangerous import BadSignature, URLSafeSerializer


@dataclass(frozen=True)
class SessionData:
    uid: int
    ver: int
    iat: int  # issued at (unix seconds)
    seen: int  # last activity (unix seconds); refreshed as the user works


class SessionCodec:
    def __init__(self, key: bytes, *, idle_seconds: int, max_seconds: int) -> None:
        self._serializer = URLSafeSerializer(key, salt="webos.session")
        self.idle_seconds = idle_seconds
        self.max_seconds = max_seconds

    def dump(self, data: SessionData) -> str:
        return self._serializer.dumps([data.uid, data.ver, data.iat, data.seen])

    def load(self, token: str, *, now: float) -> SessionData | None:
        """Return the session if the signature is valid and it has not expired."""
        try:
            raw: Any = self._serializer.loads(token)
        except BadSignature:
            return None
        if not (isinstance(raw, list) and len(raw) == 4 and all(type(v) is int for v in raw)):
            return None
        data = SessionData(*raw)
        return data if now < self.deadline(data) else None

    def deadline(self, data: SessionData) -> float:
        """The moment this session expires unless the user is active again before it."""
        return min(data.seen + self.idle_seconds, data.iat + self.max_seconds)
