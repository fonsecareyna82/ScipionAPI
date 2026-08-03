"""add scipion runtime mapper tables

Revision ID: cfe01c5b48d9
Revises: 2fc2cd4da2e2
Create Date: 2026-07-03 10:03:16.950623

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cfe01c5b48d9'
down_revision: Union[str, None] = '2fc2cd4da2e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_object_id_counters",
        sa.Column("projectId", sa.Integer(), nullable=False),
        sa.Column("nextObjectId", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("createdAt", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updatedAt", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(
            ["projectId"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("projectId"),
    )

    op.create_table(
        "scipion_relations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("projectId", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("creatorObjId", sa.Integer(), nullable=False),
        sa.Column("parentObjId", sa.Integer(), nullable=False),
        sa.Column("childObjId", sa.Integer(), nullable=False),
        sa.Column("parentExtended", sa.Text(), nullable=False, server_default=""),
        sa.Column("childExtended", sa.Text(), nullable=False, server_default=""),
        sa.Column("createdAt", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(
            ["projectId"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "projectId",
            "name",
            "creatorObjId",
            "parentObjId",
            "childObjId",
            "parentExtended",
            "childExtended",
            name="ux_scipion_relations_unique_relation",
        ),
    )

    op.create_index(
        "idx_scipion_relations_project_name",
        "scipion_relations",
        ["projectId", "name"],
    )

    op.create_index(
        "idx_scipion_relations_creator",
        "scipion_relations",
        ["projectId", "creatorObjId"],
    )

    op.create_index(
        "idx_scipion_relations_parent",
        "scipion_relations",
        ["projectId", "parentObjId"],
    )

    op.create_index(
        "idx_scipion_relations_child",
        "scipion_relations",
        ["projectId", "childObjId"],
    )


def downgrade() -> None:
    op.drop_index("idx_scipion_relations_child", table_name="scipion_relations")
    op.drop_index("idx_scipion_relations_parent", table_name="scipion_relations")
    op.drop_index("idx_scipion_relations_creator", table_name="scipion_relations")
    op.drop_index("idx_scipion_relations_project_name", table_name="scipion_relations")

    op.drop_table("scipion_relations")
    op.drop_table("project_object_id_counters")
