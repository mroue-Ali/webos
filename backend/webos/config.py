"""Runtime settings, read from WEBOS_* environment variables or a .env file in the cwd."""

from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WEBOS_", env_file=".env", extra="ignore")

    # Signs session cookies and encrypts the TOTP secret. Changing it logs everyone out
    # and makes the stored TOTP secret unreadable (run `webos-admin enable-totp` again).
    secret_key: SecretStr = Field(min_length=32)

    database_url: str = "sqlite:///./data/webos.db"
    docker_url: str = "http://socket-proxy:2375"

    # Exact origins the panel is opened at. Every state-changing request must come from one.
    allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:9000"]

    # Only turn off for plain-HTTP setups that are not localhost (browsers already accept
    # Secure cookies on http://localhost).
    cookie_secure: bool = True
    session_idle_minutes: int = Field(default=30, ge=1)
    session_max_hours: int = Field(default=12, ge=1)

    # Compose project name of webos itself; the panel refuses to stop or restart it.
    self_project: str = "webos"

    # Proxies whose X-Forwarded-For uvicorn trusts (comma-separated IPs, or "*").
    forwarded_allow_ips: str = "127.0.0.1"

    # Server stats. /proc in a container already shows the host's CPU, memory and load;
    # network counters need the host's /proc/1/net/dev mounted read-only (compose does it).
    proc_root: Path = Path("/proc")
    host_net_dev: Path | None = Path("/host/net_dev")
    # Disk usage is reported for the filesystem holding this path (the data bind mount).
    disk_path: Path = Path("/data")
    metrics_interval_seconds: float = Field(default=5.0, gt=0)

    static_dir: Path | None = None
    debug: bool = False

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [o.strip().rstrip("/") for o in value.split(",") if o.strip()]
        return value
