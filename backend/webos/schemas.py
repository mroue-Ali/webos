"""The API contract. frontend/src/api/types.ts mirrors these."""

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

# Naive UTC from the database, sent with a Z so browsers don't read it as local time.
UtcDatetime = Annotated[
    datetime,
    PlainSerializer(lambda d: d.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")),
]

SLUG = r"^[a-z0-9][a-z0-9-]{0,39}$"
COMPOSE_PROJECT = r"^[a-z0-9][a-z0-9_-]{0,63}$"
# Pydantic's regex engine has no look-around; length is capped by max_length instead.
DOMAIN = r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
REPO_URL = r"^(https://|git@)[A-Za-z0-9._@:/~-]+$"
# Same rules the host agent enforces (agent/webos_agent.py).
REPO = (
    r"^(https://[A-Za-z0-9.-]+(:[0-9]+)?/[A-Za-z0-9._~/-]+|git@[A-Za-z0-9.-]+:[A-Za-z0-9._~/-]+)$"
)
BRANCH = r"^[A-Za-z0-9._][A-Za-z0-9._/-]{0,99}$"
REL_PATH = r"^[A-Za-z0-9._-][A-Za-z0-9._/-]{0,199}$"
SERVICE = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"
MAX_TEXT = 65536


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)
    code: str | None = Field(default=None, max_length=12)  # only when 2FA is on


class LoginOut(BaseModel):
    """Either signed in (username), or the password was right and a 2FA code is needed."""

    username: str | None = None
    code_required: bool = False


class MeOut(BaseModel):
    username: str


class PortOut(BaseModel):
    ip: str
    private_port: int
    public_port: int | None
    protocol: str
    public: bool


class ContainerOut(BaseModel):
    id: str
    name: str
    service: str | None
    image: str
    state: str
    status: str
    health: str | None
    ports: list[PortOut]
    restart_count: int
    exit_code: int | None
    oom_killed: bool
    started_at: str | None
    warnings: list[str]
    manageable: bool


class ProjectOut(BaseModel):
    slug: str
    display_name: str
    compose_project: str
    working_dir: str | None
    domain: str | None
    port: int | None
    repo_url: str | None
    created_at: UtcDatetime
    is_self: bool
    containers: list[ContainerOut]
    # Set for sites webos deployed itself.
    managed: bool = False
    state: str = "active"
    branch: str | None = None
    compose_file: str | None = None
    env_file: str | None = None
    web_service: str | None = None
    container_port: int | None = None
    aliases: list[str] = []
    override: str | None = None
    auto_deploy: bool = False
    deployed_commit: str | None = None
    deploying: bool = False


class UnmanagedGroupOut(BaseModel):
    compose_project: str | None  # None: containers started without compose
    working_dir: str | None
    is_self: bool
    containers: list[ContainerOut]


class DockerSummaryOut(BaseModel):
    version: str
    running: int
    total: int


class OverviewOut(BaseModel):
    docker: DockerSummaryOut
    projects: list[ProjectOut]
    unmanaged: list[UnmanagedGroupOut]


class ProjectImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    compose_project: str = Field(pattern=COMPOSE_PROJECT)
    slug: str | None = Field(default=None, pattern=SLUG)
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    domain: str | None = Field(default=None, max_length=253, pattern=DOMAIN)


