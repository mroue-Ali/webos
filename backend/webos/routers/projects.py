import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from webos import audit
from webos.context import get_context
from webos.db import get_db
from webos.models import Project, User
from webos.routers.containers import DISRUPTIVE, Action, ensure_controllable, run_action
from webos.schemas import SLUG, ConfirmIn, OkOut, ProjectImportIn, ProjectUpdateIn
from webos.security.auth import require_user

router = APIRouter(prefix="/api/projects", tags=["projects"])

Slug = Annotated[str, Path(pattern=SLUG)]


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:40] or "project"


def get_project(db: Session, slug: str) -> Project:
    project = db.scalar(select(Project).where(Project.slug == slug))
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such project")
    return project


def ensure_port_free(db: Session, port: int, *, exclude_id: int | None = None) -> None:
    other = db.scalar(select(Project).where(Project.port == port))
    if other is not None and other.id != exclude_id:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Port {port} is assigned to {other.slug}")


@router.post("", status_code=status.HTTP_201_CREATED)
async def import_project(
    body: ProjectImportIn,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> OkOut:
    """Register an existing compose stack. Details come from its containers' labels."""
    ctx = get_context(request)
    containers = [
        c for c in await ctx.docker.list_containers() if c.compose_project == body.compose_project
    ]
    if not containers:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No containers belong to that compose project"
        )

    slug = body.slug or slugify(body.compose_project)
    if db.scalar(select(Project).where(Project.slug == slug)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"A project named {slug!r} already exists")
    if db.scalar(select(Project).where(Project.compose_project == body.compose_project)):
        raise HTTPException(status.HTTP_409_CONFLICT, "That compose project is already registered")

    # Record the stack's loopback port in the registry when there's exactly one.
    loopback = {
        p.public_port for c in containers for p in c.ports if p.public_port and p.ip == "127.0.0.1"
    }
    port = loopback.pop() if len(loopback) == 1 else None
    if port is not None and db.scalar(select(Project).where(Project.port == port)):
        port = None

    project = Project(
        slug=slug,
        display_name=body.display_name or body.compose_project,
        compose_project=body.compose_project,
        working_dir=next((c.working_dir for c in containers if c.working_dir), None),
        domain=body.domain,
        port=port,
    )
    db.add(project)
    db.commit()
    audit.record_request(
        db,
        request,
        action="project.import",
        outcome="ok",
        target=slug,
        params={"compose_project": body.compose_project, "port": port, "domain": body.domain},
    )
    return OkOut()


@router.patch("/{slug}")
def update_project(
    slug: Slug,
    body: ProjectUpdateIn,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> OkOut:
    project = get_project(db, slug)
    changes = body.model_dump(exclude_unset=True)
    if "display_name" in changes and changes["display_name"] is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "display_name can't be empty")
    if changes.get("port") is not None:
        ensure_port_free(db, changes["port"], exclude_id=project.id)
    for field, value in changes.items():
        setattr(project, field, value)
    db.commit()
    audit.record_request(
        db, request, action="project.update", outcome="ok", target=slug, params=changes
    )
    return OkOut()


@router.delete("/{slug}")
def unregister_project(
    slug: Slug,
    body: ConfirmIn,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> OkOut:
    """Forget the project. Its containers, files and nginx config are left untouched."""
    project = get_project(db, slug)
    if body.confirm != project.slug:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Confirmation required: send confirm={slug!r}"
        )
    db.delete(project)
    db.commit()
    audit.record_request(
        db,
        request,
        action="project.unregister",
        outcome="ok",
        target=slug,
        params={"compose_project": project.compose_project},
    )
    return OkOut()


@router.post("/{slug}/{action}")
async def project_action(
    slug: Slug,
    action: Action,
    body: ConfirmIn,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> OkOut:
    """Start, stop or restart every container of the project."""
    ctx = get_context(request)
    project = get_project(db, slug)
    ensure_controllable(ctx, db, project.compose_project)
    if action in DISRUPTIVE and body.confirm != project.slug:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Confirmation required: send confirm={slug!r}"
        )

    containers = [
        c
        for c in await ctx.docker.list_containers()
        if c.compose_project == project.compose_project
    ]
    if not containers:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This project has no containers (removed with `compose down`?). Recreating them "
            "needs `docker compose up`, which webos can't do yet.",
        )
    targets = [c for c in containers if action is not Action.start or c.state != "running"]

    async with audit.audited(
        db,
        request,
        action=f"project.{action}",
        target=slug,
        params={"containers": [c.name for c in targets]},
    ):
        for container in targets:
            await run_action(ctx, action, container.id)
    return OkOut()
