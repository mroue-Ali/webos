"""The new-site wizard, deployments, the environment editor and site removal.

Wizard order: deploy key (private repos) -> clone -> inspect the compose file -> preview the
production layer -> deploy. Host work goes through webos-agent; project secrets (the .env)
pass through to it and are never stored or logged here.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from webos import audit
from webos.agent_client import AgentError, AgentUnavailable
from webos.compose_override import ServiceChoice, generate_override, suggest
from webos.context import AppContext, get_context
from webos.db import get_db
from webos.deployer import resolve
from webos.models import Deployment, Project, User
from webos.schemas import (
    DOMAIN,
    REL_PATH,
    AgentStatusOut,
    ConfirmIn,
    DeployKeyOut,
    DeploymentDetailOut,
    DeploymentOut,
    DeployStartedOut,
    DomainCheckOut,
    EnvOut,
    EnvUpdateIn,
    OkOut,
    RemoveSiteIn,
    RemoveSiteOut,
    SiteConfigIn,
    SiteCreatedOut,
    SiteCreateIn,
    SiteDeployIn,
    SiteInspectOut,
    SiteNameIn,
    SitePreviewOut,
    SiteSettingsIn,
)
from webos.security import totp
from webos.security.auth import require_user, session_guard
from webos.sse import SseEvent, sse_response

router = APIRouter(prefix="/api", tags=["sites"])


def bad_request(message: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, message)


def get_site(db: Session, slug: str, *, state: str | None = None) -> Project:
    project = db.scalar(select(Project).where(Project.slug == slug))
    if project is None or not project.managed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such site")
    if state is not None and project.state != state:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{slug} is {project.state}, not {state}")
    return project


async def ensure_name_free(ctx: AppContext, db: Session, name: str) -> None:
    taken = db.scalar(
        select(Project).where((Project.slug == name) | (Project.compose_project == name))
    )
    if taken is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"A project named {name!r} already exists")
    if any(c.compose_project == name for c in await ctx.docker.list_containers()):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A compose project named {name!r} already runs here"
        )


async def pick_port(ctx: AppContext, db: Session, project: Project) -> int:
    """The project's registered port, or the lowest free one in the site range."""
    if project.port:
        return project.port
    used = {p.port for p in db.scalars(select(Project)) if p.port}
    used |= set((await ctx.agent.call("ports", {})).get("listening") or [])
    used |= {
        port.public_port
        for container in await ctx.docker.list_containers()
        for port in container.ports
        if port.public_port
    }
    settings = ctx.settings
    for port in range(settings.site_port_min, settings.site_port_max + 1):
        if port not in used:
            return port
    raise HTTPException(status.HTTP_409_CONFLICT, "No free port left in the site port range")


async def repo_config(ctx: AppContext, slug: str, compose_file: str) -> dict[str, Any]:
    """The repository's own compose config, without webos's production layer."""
    result: dict[str, Any] = await ctx.agent.call(
        "compose_config", {"name": slug, "compose_file": compose_file, "override": ""}
    )
    return result


def choices_from(body: SiteConfigIn) -> dict[str, ServiceChoice]:
    return {
        name: ServiceChoice(
            keep_volumes=tuple(choice.keep_volumes) if choice.keep_volumes is not None else None,
            use_image_command=choice.use_image_command,
        )
        for name, choice in body.services.items()
    }


def env_keys(content: str) -> list[str]:
    keys = []
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.append(line.split("=", 1)[0].removeprefix("export ").strip())
    return keys


# --- agent and wizard -----------------------------------------------------------------------


@router.get("/agent")
async def agent_status(request: Request, user: User = Depends(require_user)) -> AgentStatusOut:
    try:
        info = await get_context(request).agent.call("ping", {}, timeout=30)
    except (AgentUnavailable, AgentError) as exc:
        return AgentStatusOut(available=False, error=str(exc))
    return AgentStatusOut(available=True, **info)


