"""The database holds only configuration and history. Live server state is never stored here."""

from datetime import UTC, datetime

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Naive UTC: SQLite has no time zones, so every timestamp in the database is UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    """The single panel user."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    totp_secret_enc: Mapped[str] = mapped_column(String(255))
    # Last accepted TOTP time step; codes at or before it are rejected as replays.
    totp_last_step: Mapped[int] = mapped_column(default=0)
    # Embedded in every session cookie; bumping it ends all sessions.
    session_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    password_changed_at: Mapped[datetime] = mapped_column(default=utcnow)


class Project(Base):
    """A compose stack registered with the panel."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    display_name: Mapped[str] = mapped_column(String(80))
    compose_project: Mapped[str] = mapped_column(String(64), unique=True)
    working_dir: Mapped[str | None] = mapped_column(String(255))
    domain: Mapped[str | None] = mapped_column(String(253))
    # Assigned loopback port (the registry), not whatever happens to be bound right now.
    port: Mapped[int | None] = mapped_column(unique=True)
    repo_url: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditEvent(Base):
    """Append-only: triggers created in the initial migration abort any UPDATE or DELETE."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_action", "action"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    request_id: Mapped[str | None] = mapped_column(String(32))
    actor: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(255))
    params: Mapped[str] = mapped_column(Text, default="{}")
    outcome: Mapped[str] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(String(500))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
