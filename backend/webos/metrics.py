"""Server resource usage: host CPU, memory, disk and network, plus per-container usage.

Inside a container, /proc already reports the host kernel's CPU, memory, load and uptime,
and the disk under /data is the host filesystem it is bind-mounted from. Network counters
are per namespace, so the host's come from a read-only mount of the host's
/proc/1/net/dev (see docker-compose.yml). Nothing here writes anything.

Recent history lives in memory only (a few hundred points); live state never goes into the
database.
"""

import asyncio
import shutil
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, TypeVar

from webos.docker_api import DockerClient, DockerError

# Interfaces that only carry container-internal traffic; host totals would double-count.
_VIRTUAL_PREFIXES = ("lo", "docker", "br-", "veth", "virbr", "tailscale", "tun", "wg")

T = TypeVar("T")


@dataclass(frozen=True)
class Interface:
    name: str
    rx_bytes: int
    tx_bytes: int
    rx_rate: float | None
    tx_rate: float | None


@dataclass(frozen=True)
class HostSample:
    ts: float
    cpu_percent: float | None
    load: tuple[float, float, float] | None
    uptime_seconds: float | None
    mem_total: int | None
    mem_available: int | None
    swap_total: int | None
    swap_free: int | None
    disk_total: int | None
    disk_used: int | None
    disk_free: int | None
    interfaces: tuple[Interface, ...] | None

    @property
    def mem_percent(self) -> float | None:
        if not self.mem_total or self.mem_available is None:
            return None
        return 100 * (self.mem_total - self.mem_available) / self.mem_total

    def total_rate(self, attr: str) -> float | None:
        if not self.interfaces:
            return None
        rates = [getattr(i, attr) for i in self.interfaces]
        return None if any(r is None for r in rates) else sum(rates)


@dataclass(frozen=True)
class ContainerUsage:
    id: str
    name: str
    project: str | None
    cpu_percent: float  # share of the whole machine, 0-100
    memory_used: int
    memory_limit: int
    net_rx: int
    net_tx: int


@dataclass(frozen=True)
class DockerDisk:
    images: int
    images_reclaimable: int
    containers: int
    volumes: int
    build_cache: int
    build_cache_reclaimable: int


def read_cpu_times(proc: Path) -> tuple[int, int] | None:
    """(total, idle) jiffies from the aggregate `cpu` line of /proc/stat."""
    try:
        first = (proc / "stat").read_text().splitlines()[0].split()
    except (OSError, IndexError):
        return None
    if first[0] != "cpu":
        return None
    # user nice system idle iowait irq softirq steal (guest time is already in user)
    values = [int(v) for v in first[1:9]]
    return sum(values), values[3] + values[4]


