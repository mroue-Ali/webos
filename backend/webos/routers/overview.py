from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from webos.context import get_context
from webos.db import get_db
from webos.docker_api import LABEL_PROJECT
from webos.models import User
from webos.overview import build_overview
from webos.schemas import OverviewOut
from webos.security.auth import require_user, session_guard
from webos.sse import SseEvent, sse_response

router = APIRouter(prefix="/api", tags=["overview"])


@router.get("/overview")
async def overview(
    request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)
) -> OverviewOut:
    ctx = get_context(request)
    return await build_overview(
        ctx.docker, db, self_project=ctx.settings.self_project, busy=ctx.deployer.busy
    )


@router.get("/events")
async def events(request: Request, user: User = Depends(require_user)) -> StreamingResponse:
    """Container lifecycle events; the dashboard refetches the overview when one arrives."""
    docker = get_context(request).docker

    async def source() -> AsyncIterator[SseEvent]:
        async for event in docker.events():
            actor = event.get("Actor") or {}
            attributes = actor.get("Attributes") or {}
            yield (
                "container",
                {
                    "action": str(event.get("Action") or event.get("status") or ""),
                    "id": str(actor.get("ID") or event.get("id") or ""),
                    "name": str(attributes.get("name") or ""),
                    "project": attributes.get(LABEL_PROJECT),
                },
                None,
            )

    return sse_response(source(), session_guard(request))