@router.post("/sites/deploy-key")
async def deploy_key(
    body: SiteNameIn,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> DeployKeyOut:
    """A read-only key for a private repository; add it under the repo's Deploy keys."""
    ctx = get_context(request)
    await ensure_name_free(ctx, db, body.name)
    result = await ctx.agent.call("deploy_key", {"name": body.name})
    audit.record_request(db, request, action="site.deploy_key", outcome="ok", target=body.name)
    return DeployKeyOut(public_key=result["public_key"])


@router.post("/sites", status_code=status.HTTP_201_CREATED)
async def create_site(
    body: SiteCreateIn,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> SiteCreatedOut:
    """Clone the repository into the apps folder and register it as a draft site."""
    ctx = get_context(request)
    await ensure_name_free(ctx, db, body.name)
    async with audit.audited(
        db,
        request,
        action="site.clone",
        target=body.name,
        params={"repo": body.repo, "branch": body.branch},
    ):
        head = await ctx.agent.call(
            "clone", {"name": body.name, "repo": body.repo, "branch": body.branch}, timeout=900
        )
    info = await ctx.agent.call("ping", {})
    files = (await ctx.agent.call("find_compose", {"name": body.name})).get("files") or []
    db.add(
        Project(
            slug=body.name,
            display_name=body.name,
            compose_project=body.name,
            working_dir=f"{info['apps_root']}/{body.name}",
            repo_url=body.repo,
            branch=body.branch,
            managed=True,
            state="draft",
        )
    )
    db.commit()
    return SiteCreatedOut(
        slug=body.name, commit=head["commit"], subject=head["subject"], compose_files=files
    )


@router.get("/sites/{slug}/compose-files")
async def compose_files(
    slug: str,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[str]:
    get_site(db, slug, state="draft")
    files = await get_context(request).agent.call("find_compose", {"name": slug})
    return list(files.get("files") or [])


@router.get("/sites/{slug}/inspect")
async def inspect_site(
    slug: str,
    request: Request,
    compose_file: Annotated[str, Query(pattern=REL_PATH)],
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> SiteInspectOut:
    ctx = get_context(request)
    project = get_site(db, slug, state="draft")
    config = await repo_config(ctx, slug, compose_file)
    example = ""
    if config.get("has_env_example"):
        example = (
            await ctx.agent.call("env_example", {"name": slug, "compose_file": compose_file})
        ).get("content") or ""
    info = await ctx.agent.call("ping", {})
    base = ctx.settings.base_domain
    return SiteInspectOut(
        compose_file=compose_file,
        services=config.get("services") or {},
        violations=config.get("violations") or [],
        env_example=example,
        suggestion=suggest(
            config.get("services") or {},
            project_dir=project.working_dir or "",
            compose_file=compose_file,
        ),
        port=await pick_port(ctx, db, project),
        domain_suggestion=f"{slug}.{base}" if base else None,
        server_ips=info.get("host_ips") or [],
    )


@router.post("/sites/{slug}/preview")
async def preview_site(
    slug: str,
    body: SiteConfigIn,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> SitePreviewOut:
    """Generate the production layer and run the safety check on the merged result."""
    ctx = get_context(request)
    project = get_site(db, slug, state="draft")
    services = (await repo_config(ctx, slug, body.compose_file)).get("services") or {}
    port = await pick_port(ctx, db, project)
    try:
        override = generate_override(
            compose_file=body.compose_file,
            services=services,
            web_service=body.web_service,
            container_port=body.container_port,
            host_port=port,
            choices=choices_from(body),
        )
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    merged = await ctx.agent.call(
        "compose_config", {"name": slug, "compose_file": body.compose_file, "override": override}
    )
    project.port = port  # reserve it in the registry
    db.commit()
    return SitePreviewOut(
        override=override,
        port=port,
        violations=merged.get("violations") or [],
        services=merged.get("services") or {},
    )


@router.post("/sites/{slug}/deploy")
async def deploy_site(
    slug: str,
    body: SiteDeployIn,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> DeployStartedOut:
    """First deployment. Safe to retry after a failure: every step is idempotent."""
    ctx = get_context(request)
    project = get_site(db, slug, state="draft")
    if not project.port:
        raise bad_request("Preview the setup first; that assigns the port")
    project.compose_file = body.compose_file
    project.env_file = body.env_file
    project.web_service = body.web_service
    project.container_port = body.container_port
    project.domain = body.domain
    project.aliases = " ".join(body.aliases) or None
    project.override = body.override
    project.auto_deploy = body.auto_deploy
    db.commit()
    audit.record_request(
        db,
        request,
        action="site.create",
        outcome="ok",
        target=slug,
        params={
            "domain": body.domain,
            "aliases": body.aliases,
            "port": project.port,
            "env_keys": env_keys(body.env),
        },
    )
    deployment_id = await ctx.deployer.start(slug, "create", user.username, env_content=body.env)
    return DeployStartedOut(deployment_id=deployment_id)


@router.delete("/sites/{slug}")
async def discard_draft(
    slug: str,
    body: ConfirmIn,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> OkOut:
    """Throw away a site that never finished its first deployment."""
    ctx = get_context(request)
    project = get_site(db, slug, state="draft")
    if body.confirm != slug:
        raise bad_request(f"Confirmation required: send confirm={slug!r}")
    if ctx.deployer.busy(slug):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{slug} is deploying")
    async with audit.audited(db, request, action="site.discard", target=slug):
        if project.compose_file:
            await ctx.agent.call(
                "down",
                {"name": slug, "compose_file": project.compose_file, "volumes": True},
                timeout=300,
            )
        if project.domain:
            await ctx.agent.call("nginx_remove", {"domain": project.domain})
        await ctx.agent.call("discard", {"name": slug})
        db.delete(project)
        db.commit()
    return OkOut()


@router.get("/sites/check-domain")
async def check_domain(
    request: Request,
    domain: Annotated[str, Query(max_length=253, pattern=DOMAIN)],
    user: User = Depends(require_user),
) -> DomainCheckOut:
    info = await get_context(request).agent.call("ping", {})
    server = info.get("host_ips") or []
    found = await resolve(domain)
    return DomainCheckOut(
        domain=domain, resolves_to=found, server_ips=server, ok=bool(set(found) & set(server))
    )


# --- deployments ---------------------------------------------------------------------------


def deployment_out(d: Deployment) -> DeploymentOut:
    return DeploymentOut(
        id=d.id,
        trigger=d.trigger,
        status=d.status,
        commit=d.commit,
        subject=d.subject,
        actor=d.actor,
        started_at=d.started_at,
        finished_at=d.finished_at,
        error=d.error,
    )


@router.get("/projects/{slug}/deployments")
def list_deployments(
    slug: str, user: User = Depends(require_user), db: Session = Depends(get_db)
) -> list[DeploymentOut]:
    project = get_site(db, slug)
    rows = db.scalars(
        select(Deployment)
        .where(Deployment.project_id == project.id)
        .order_by(Deployment.id.desc())
        .limit(50)
    )
    return [deployment_out(d) for d in rows]


def get_deployment(db: Session, deployment_id: int) -> tuple[Deployment, Project]:
    deployment = db.get(Deployment, deployment_id)
    project = db.get(Project, deployment.project_id) if deployment else None
    if deployment is None or project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such deployment")
    return deployment, project


@router.get("/deployments/{deployment_id}")
def deployment_detail(
    deployment_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> DeploymentDetailOut:
    deployment, project = get_deployment(db, deployment_id)
    run = get_context(request).deployer.runs.get(deployment_id)
    log = "\n".join(run.lines) if run and not run.finished else deployment.log
    return DeploymentDetailOut(
        **deployment_out(deployment).model_dump(), project=project.slug, log=log
    )


@router.get("/deployments/{deployment_id}/stream")
async def deployment_stream(
    deployment_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Live log over SSE: everything so far, then new lines until the deployment ends."""
    deployment, _ = get_deployment(db, deployment_id)
    run = get_context(request).deployer.runs.get(deployment_id)
    saved = deployment.log

    async def source() -> AsyncIterator[SseEvent]:
        if run is None:
            for line in saved.splitlines():
                yield "line", {"text": line}, None
            return
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        backlog = list(run.lines)
        run.listeners.add(queue)
        try:
            for line in backlog:
                yield "line", {"text": line}, None
            if run.finished:
                return
            while True:
                new = await queue.get()
                if new is None:
                    return
                yield "line", {"text": new}, None
        finally:
            run.listeners.discard(queue)

    return sse_response(source(), session_guard(request))


@router.post("/projects/{slug}/deploy")
async def redeploy(
    slug: str,
    body: ConfirmIn,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> DeployStartedOut:
    """Deploy now: pull the latest commit, rebuild, restart."""
    get_site(db, slug, state="active")
    if body.confirm != slug:
        raise bad_request(f"Confirmation required: send confirm={slug!r}")
    # End this request's read transaction first: the deployer writes on its own connection,
    # and SQLite is happiest with one transaction at a time.
    db.commit()
    deployment_id = await get_context(request).deployer.start(slug, "manual", user.username)
    return DeployStartedOut(deployment_id=deployment_id)


@router.patch("/projects/{slug}/site")
def update_site(
    slug: str,
    body: SiteSettingsIn,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> OkOut:
    """Auto-deploy on/off, or a hand-edited production layer (used from the next deploy)."""
    project = get_site(db, slug)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(project, field, value)
    db.commit()
    audit.record_request(
        db,
        request,
        action="site.update",
        outcome="ok",
        target=slug,
        params={k: (v if k != "override" else "changed") for k, v in changes.items()},
    )
    return OkOut()


@router.get("/projects/{slug}/env")
async def read_env(
    slug: str,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> EnvOut:
    """The site's .env, for the editor. Reading it is audited: it holds the secrets."""
    project = get_site(db, slug)
    result = await get_context(request).agent.call(
        "read_env",
        {
            "name": slug,
            "compose_file": project.compose_file,
            "env_file": project.env_file or ".env",
        },
    )
    audit.record_request(db, request, action="env.read", outcome="ok", target=slug)
    return EnvOut(content=result.get("content") or "", exists=bool(result.get("exists")))


@router.put("/projects/{slug}/env")
async def update_env(
    slug: str,
    body: EnvUpdateIn,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> DeployStartedOut:
    """Save the .env and rebuild, as a deployment. Only the key names are audited."""
    get_site(db, slug, state="active")
    if body.confirm != slug:
        raise bad_request(f"Confirmation required: send confirm={slug!r}")
    audit.record_request(
        db,
        request,
        action="env.update",
        outcome="ok",
        target=slug,
        params={"keys": env_keys(body.content)},
    )
    deployment_id = await get_context(request).deployer.start(
        slug, "env", user.username, env_content=body.content
    )
    return DeployStartedOut(deployment_id=deployment_id)


@router.post("/projects/{slug}/remove")
async def remove_site(
    slug: str,
    body: RemoveSiteIn,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> RemoveSiteOut:
    """Stop the site, remove its nginx site and certificate, optionally its data and files."""
    ctx = get_context(request)
    project = get_site(db, slug)
    if body.confirm != slug:
        raise bad_request(f"Confirmation required: send confirm={slug!r}")
    if user.totp_secret_enc is not None:
        step = totp.verify(
            ctx.secrets.open(user.totp_secret_enc),
            body.code or "",
            last_step=user.totp_last_step,
            now=ctx.clock(),
        )
        if step is None:
            raise bad_request("Enter a current code from your authenticator app")
        user.totp_last_step = step
        db.commit()
    if ctx.deployer.busy(slug):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{slug} is deploying")

    log: list[str] = []
    params = {"delete_files": body.delete_files, "delete_volumes": body.delete_volumes}
    async with audit.audited(db, request, action="site.remove", target=slug, params=params):
        if project.compose_file:
            log.append("==> Stopping the containers")
            await ctx.agent.call(
                "down",
                {
                    "name": slug,
                    "compose_file": project.compose_file,
                    "volumes": body.delete_volumes,
                },
                on_log=log.append,
                timeout=300,
            )
        if project.domain:
            log.append("==> Removing the nginx site and certificate")
            await ctx.agent.call("nginx_remove", {"domain": project.domain}, on_log=log.append)
            await ctx.agent.call("cert_delete", {"domain": project.domain}, on_log=log.append)
        if body.delete_files:
            log.append("==> Deleting the project folder")
            await ctx.agent.call("discard", {"name": slug}, on_log=log.append)
        db.delete(project)
        db.commit()
    log.append("==> Removed")
    return RemoveSiteOut(log=log)
