"""add protocol input refs

Revision ID: 2fc2cd4da2e2
Revises: 33ffae69565b
Create Date: 2026-06-22 12:06:28.813389

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2fc2cd4da2e2'
down_revision: Union[str, None] = '33ffae69565b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "protocol_input_refs",
        sa.Column("projectId", sa.Integer(), nullable=False),
        sa.Column("protocolDbId", sa.Integer(), nullable=False),
        sa.Column("protocolId", sa.Text(), nullable=False),
        sa.Column("inputName", sa.Text(), nullable=False),
        sa.Column("itemIndex", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parentProtocolDbId", sa.Integer(), nullable=True),
        sa.Column("parentProtocolId", sa.Text(), nullable=True),
        sa.Column("parentOutputName", sa.Text(), nullable=True),
        sa.Column("objectClassName", sa.Text(), nullable=True),
        sa.Column("objectId", sa.Text(), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint(
            "projectId",
            "protocolDbId",
            "inputName",
            "itemIndex",
            name="protocol_input_refs_pkey",
        ),
        sa.ForeignKeyConstraint(
            ["projectId"],
            ["projects.id"],
            name="protocol_input_refs_projectId_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["projectId", "protocolDbId"],
            ["protocols.projectId", "protocols.id"],
            name="protocol_input_refs_protocolDbId_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["projectId", "parentProtocolDbId"],
            ["protocols.projectId", "protocols.id"],
            name="protocol_input_refs_parentProtocolDbId_fkey",
            ondelete="CASCADE",
        ),
    )

    op.create_index(
        "idx_protocol_input_refs_protocol",
        "protocol_input_refs",
        ["projectId", "protocolDbId"],
        unique=False,
    )

    op.create_index(
        "idx_protocol_input_refs_parent",
        "protocol_input_refs",
        ["projectId", "parentProtocolDbId", "parentOutputName"],
        unique=False,
    )

    op.create_index(
        "idx_protocol_input_refs_parent_protocol_id",
        "protocol_input_refs",
        ["projectId", "parentProtocolId", "parentOutputName"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_protocol_input_refs_parent_protocol_id", table_name="protocol_input_refs")
    op.drop_index("idx_protocol_input_refs_parent", table_name="protocol_input_refs")
    op.drop_index("idx_protocol_input_refs_protocol", table_name="protocol_input_refs")
    op.drop_table("protocol_input_refs")
