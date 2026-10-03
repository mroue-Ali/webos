import json
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from webos.db import get_db
from webos.models import AuditEvent, User
from webos.schemas import AuditEventOut, AuditPageOut
from webos.security.auth import require_user

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def list_audit_events(
    action: Annotated[str | None, Query(max_length=64)] = None,
    target: Annotated[str | None, Query(max_length=255)] = None,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> AuditPageOut:
    """Newest first. Pass the returned next_before to get the next page."""
    query = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit + 1)
    if action:
        # A prefix, so "container." matches every container action.
        query = query.where(AuditEvent.action.startswith(action, autoescape=True))
    if target:
        query = query.where(AuditEvent.target == target)
    if before:
        query = query.where(AuditEvent.id < before)

    rows = db.scalars(query).all()
    page = rows[:limit]
    return AuditPageOut(
        items=[
            AuditEventOut(
                id=e.id,
                ts=e.ts,
                request_id=e.request_id,
                actor=e.actor,
                action=e.action,
                target=e.target,
                params=json.loads(e.params),
                outcome=e.outcome,
                error=e.error,
                ip=e.ip,
                user_agent=e.user_agent,
            )
            for e in page
        ],
        next_before=page[-1].id if len(rows) > limit else None,
    )
