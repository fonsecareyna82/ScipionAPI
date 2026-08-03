"""add native protocol step state

Revision ID: 9b9016b043d3
Revises: 8af62df7d90c
Create Date: 2026-07-27 18:52:29.271913

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '9b9016b043d3'
down_revision: Union[str, None] = '8af62df7d90c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "protocol_steps",
        sa.Column(
            "stepClassName",
            sa.Text(),
            nullable=True,
        ),
    )

    op.add_column(
        "protocol_steps",
        sa.Column(
            "argsText",
            sa.Text(),
            nullable=True,
        ),
    )

    op.add_column(
        "protocol_steps",
        sa.Column(
            "resultFiles",
            postgresql.JSONB(
                astext_type=sa.Text(),
            ),
            nullable=True,
        ),
    )

    op.add_column(
        "protocol_steps",
        sa.Column(
            "schemaVersion",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "protocol_steps",
        "schemaVersion",
    )

    op.drop_column(
        "protocol_steps",
        "resultFiles",
    )

    op.drop_column(
        "protocol_steps",
        "argsText",
    )

    op.drop_column(
        "protocol_steps",
        "stepClassName",
    )
