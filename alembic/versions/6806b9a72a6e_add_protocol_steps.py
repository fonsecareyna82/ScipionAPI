"""add protocol steps

Revision ID: 6806b9a72a6e
Revises: 9b7b3c4d8e21
Create Date: 2026-06-17 17:40:02.063195

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6806b9a72a6e'
down_revision: Union[str, None] = '9b7b3c4d8e21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "protocol_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("projectId", sa.Integer(), nullable=False),
        sa.Column("protocolDbId", sa.Integer(), nullable=False),
        sa.Column("protocolId", sa.String(), nullable=False),
        sa.Column("stepIndex", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("prerequisites", sa.dialects.postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("args", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("initTime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("endTime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("elapsedSeconds", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("interactive", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("needsGpu", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("event", sa.Text(), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["projectId"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["protocolDbId"], ["protocols.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("projectId", "protocolDbId", "stepIndex", name="ux_protocol_steps_project_protocol_step"),
    )
    op.create_index("idx_protocol_steps_protocol", "protocol_steps", ["projectId", "protocolDbId", "stepIndex"])
    op.create_index("idx_protocol_steps_protocol_id", "protocol_steps", ["projectId", "protocolId"])


def downgrade() -> None:
    op.drop_index("idx_protocol_steps_protocol_id", table_name="protocol_steps")
    op.drop_index("idx_protocol_steps_protocol", table_name="protocol_steps")
    op.drop_table("protocol_steps")
