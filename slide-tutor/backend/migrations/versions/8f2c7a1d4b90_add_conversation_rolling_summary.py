"""add conversation rolling summary

Revision ID: 8f2c7a1d4b90
Revises: 63588f9af7ab
Create Date: 2026-07-31 10:15:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8f2c7a1d4b90"
down_revision: str | Sequence[str] | None = "63588f9af7ab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("conversations", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "summary_text",
                sa.Text(),
                server_default=sa.text("''"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "summary_turn_count",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("summary_updated_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("conversations", schema=None) as batch_op:
        batch_op.drop_column("summary_updated_at")
        batch_op.drop_column("summary_turn_count")
        batch_op.drop_column("summary_text")
