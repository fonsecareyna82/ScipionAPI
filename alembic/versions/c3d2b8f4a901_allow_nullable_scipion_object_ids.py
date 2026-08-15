"""allow nullable scipion object ids

Revision ID: c3d2b8f4a901
Revises: 1f8e5b400102
Create Date: 2026-06-19 10:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d2b8f4a901"
down_revision: Union[str, None] = "1f8e5b400102"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "scipion_objects",
        "scipionObjId",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.execute('UPDATE scipion_objects SET "scipionObjId" = NULL WHERE "scipionObjId" < 0')


def downgrade() -> None:
    op.execute('UPDATE scipion_objects SET "scipionObjId" = -id WHERE "scipionObjId" IS NULL')
    op.alter_column(
        "scipion_objects",
        "scipionObjId",
        existing_type=sa.Integer(),
        nullable=False,
    )
