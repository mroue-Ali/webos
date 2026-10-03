"""The audit log: one row per state change and login attempt, mirrored to stdout."""

import json
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from webos.models import AuditEvent, utcnow

logger = logging.getLogger("webos.audit")


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def record(
    db: Session,
    *,
    action: str,
    outcome: str,
    actor: str | None,
    target: str | None = None,
    params: Mapping[str, Any] | None = None,
    error: str | None = None,
    request_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Write one audit row. Callers pass only allowlisted params, never .env values."""
    event = AuditEvent(
        ts=utcnow(),
        request_id=request_id,
        actor=actor[:64] if actor else None,
        action=action,
        target=target[:255] if target else None,
        params=json.dumps(dict(params or {}), sort_keys=True, default=str),
        outcome=outcome,
        error=error[:500] if error else None,
        ip=ip,
        user_agent=user_agent[:300] if user_agent else None,
    )
    db.add(event)
    db.commit()
    logger.info(
        json.dumps(
            {
                "audit": action,
                "outcome": outcome,
                "actor": event.actor,
                "target": event.target,
                "params": json.loads(event.params),
                "error": event.error,
                "request_id": request_id,
                "ip": ip,
                "ts": event.ts.isoformat() + "Z",
            }
        )
    )


def record_request(
    db: Session,
    request: Request,
    *,
    action: str,
    outcome: str,
    actor: str | None = None,
    target: str | None = None,
    params: Mapping[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Write an audit row with the actor and client details taken from the request."""
    user = getattr(request.state, "user", None)
    record(
        db,
        action=action,
        outcome=outcome,
        actor=actor or (user.username if user else None),
        target=target,
        params=params,
        error=error,
        request_id=getattr(request.state, "request_id", None),
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


@asynccontextmanager
async def audited(
    db: Session,
    request: Request,
    *,
    action: str,
    target: str,
    params: Mapping[str, Any] | None = None,
) -> AsyncIterator[None]:
    """Record `started`, then `ok` or `error`. Two rows, because rows are never updated."""
    record_request(db, request, action=action, outcome="started", target=target, params=params)
    try:
        yield
    except Exception as exc:
        message = getattr(exc, "message", None) or getattr(exc, "detail", None) or str(exc)
        record_request(
            db,
            request,
            action=action,
            outcome="error",
            target=target,
            params=params,
            error=str(message) or type(exc).__name__,
        )
        raise
    record_request(db, request, action=action, outcome="ok", target=target, params=params)
