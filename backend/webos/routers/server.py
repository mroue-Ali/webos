import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Request

from webos.context import get_context
from webos.docker_api import DockerError
from webos.metrics import TtlCache
from webos.models import User
from webos.schemas import (
    ContainerUsageOut,
    CpuOut,
    DiskOut,
    DockerDiskOut,
    HistoryOut,
    HostInfoOut,
    InterfaceOut,
    MemoryOut,
    ServerOut,
)
from webos.security.auth import require_user

router = APIRouter(prefix="/api", tags=["server"])
logger = logging.getLogger(__name__)


async def _optional(cache: TtlCache[Any]) -> Any:
    """A Docker reading that may fail without taking the whole page down."""
    try:
        return await cache.get()
    except DockerError as exc:
        logger.warning("server stats: %s", exc.message)
        return None


@router.get("/server")
async def server(request: Request, user: User = Depends(require_user)) -> ServerOut:
    """Host resources and per-container usage. Read-only; nothing here changes anything."""
    metrics = get_context(request).metrics
    sampler = metrics.sampler
    latest = sampler.latest or sampler.sample()
    info = await _optional(metrics.info) or {}
    docker_disk = await _optional(metrics.disk)
    usage = await _optional(metrics.containers) or []

    memory = None
    if latest.mem_total and latest.mem_available is not None:
        swap_used = (
            latest.swap_total - latest.swap_free
            if latest.swap_total is not None and latest.swap_free is not None
            else None
        )
        memory = MemoryOut(
            total=latest.mem_total,
            used=latest.mem_total - latest.mem_available,
            available=latest.mem_available,
            swap_total=latest.swap_total,
            swap_used=swap_used,
        )

    history = list(sampler.history)
    return ServerOut(
        host=HostInfoOut(
            hostname=info.get("Name"),
            os=info.get("OperatingSystem"),
            kernel=info.get("KernelVersion"),
            cpus=info.get("NCPU"),
            docker_version=info.get("ServerVersion"),
            uptime_seconds=latest.uptime_seconds,
        ),
        cpu=CpuOut(
            percent=latest.cpu_percent,
            load=list(latest.load) if latest.load else None,
        ),
        memory=memory,
        disk=(
            DiskOut(total=latest.disk_total, used=latest.disk_used, free=latest.disk_free)
            if latest.disk_total is not None
            and latest.disk_used is not None
            and latest.disk_free is not None
            else None
        ),
        docker_disk=DockerDiskOut(**asdict(docker_disk)) if docker_disk else None,
        network=(
            [InterfaceOut(**asdict(i)) for i in latest.interfaces]
            if latest.interfaces is not None
            else None
        ),
        history=HistoryOut(
            interval_seconds=sampler.interval,
            ts=[s.ts for s in history],
            cpu=[s.cpu_percent for s in history],
            memory=[s.mem_percent for s in history],
            rx=[s.total_rate("rx_rate") for s in history],
            tx=[s.total_rate("tx_rate") for s in history],
        ),
        containers=[
            ContainerUsageOut(**asdict(u))
            for u in sorted(usage, key=lambda u: u.memory_used, reverse=True)
        ],
    )
