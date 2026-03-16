"""cascade delete protocols when deleting project

Revision ID: f3f7b0a3f1aa
Revises: d79a883ddb7c
Create Date: 2026-03-16 17:21:17.200505

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3f7b0a3f1aa'
down_revision: Union[str, None] = 'd79a883ddb7c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.drop_constraint(
        "protocols_projectId_fkey",
        "protocols",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "protocols_projectId_fkey",
        "protocols",
        "projects",
        ["projectId"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade():
    op.drop_constraint(
        "protocols_projectId_fkey",
        "protocols",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "protocols_projectId_fkey",
        "protocols",
        "projects",
        ["projectId"],
        ["id"],
    )