def read_meminfo(proc: Path) -> dict[str, int]:
    """Values in bytes, keyed like the file (MemTotal, MemAvailable, SwapTotal, SwapFree)."""
    result = {}
    try:
        for line in (proc / "meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            parts = rest.split()
            if parts and parts[0].isdigit():
                result[key] = int(parts[0]) * 1024
    except OSError:
        pass
    return result


def read_loadavg(proc: Path) -> tuple[float, float, float] | None:
    try:
        one, five, fifteen = (proc / "loadavg").read_text().split()[:3]
        return float(one), float(five), float(fifteen)
    except (OSError, ValueError):
        return None


def read_uptime(proc: Path) -> float | None:
    try:
        return float((proc / "uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def read_net_dev(path: Path | None) -> dict[str, tuple[int, int]] | None:
    """{interface: (rx_bytes, tx_bytes)} for physical-looking interfaces."""
    if path is None:
        return None
    try:
        lines = path.read_text().splitlines()[2:]
    except OSError:
        return None
    result = {}
    for line in lines:
        name, _, rest = line.partition(":")
        name = name.strip()
        fields = rest.split()
        if len(fields) >= 9 and not name.startswith(_VIRTUAL_PREFIXES):
            result[name] = (int(fields[0]), int(fields[8]))
    return result


def read_disk(path: Path) -> tuple[int, int, int] | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return usage.total, usage.used, usage.free


class HostSampler:
    """Samples the host every `interval` seconds and keeps a short in-memory history."""

    def __init__(
        self,
        *,
        proc_root: Path,
        net_dev: Path | None,
        disk_path: Path,
        interval: float = 5.0,
        history_points: int = 360,  # 30 minutes at 5 s
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.proc_root = proc_root
        self.net_dev = net_dev
        self.disk_path = disk_path
        self.interval = interval
        self.clock = clock
        self.history: deque[HostSample] = deque(maxlen=history_points)
        self._last_cpu: tuple[int, int] | None = None
        self._last_net: tuple[float, dict[str, tuple[int, int]]] | None = None

    @property
    def latest(self) -> HostSample | None:
        return self.history[-1] if self.history else None

    def sample(self) -> HostSample:
        now = self.clock()

        cpu_percent = None
        cpu = read_cpu_times(self.proc_root)
        if cpu and self._last_cpu:
            total = cpu[0] - self._last_cpu[0]
            idle = cpu[1] - self._last_cpu[1]
            if total > 0:
                cpu_percent = max(0.0, min(100.0, 100 * (total - idle) / total))
        self._last_cpu = cpu or self._last_cpu

        interfaces = None
        counters = read_net_dev(self.net_dev)
        if counters is not None:
            previous = self._last_net
            elapsed = now - previous[0] if previous else 0.0
            items = []
            for name, (rx, tx) in sorted(counters.items()):
                before = previous[1].get(name) if previous else None
                ok = before is not None and elapsed > 0 and rx >= before[0] and tx >= before[1]
                items.append(
                    Interface(
                        name=name,
                        rx_bytes=rx,
                        tx_bytes=tx,
                        rx_rate=(rx - before[0]) / elapsed if ok and before else None,
                        tx_rate=(tx - before[1]) / elapsed if ok and before else None,
                    )
                )
            interfaces = tuple(items)
            self._last_net = (now, counters)

        mem = read_meminfo(self.proc_root)
        disk = read_disk(self.disk_path)
        sample = HostSample(
            ts=now,
            cpu_percent=cpu_percent,
            load=read_loadavg(self.proc_root),
            uptime_seconds=read_uptime(self.proc_root),
            mem_total=mem.get("MemTotal"),
            mem_available=mem.get("MemAvailable"),
            swap_total=mem.get("SwapTotal"),
            swap_free=mem.get("SwapFree"),
            disk_total=disk[0] if disk else None,
            disk_used=disk[1] if disk else None,
            disk_free=disk[2] if disk else None,
            interfaces=interfaces,
        )
        self.history.append(sample)
        return sample

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            self.sample()


@dataclass
class TtlCache(Generic[T]):
    """Fetches on demand, at most once per `ttl` seconds, shared by concurrent callers."""

    ttl: float
    fetch: Callable[[], Awaitable[T]]
    clock: Callable[[], float] = time.monotonic
    _value: T | None = None
    _fetched_at: float = float("-inf")
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def get(self) -> T:
        async with self._lock:
            if self._value is None or self.clock() - self._fetched_at >= self.ttl:
                self._value = await self.fetch()
                self._fetched_at = self.clock()
            return self._value


def parse_container_stats(raw: dict[str, Any]) -> tuple[float, int, int, int, int]:
    """(cpu %, memory used, memory limit, net rx, net tx) from one Docker stats reading."""
    cpu = raw.get("cpu_stats") or {}
    pre = raw.get("precpu_stats") or {}
    cpu_delta = (cpu.get("cpu_usage") or {}).get("total_usage", 0) - (
        pre.get("cpu_usage") or {}
    ).get("total_usage", 0)
    system_delta = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
    # system_cpu_usage counts every core, so this is the share of the whole machine.
    cpu_percent = 100 * cpu_delta / system_delta if system_delta > 0 and cpu_delta > 0 else 0.0

    memory = raw.get("memory_stats") or {}
    stats = memory.get("stats") or {}
    # Like `docker stats`: page cache the kernel can drop doesn't count as used.
    cache = stats.get("inactive_file", stats.get("total_inactive_file", 0))
    used = max(int(memory.get("usage", 0)) - int(cache), 0)

    networks = (raw.get("networks") or {}).values()
    rx = sum(int(n.get("rx_bytes", 0)) for n in networks)
    tx = sum(int(n.get("tx_bytes", 0)) for n in networks)
    return min(cpu_percent, 100.0), used, int(memory.get("limit", 0)), rx, tx


def summarize_df(raw: dict[str, Any]) -> DockerDisk:
    images = raw.get("Images") or []
    build = raw.get("BuildCache") or []
    return DockerDisk(
        images=int(raw.get("LayersSize") or 0),
        images_reclaimable=sum(
            int(i.get("Size") or 0) - max(int(i.get("SharedSize") or 0), 0)
            for i in images
            if not i.get("Containers")
        ),
        containers=sum(int(c.get("SizeRw") or 0) for c in raw.get("Containers") or []),
        volumes=sum(
            max(int((v.get("UsageData") or {}).get("Size") or 0), 0)
            for v in raw.get("Volumes") or []
        ),
        build_cache=sum(int(b.get("Size") or 0) for b in build),
        build_cache_reclaimable=sum(int(b.get("Size") or 0) for b in build if not b.get("InUse")),
    )


class ServerMetrics:
    """Host sampler plus on-demand, cached Docker readings."""

    def __init__(self, docker: DockerClient, sampler: HostSampler) -> None:
        self.docker = docker
        self.sampler = sampler
        self.info: TtlCache[dict[str, Any]] = TtlCache(300, docker.info)
        # `docker system df` walks every image and volume, so refresh it rarely.
        self.disk: TtlCache[DockerDisk] = TtlCache(60, self._docker_disk)
        self.containers: TtlCache[list[ContainerUsage]] = TtlCache(10, self._container_usage)

    async def _docker_disk(self) -> DockerDisk:
        return summarize_df(await self.docker.system_df())

    async def _container_usage(self) -> list[ContainerUsage]:
        running = [c for c in await self.docker.list_containers() if c.state == "running"]
        results = await asyncio.gather(
            *(self.docker.stats(c.id) for c in running), return_exceptions=True
        )
        usage = []
        for container, result in zip(running, results, strict=True):
            if isinstance(result, DockerError):
                continue  # stopped between list and stats
            if isinstance(result, BaseException):
                raise result
            cpu, used, limit, rx, tx = parse_container_stats(result)
            usage.append(
                ContainerUsage(
                    id=container.id,
                    name=container.name,
                    project=container.compose_project,
                    cpu_percent=cpu,
                    memory_used=used,
                    memory_limit=limit,
                    net_rx=rx,
                    net_tx=tx,
                )
            )
        return usage
