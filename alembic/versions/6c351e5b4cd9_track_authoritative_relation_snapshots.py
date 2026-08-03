"""track authoritative relation snapshots

Revision ID: 6c351e5b4cd9
Revises: 0d02314012e3
Create Date: 2026-07-16 18:40:11.156583

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6c351e5b4cd9'
down_revision: Union[str, None] = '0d02314012e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "protocols",
        sa.Column(
            "relationsSynchronized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "protocols",
        "relationsSynchronized",
    )
