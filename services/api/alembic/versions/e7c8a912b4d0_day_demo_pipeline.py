"""add continuous-day demo sessions and batches

Revision ID: e7c8a912b4d0
Revises: d9a2f18b6c41
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7c8a912b4d0"
down_revision: str | Sequence[str] | None = "d9a2f18b6c41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("recording", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "experience",
                sa.String(length=24),
                server_default="recording",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("requested_batch_count", sa.Integer(), server_default="1", nullable=False)
        )

    with op.batch_alter_table("recording", schema=None) as batch_op:
        batch_op.alter_column(
            "experience",
            existing_type=sa.String(length=24),
            existing_nullable=False,
            server_default=None,
        )
        batch_op.alter_column(
            "requested_batch_count",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default=None,
        )

    op.create_table(
        "day_session",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("recording_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("fixture_id", sa.String(length=96), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requested_batch_count", sa.Integer(), nullable=False),
        sa.Column("processed_batch_count", sa.Integer(), nullable=False),
        sa.Column("active_batch_index", sa.Integer(), nullable=True),
        sa.Column("current_stage", sa.String(length=48), nullable=False),
        sa.Column("watermark_ms", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("memory_state", sa.JSON(), nullable=False),
        sa.Column("change_log", sa.JSON(), nullable=False),
        sa.Column("ask_history", sa.JSON(), nullable=False),
        sa.Column("pipeline_version", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=96), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["recording_id"], ["recording.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_day_session_recording_id", "day_session", ["recording_id"], unique=True
    )
    op.create_index("ix_day_session_workspace_id", "day_session", ["workspace_id"])
    op.create_index("ix_day_session_status", "day_session", ["status"])

    op.create_table(
        "day_batch",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("day_session_id", sa.String(length=36), nullable=False),
        sa.Column("recording_id", sa.String(length=36), nullable=False),
        sa.Column("batch_index", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("blob_key", sa.String(length=512), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=48), nullable=False),
        sa.Column("source_payload", sa.JSON(), nullable=False),
        sa.Column("transcript", sa.JSON(), nullable=False),
        sa.Column("reconciliation", sa.JSON(), nullable=False),
        sa.Column("index_state", sa.JSON(), nullable=False),
        sa.Column("pending_changes", sa.JSON(), nullable=False),
        sa.Column("published_snapshot", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["day_session_id"], ["day_session.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recording_id"], ["recording.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("day_session_id", "batch_index", name="uq_day_batch_index"),
    )
    op.create_index("ix_day_batch_day_session_id", "day_batch", ["day_session_id"])
    op.create_index("ix_day_batch_recording_id", "day_batch", ["recording_id"])
    op.create_index("ix_day_batch_status", "day_batch", ["status"])


def downgrade() -> None:
    op.drop_index("ix_day_batch_status", table_name="day_batch")
    op.drop_index("ix_day_batch_recording_id", table_name="day_batch")
    op.drop_index("ix_day_batch_day_session_id", table_name="day_batch")
    op.drop_table("day_batch")
    op.drop_index("ix_day_session_status", table_name="day_session")
    op.drop_index("ix_day_session_workspace_id", table_name="day_session")
    op.drop_index("ix_day_session_recording_id", table_name="day_session")
    op.drop_table("day_session")
    with op.batch_alter_table("recording", schema=None) as batch_op:
        batch_op.drop_column("requested_batch_count")
        batch_op.drop_column("experience")
