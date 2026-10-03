"""2FA becomes optional: users.totp_secret_enc may be NULL.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.alter_column("totp_secret_enc", existing_type=sa.String(255), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.alter_column("totp_secret_enc", existing_type=sa.String(255), nullable=False)
