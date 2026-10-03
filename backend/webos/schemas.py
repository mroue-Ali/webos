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


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)
    code: str = Field(min_length=6, max_length=12)


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
