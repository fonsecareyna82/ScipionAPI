"""add metadata to scipion relations

Revision ID: 8af62df7d90c
Revises: 9bb10c269920
Create Date: 2026-07-24 01:52:43.262358

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '8af62df7d90c'
down_revision: Union[str, None] = '9bb10c269920'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scipion_relations",
        sa.Column(
            "metadata",
            postgresql.JSONB(
                astext_type=sa.Text()
            ),
            server_default=sa.text(
                "'{}'::jsonb"
            ),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "scipion_relations",
        "metadata",
    )
