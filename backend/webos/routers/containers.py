from collections.abc import AsyncIterator
from dataclasses import asdict
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from webos import audit
from webos.context import AppContext, get_context
from webos.db import get_db
from webos.docker_api import CONTAINER_ID_PATTERN, Container, timestamp_to_since
from webos.models import Project, User
from webos.schemas import ConfirmIn, OkOut
from webos.security.auth import require_user, session_guard
from webos.sse import SseEvent, sse_response

router = APIRouter(prefix="/api/containers", tags=["containers"])

ContainerId = Annotated[str, Path(pattern=CONTAINER_ID_PATTERN)]


class Action(StrEnum):
    start = "start"
    stop = "stop"
    restart = "restart"


DISRUPTIVE = frozenset({Action.stop, Action.restart})


async def find_container(ctx: AppContext, container_id: str) -> Container:
    for container in await ctx.docker.list_containers():
        if container.id.startswith(container_id):
            return container
    raise HTTPException(status.HTTP_404_NOT_FOUND, "No such container")


def ensure_controllable(ctx: AppContext, db: Session, compose_project: str | None) -> Project:
    """Only containers of registered projects can be controlled, and never webos itself."""
    if compose_project == ctx.settings.self_project:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "webos won't stop or restart itself: you would lose the UI needed to bring it back",
        )
    project = (
        db.scalar(select(Project).where(Project.compose_project == compose_project))
        if compose_project
        else None
    )
    if project is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only containers of registered projects can be controlled. Import the project first.",
        )
    return project


async def run_action(ctx: AppContext, action: Action, container_id: str) -> None:
    if action is Action.start:
        await ctx.docker.start(container_id)
    elif action is Action.stop:
        await ctx.docker.stop(container_id)
    else:
        await ctx.docker.restart(container_id)


@router.post("/{container_id}/{action}")
async def container_action(
    container_id: ContainerId,
    action: Action,
    body: ConfirmIn,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> OkOut:
    ctx = get_context(request)
    container = await find_container(ctx, container_id)
    project = ensure_controllable(ctx, db, container.compose_project)
    if action in DISRUPTIVE and body.confirm != container.name:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Confirmation required: send confirm={container.name!r}"
        )

    async with audit.audited(
        db,
        request,
        action=f"container.{action}",
        target=container.name,
        params={"project": project.slug, "container_id": container.id[:12]},
    ):
        await run_action(ctx, action, container.id)
    return OkOut()


@router.get("/{container_id}/logs")
async def container_logs(
    container_id: ContainerId,
    request: Request,
    tail: Annotated[int, Query(ge=0, le=5000)] = 500,
    user: User = Depends(require_user),
) -> StreamingResponse:
    """Follow logs over SSE. Read-only, so unregistered containers are allowed too.

    On reconnect the browser sends Last-Event-ID (the last line's timestamp) and the stream
    resumes after it instead of replaying the tail.
    """
    ctx = get_context(request)
    details = await ctx.docker.details(container_id)  # 404 before the stream starts
    since = timestamp_to_since(request.headers.get("last-event-id", ""))

    async def source() -> AsyncIterator[SseEvent]:
        async for line in ctx.docker.logs(
            container_id, tail="all" if since else tail, since=since, tty=details.tty
        ):
            yield "line", asdict(line), line.ts or None

    return sse_response(source(), session_guard(request))
