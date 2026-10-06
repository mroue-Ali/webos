"""Joins registered projects (database) with live container state (Docker)."""

import asyncio
from collections import defaultdict
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from webos.docker_api import Container, ContainerDetails, DockerClient, DockerError
from webos.models import Project
from webos.schemas import (
    ContainerOut,
    DockerSummaryOut,
    OverviewOut,
    PortOut,
    ProjectOut,
    UnmanagedGroupOut,
)

Pair = tuple[Container, ContainerDetails]


async def load_containers(docker: DockerClient) -> list[Pair]:
    containers = await docker.list_containers()
    results = await asyncio.gather(
        *(docker.details(c.id) for c in containers), return_exceptions=True
    )
    pairs: list[Pair] = []
    for container, result in zip(containers, results, strict=True):
        if isinstance(result, DockerError):
            result = ContainerDetails()  # removed between list and inspect
        elif isinstance(result, BaseException):
            raise result
        pairs.append((container, result))
    return sorted(pairs, key=lambda pair: pair[0].name)


def warnings_for(container: Container, details: ContainerDetails) -> list[str]:
    warnings = []
    if any(port.public for port in container.ports):
        warnings.append("public_port")
    if container.state == "restarting":
        warnings.append("restarting")
    if container.health == "unhealthy":
        warnings.append("unhealthy")
    if container.state in ("exited", "dead") and details.exit_code not in (0, None):
        warnings.append("exited_error")
    if details.oom_killed:
        warnings.append("oom_killed")
    return warnings


def container_out(
    container: Container, details: ContainerDetails, *, manageable: bool
) -> ContainerOut:
    return ContainerOut(
        id=container.id,
        name=container.name,
        service=container.compose_service,
        image=container.image,
        state=container.state,
        status=container.status,
        health=container.health,
        ports=[
            PortOut(
                ip=p.ip,
                private_port=p.private_port,
                public_port=p.public_port,
                protocol=p.protocol,
                public=p.public,
            )
            for p in container.ports
        ],
        restart_count=details.restart_count,
        exit_code=details.exit_code,
        oom_killed=details.oom_killed,
        started_at=details.started_at,
        warnings=warnings_for(container, details),
        manageable=manageable,
    )


async def build_overview(
    docker: DockerClient,
    db: Session,
    *,
    self_project: str,
    busy: Callable[[str], bool] = lambda _slug: False,
) -> OverviewOut:
    version, pairs = await asyncio.gather(docker.version(), load_containers(docker))
    projects = db.scalars(select(Project).order_by(Project.slug)).all()

    groups: dict[str | None, list[Pair]] = defaultdict(list)
    for pair in pairs:
        groups[pair[0].compose_project].append(pair)

    project_outs = []
    for project in projects:
        is_self = project.compose_project == self_project
        project_outs.append(
            ProjectOut(
                slug=project.slug,
                display_name=project.display_name,
                compose_project=project.compose_project,
                working_dir=project.working_dir,
                domain=project.domain,
                port=project.port,
                repo_url=project.repo_url,
                created_at=project.created_at,
                is_self=is_self,
                containers=[
                    container_out(c, d, manageable=not is_self)
                    for c, d in groups.get(project.compose_project, [])
                ],
                managed=project.managed,
                state=project.state,
                branch=project.branch,
                compose_file=project.compose_file,
                env_file=project.env_file,
                web_service=project.web_service,
                container_port=project.container_port,
                aliases=project.alias_list,
                override=project.override,
                auto_deploy=project.auto_deploy,
                deployed_commit=project.deployed_commit,
                deploying=busy(project.slug),
            )
        )

    registered = {p.compose_project for p in projects}
    unmanaged = [
        UnmanagedGroupOut(
            compose_project=name,
            working_dir=next((c.working_dir for c, _ in items if c.working_dir), None),
            is_self=name == self_project,
            containers=[container_out(c, d, manageable=False) for c, d in items],
        )
        for name, items in sorted(groups.items(), key=lambda kv: (kv[0] is None, kv[0] or ""))
        if name not in registered
    ]

    return OverviewOut(
        docker=DockerSummaryOut(
            version=str(version.get("Version", "unknown")),
            running=sum(1 for c, _ in pairs if c.state == "running"),
            total=len(pairs),
        ),
        projects=project_outs,
        unmanaged=unmanaged,
    )
