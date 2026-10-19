"""Keep the parameters of every protocol launch.

Each launch (and restart, continue or schedule) stores the parameters the
protocol had and who launched it, so earlier runs can be told apart and
compared after their parameters changed.

Revision ID: 4e8b1d2c7a55
Revises: 7a1c2e9d4f30
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "4e8b1d2c7a55"
down_revision = "7a1c2e9d4f30"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "protocol_launches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("projectId", sa.Integer(), nullable=False),
        sa.Column("protocolDbId", sa.Integer(), nullable=False),
        sa.Column("protocolId", sa.String(), nullable=False),
        sa.Column("userId", sa.Integer(), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("launchedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["projectId"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["protocolDbId"], ["protocols.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["userId"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_protocol_launches_id"), "protocol_launches", ["id"])
    op.create_index("idx_protocol_launches_protocol", "protocol_launches", ["protocolDbId", "launchedAt"])
    op.create_index("idx_protocol_launches_project", "protocol_launches", ["projectId"])


def downgrade():
    op.drop_index("idx_protocol_launches_project", table_name="protocol_launches")
    op.drop_index("idx_protocol_launches_protocol", table_name="protocol_launches")
    op.drop_index(op.f("ix_protocol_launches_id"), table_name="protocol_launches")
    op.drop_table("protocol_launches")
