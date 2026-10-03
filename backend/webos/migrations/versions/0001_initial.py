"""Initial schema: users, projects, append-only audit log.

Revision ID: 0001
Revises:
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("totp_secret_enc", sa.String(255), nullable=False),
        sa.Column("totp_last_step", sa.Integer(), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("password_changed_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(40), nullable=False, unique=True),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("compose_project", sa.String(64), nullable=False, unique=True),
        sa.Column("working_dir", sa.String(255), nullable=True),
        sa.Column("domain", sa.String(253), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True, unique=True),
        sa.Column("repo_url", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("request_id", sa.String(32), nullable=True),
        sa.Column("actor", sa.String(64), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target", sa.String(255), nullable=True),
        sa.Column("params", sa.Text(), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
    )
    op.create_index("ix_audit_events_ts", "audit_events", ["ts"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])

    # The audit log is append-only. This stops bugs and mistakes, not root on the host.
    for verb in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER audit_events_no_{verb.lower()} BEFORE {verb} ON audit_events "
            "BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END"
        )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_update")
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_delete")
    op.drop_table("audit_events")
    op.drop_table("projects")
    op.drop_table("users")
