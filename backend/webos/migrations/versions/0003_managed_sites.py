"""Managed sites (the new-site wizard) and deployment history.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(
            sa.Column("managed", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("state", sa.String(16), nullable=False, server_default="active"))
        batch.add_column(sa.Column("branch", sa.String(100), nullable=True))
        batch.add_column(sa.Column("compose_file", sa.String(200), nullable=True))
        batch.add_column(sa.Column("env_file", sa.String(200), nullable=True))
        batch.add_column(sa.Column("web_service", sa.String(64), nullable=True))
        batch.add_column(sa.Column("container_port", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("aliases", sa.String(600), nullable=True))
        batch.add_column(sa.Column("override", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("auto_deploy", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("deployed_commit", sa.String(64), nullable=True))

    op.create_table(
        "deployments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("commit", sa.String(64), nullable=True),
        sa.Column("subject", sa.String(200), nullable=True),
        sa.Column("actor", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("log", sa.Text(), nullable=False),
    )
    op.create_index("ix_deployments_project_id", "deployments", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_deployments_project_id", "deployments")
    op.drop_table("deployments")
    with op.batch_alter_table("projects") as batch:
        for column in (
            "deployed_commit",
            "auto_deploy",
            "override",
            "aliases",
            "container_port",
            "web_service",
            "env_file",
            "compose_file",
            "branch",
            "state",
            "managed",
        ):
            batch.drop_column(column)
