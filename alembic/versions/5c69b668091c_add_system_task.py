"""add system task

Revision ID: 5c69b668091c
Revises: 9b9016b043d3
Create Date: 2026-08-14 22:49:07.145668

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '5c69b668091c'
down_revision: Union[str, None] = '9b9016b043d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("taskId", sa.String(), nullable=False),
        sa.Column("taskType", sa.String(), server_default="plugin", nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("subjectLabel", sa.String(), nullable=True),
        sa.Column("status", sa.String(), server_default="PENDING", nullable=False),
        sa.Column("step", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("backend", sa.String(), nullable=False),
        sa.Column("acknowledged", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("retryOfTaskId", sa.String(), nullable=True),
        sa.Column("logPath", sa.Text(), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("startedAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finishedAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("taskId", name="ux_system_tasks_task_id"),
    )


def downgrade() -> None:
    op.drop_table("system_tasks")
