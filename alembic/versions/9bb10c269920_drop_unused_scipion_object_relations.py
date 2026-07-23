"""drop unused scipion object relations

Revision ID: 9bb10c269920
Revises: 9ee90c3d36c8
Create Date: 2026-07-24 01:22:45.861250

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9bb10c269920'
down_revision: Union[str, None] = '9ee90c3d36c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("scipion_object_relations")


def downgrade() -> None:
    op.create_table(
        "scipion_object_relations",
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "projectId",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "creatorObjectId",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "parentObjectId",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "childObjectId",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "name",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "parentExtended",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "childExtended",
            sa.Text(),
            nullable=True,
        ),
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
        sa.Column(
            "creation",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "createdAt",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["projectId"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["creatorObjectId"],
            ["scipion_objects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parentObjectId"],
            ["scipion_objects.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["childObjectId"],
            ["scipion_objects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "idx_scipion_object_relations_child",
        "scipion_object_relations",
        ["childObjectId"],
        unique=False,
    )

    op.create_index(
        "idx_scipion_object_relations_metadata_gin",
        "scipion_object_relations",
        ["metadata"],
        unique=False,
        postgresql_using="gin",
    )

    op.create_index(
        "idx_scipion_object_relations_parent",
        "scipion_object_relations",
        ["parentObjectId"],
        unique=False,
    )

    op.create_index(
        "idx_scipion_object_relations_project_name",
        "scipion_object_relations",
        [
            "projectId",
            "name",
        ],
        unique=False,
    )

    op.create_index(
        op.f("ix_scipion_object_relations_id"),
        "scipion_object_relations",
        ["id"],
        unique=False,
    )
