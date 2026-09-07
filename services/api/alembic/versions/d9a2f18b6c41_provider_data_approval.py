"""persist remote-provider data approval

Revision ID: d9a2f18b6c41
Revises: c14c172f08b5
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d9a2f18b6c41"
down_revision: str | Sequence[str] | None = "c14c172f08b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("recording", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "provider_data_approved",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )
    op.execute(
        sa.text(
            "UPDATE recording SET provider_data_approved = true "
            "WHERE source_kind = 'approved_fixture'"
        )
    )
    with op.batch_alter_table("recording", schema=None) as batch_op:
        batch_op.alter_column(
            "provider_data_approved",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=None,
        )


def downgrade() -> None:
    with op.batch_alter_table("recording", schema=None) as batch_op:
        batch_op.drop_column("provider_data_approved")
