"""add scipion set logical tables

Revision ID: 33ffae69565b
Revises: c3d2b8f4a901
Create Date: 2026-06-19 22:01:10.327665

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '33ffae69565b'
down_revision: Union[str, None] = 'c3d2b8f4a901'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scipion_set_tables",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("setId", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("alias", sa.Text(), nullable=True),
        sa.Column("tableKind", sa.Text(), server_default="root", nullable=False),
        sa.Column("parentTableId", sa.Integer(), nullable=True),
        sa.Column("parentItemId", sa.Integer(), nullable=True),
        sa.Column("itemClassName", sa.Text(), nullable=True),
        sa.Column(
            "properties",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "\"tableKind\" IN ('root', 'child', 'properties')",
            name="ck_scipion_set_tables_table_kind",
        ),
        sa.ForeignKeyConstraint(["setId"], ["scipion_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parentTableId"], ["scipion_set_tables.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("setId", "name", name="ux_scipion_set_tables_set_name"),
    )
    op.create_index("idx_scipion_set_tables_set", "scipion_set_tables", ["setId"])
    op.create_index("idx_scipion_set_tables_parent", "scipion_set_tables", ["parentTableId"])
    op.create_index("idx_scipion_set_tables_properties_gin", "scipion_set_tables", ["properties"], postgresql_using="gin")

    op.create_table(
        "scipion_set_table_columns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tableId", sa.Integer(), nullable=False),
        sa.Column("labelProperty", sa.Text(), nullable=False),
        sa.Column("columnName", sa.Text(), nullable=False),
        sa.Column("className", sa.Text(), nullable=True),
        sa.Column("valueType", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("indexed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "properties",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tableId"], ["scipion_set_tables.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tableId", "labelProperty", name="ux_scipion_set_table_columns_table_label"),
        sa.UniqueConstraint("tableId", "columnName", name="ux_scipion_set_table_columns_table_column"),
    )
    op.create_index("idx_scipion_set_table_columns_table", "scipion_set_table_columns", ["tableId"])
    op.create_index("idx_scipion_set_table_columns_label", "scipion_set_table_columns", ["labelProperty"])

    op.create_table(
        "scipion_set_table_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tableId", sa.Integer(), nullable=False),
        sa.Column("scipionItemId", sa.Integer(), nullable=False),
        sa.Column("parentItemId", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("creation", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "values",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tableId"], ["scipion_set_tables.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tableId", "scipionItemId", name="ux_scipion_set_table_items_table_item"),
    )
    op.create_index("idx_scipion_set_table_items_table", "scipion_set_table_items", ["tableId"])
    op.create_index("idx_scipion_set_table_items_parent", "scipion_set_table_items", ["parentItemId"])
    op.create_index("idx_scipion_set_table_items_values_gin", "scipion_set_table_items", ["values"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("idx_scipion_set_table_items_values_gin", table_name="scipion_set_table_items")
    op.drop_index("idx_scipion_set_table_items_parent", table_name="scipion_set_table_items")
    op.drop_index("idx_scipion_set_table_items_table", table_name="scipion_set_table_items")
    op.drop_table("scipion_set_table_items")

    op.drop_index("idx_scipion_set_table_columns_label", table_name="scipion_set_table_columns")
    op.drop_index("idx_scipion_set_table_columns_table", table_name="scipion_set_table_columns")
    op.drop_table("scipion_set_table_columns")

    op.drop_index("idx_scipion_set_tables_properties_gin", table_name="scipion_set_tables")
    op.drop_index("idx_scipion_set_tables_parent", table_name="scipion_set_tables")
    op.drop_index("idx_scipion_set_tables_set", table_name="scipion_set_tables")
    op.drop_table("scipion_set_tables")