class ProjectUpdateIn(BaseModel):
    """PATCH: only the fields sent are changed; send null to clear one."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    domain: str | None = Field(default=None, max_length=253, pattern=DOMAIN)
    repo_url: str | None = Field(default=None, max_length=300, pattern=REPO_URL)
    port: int | None = Field(default=None, ge=1024, le=65535)


class ConfirmIn(BaseModel):
    """Disruptive actions must name their target, so even a raw API call states intent."""

    confirm: str | None = Field(default=None, max_length=128)


class OkOut(BaseModel):
    ok: bool = True


class AuditEventOut(BaseModel):
    id: int
    ts: UtcDatetime
    request_id: str | None
    actor: str | None
    action: str
    target: str | None
    params: dict[str, Any]
    outcome: str
    error: str | None
    ip: str | None
    user_agent: str | None


class AuditPageOut(BaseModel):
    items: list[AuditEventOut]
    next_before: int | None


class HostInfoOut(BaseModel):
    hostname: str | None
    os: str | None
    kernel: str | None
    cpus: int | None
    docker_version: str | None
    uptime_seconds: float | None


class CpuOut(BaseModel):
    percent: float | None  # None until two samples exist
    load: list[float] | None  # 1, 5, 15 minutes


class MemoryOut(BaseModel):
    total: int
    used: int
    available: int
    swap_total: int | None
    swap_used: int | None


class DiskOut(BaseModel):
    total: int
    used: int
    free: int


class DockerDiskOut(BaseModel):
    images: int
    images_reclaimable: int
    containers: int
    volumes: int
    build_cache: int
    build_cache_reclaimable: int


class InterfaceOut(BaseModel):
    name: str
    rx_bytes: int
    tx_bytes: int
    rx_rate: float | None  # bytes per second
    tx_rate: float | None


class HistoryOut(BaseModel):
    """Recent samples, oldest first. Kept in memory only; restarts start it afresh."""

    interval_seconds: float
    ts: list[float]
    cpu: list[float | None]
    memory: list[float | None]  # percent used
    rx: list[float | None]  # bytes per second, all interfaces
    tx: list[float | None]


class ContainerUsageOut(BaseModel):
    id: str
    name: str
    project: str | None
    cpu_percent: float  # share of the whole machine
    memory_used: int
    memory_limit: int
    net_rx: int
    net_tx: int


class ServerOut(BaseModel):
    host: HostInfoOut
    cpu: CpuOut
    memory: MemoryOut | None
    disk: DiskOut | None
    docker_disk: DockerDiskOut | None
    network: list[InterfaceOut] | None  # None when the host counters aren't mounted
    history: HistoryOut
    containers: list[ContainerUsageOut]


# --- new-site wizard and deployments ---------------------------------------------------------


class AgentStatusOut(BaseModel):
    available: bool
    error: str | None = None
    version: str | None = None
    apps_root: str | None = None
    user: str | None = None
    host_ips: list[str] = []
    compose_version: str | None = None
    nginx: bool | None = None
    certbot: bool | None = None


class SiteNameIn(BaseModel):
    name: str = Field(pattern=SLUG)


class DeployKeyOut(BaseModel):
    public_key: str


class SiteCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=SLUG)
    repo: str = Field(max_length=300, pattern=REPO)
    branch: str = Field(default="main", pattern=BRANCH)


class SiteCreatedOut(BaseModel):
    slug: str
    commit: str
    subject: str
    compose_files: list[str]


class ServiceChoiceIn(BaseModel):
    keep_volumes: list[str] | None = Field(default=None, max_length=50)
    use_image_command: bool = False


class SiteConfigIn(BaseModel):
    compose_file: str = Field(pattern=REL_PATH)
    env_file: str = Field(default=".env", pattern=REL_PATH)
    web_service: str = Field(pattern=SERVICE)
    container_port: int = Field(ge=1, le=65535)
    services: dict[str, ServiceChoiceIn] = Field(default_factory=dict, max_length=50)


class SiteInspectOut(BaseModel):
    compose_file: str
    services: dict[str, Any]
    violations: list[str]
    env_example: str
    suggestion: dict[str, Any]
    port: int
    domain_suggestion: str | None
    server_ips: list[str]


class SitePreviewOut(BaseModel):
    override: str
    port: int
    violations: list[str]
    services: dict[str, Any]


class SiteDeployIn(SiteConfigIn):
    model_config = ConfigDict(extra="forbid")

    domain: str = Field(max_length=253, pattern=DOMAIN)
    aliases: list[Annotated[str, Field(max_length=253, pattern=DOMAIN)]] = Field(
        default_factory=list, max_length=5
    )
    override: str = Field(min_length=1, max_length=MAX_TEXT)
    env: str = Field(default="", max_length=MAX_TEXT)
    auto_deploy: bool = False


class DomainCheckOut(BaseModel):
    domain: str
    resolves_to: list[str]
    server_ips: list[str]
    ok: bool


class DeployStartedOut(BaseModel):
    deployment_id: int


class DeploymentOut(BaseModel):
    id: int
    trigger: str
    status: str
    commit: str | None
    subject: str | None
    actor: str | None
    started_at: UtcDatetime
    finished_at: UtcDatetime | None
    error: str | None


class DeploymentDetailOut(DeploymentOut):
    project: str
    log: str


class EnvOut(BaseModel):
    content: str
    exists: bool


class EnvUpdateIn(BaseModel):
    content: str = Field(max_length=MAX_TEXT)
    confirm: str | None = Field(default=None, max_length=128)


class SiteSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_deploy: bool | None = None
    override: str | None = Field(default=None, min_length=1, max_length=MAX_TEXT)


class RemoveSiteIn(BaseModel):
    confirm: str | None = Field(default=None, max_length=128)
    delete_files: bool = False
    delete_volumes: bool = False
    code: str | None = Field(default=None, max_length=12)  # required when 2FA is on


class RemoveSiteOut(BaseModel):
    log: list[str]
