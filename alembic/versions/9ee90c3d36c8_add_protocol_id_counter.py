"""add protocol id counter

Revision ID: 9ee90c3d36c8
Revises: 6c351e5b4cd9
Create Date: 2026-07-17 17:44:59.797511

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9ee90c3d36c8'
down_revision: Union[str, None] = '6c351e5b4cd9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "project_object_id_counters",
        sa.Column(
            "nextProtocolId",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("2"),
        ),
    )

    op.alter_column(
        "project_object_id_counters",
        "nextObjectId",
        existing_type=sa.Integer(),
        server_default=sa.text("1000000"),
        existing_nullable=False,
    )

    op.execute(
        """
        UPDATE project_object_id_counters counters
           SET "nextProtocolId" = GREATEST(
               2,
               COALESCE(
                   (
                       SELECT MAX(
                           (protocols."protocolId")::integer
                       ) + 1
                         FROM protocols
                        WHERE protocols."projectId" =
                              counters."projectId"
                          AND protocols."protocolId"
                              ~ '^[0-9]+$'
                   ),
                   2
               )
           )
        """
    )

    op.execute(
        """
        UPDATE project_object_id_counters
           SET "nextObjectId" = GREATEST(
               "nextObjectId",
               1000000
           )
        """
    )


def downgrade() -> None:
    op.alter_column(
        "project_object_id_counters",
        "nextObjectId",
        existing_type=sa.Integer(),
        server_default=sa.text("1"),
        existing_nullable=False,
    )

    op.drop_column(
        "project_object_id_counters",
        "nextProtocolId",
    )
