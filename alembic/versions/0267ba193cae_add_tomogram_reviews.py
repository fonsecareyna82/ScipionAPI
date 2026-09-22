"""add tomogram reviews

Revision ID: 0267ba193cae
Revises: 5c69b668091c
Create Date: 2026-09-22 15:29:41.221207

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0267ba193cae'
down_revision: Union[str, None] = '5c69b668091c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tomogram_review_schemas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("setId", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "definition",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("createdByUserId", sa.Integer(), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_tomogram_review_schemas_version_positive"),
        sa.CheckConstraint("revision > 0", name="ck_tomogram_review_schemas_revision_positive"),
        sa.ForeignKeyConstraint(["setId"], ["scipion_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["createdByUserId"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("setId", name="ux_tomogram_review_schemas_set"),
    )
    op.create_index(op.f("ix_tomogram_review_schemas_id"), "tomogram_review_schemas", ["id"])
    op.create_index("idx_tomogram_review_schemas_set", "tomogram_review_schemas", ["setId"])
    op.create_index(
        "idx_tomogram_review_schemas_definition_gin",
        "tomogram_review_schemas",
        ["definition"],
        postgresql_using="gin",
    )

    op.create_table(
        "tomogram_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("setId", sa.Integer(), nullable=False),
        sa.Column("scipionItemId", sa.Integer(), nullable=False),
        sa.Column("reviewed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "values",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("schemaVersion", sa.Integer(), server_default="1", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("reviewedByUserId", sa.Integer(), nullable=True),
        sa.Column("reviewedAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('"schemaVersion" > 0', name="ck_tomogram_reviews_schema_version_positive"),
        sa.CheckConstraint("revision > 0", name="ck_tomogram_reviews_revision_positive"),
        sa.ForeignKeyConstraint(["setId"], ["scipion_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewedByUserId"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("setId", "scipionItemId", name="ux_tomogram_reviews_set_item"),
    )
    op.create_index(op.f("ix_tomogram_reviews_id"), "tomogram_reviews", ["id"])
    op.create_index("idx_tomogram_reviews_set", "tomogram_reviews", ["setId"])
    op.create_index("idx_tomogram_reviews_set_reviewed", "tomogram_reviews", ["setId", "reviewed"])
    op.create_index("idx_tomogram_reviews_updated", "tomogram_reviews", ["updatedAt"])
    op.create_index(
        "idx_tomogram_reviews_values_gin",
        "tomogram_reviews",
        ["values"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("idx_tomogram_reviews_values_gin", table_name="tomogram_reviews")
    op.drop_index("idx_tomogram_reviews_updated", table_name="tomogram_reviews")
    op.drop_index("idx_tomogram_reviews_set_reviewed", table_name="tomogram_reviews")
    op.drop_index("idx_tomogram_reviews_set", table_name="tomogram_reviews")
    op.drop_index(op.f("ix_tomogram_reviews_id"), table_name="tomogram_reviews")
    op.drop_table("tomogram_reviews")

    op.drop_index("idx_tomogram_review_schemas_definition_gin", table_name="tomogram_review_schemas")
    op.drop_index("idx_tomogram_review_schemas_set", table_name="tomogram_review_schemas")
    op.drop_index(op.f("ix_tomogram_review_schemas_id"), table_name="tomogram_review_schemas")
    op.drop_table("tomogram_review_schemas")
