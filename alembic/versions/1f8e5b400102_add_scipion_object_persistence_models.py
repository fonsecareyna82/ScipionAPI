"""add scipion object persistence models

Revision ID: 1f8e5b400102
Revises: 6806b9a72a6e
Create Date: 2026-06-19 11:10:02.296385

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "1f8e5b400102"
down_revision: Union[str, None] = "6806b9a72a6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scipion_object_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("className", sa.Text(), nullable=False),
        sa.Column("moduleName", sa.Text(), nullable=True),
        sa.Column("baseClassName", sa.Text(), nullable=True),
        sa.Column("mapperKind", sa.Text(), server_default="tree", nullable=False),
        sa.Column(
            "schema",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("\"mapperKind\" IN ('tree', 'flat_set', 'scalar', 'pointer')", name="ck_scipion_object_types_mapper_kind"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("className"),
    )
    op.create_index("idx_scipion_object_types_className", "scipion_object_types", ["className"])
    op.create_index("idx_scipion_object_types_mapperKind", "scipion_object_types", ["mapperKind"])
    op.create_index(
        "idx_scipion_object_types_schema_gin",
        "scipion_object_types",
        ["schema"],
        postgresql_using="gin",
    )
    op.create_index(op.f("ix_scipion_object_types_id"), "scipion_object_types", ["id"])

    op.create_table(
        "scipion_object_type_properties",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("typeId", sa.Integer(), nullable=False),
        sa.Column("propertyPath", sa.Text(), nullable=False),
        sa.Column("className", sa.Text(), nullable=True),
        sa.Column("valueKind", sa.Text(), nullable=True),
        sa.Column("isPointer", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("isNested", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "schema",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["typeId"], ["scipion_object_types.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("typeId", "propertyPath", name="ux_scipion_object_type_properties_type_path"),
    )
    op.create_index("idx_scipion_object_type_properties_path", "scipion_object_type_properties", ["propertyPath"])
    op.create_index(
        "idx_scipion_object_type_properties_schema_gin",
        "scipion_object_type_properties",
        ["schema"],
        postgresql_using="gin",
    )
    op.create_index(op.f("ix_scipion_object_type_properties_id"), "scipion_object_type_properties", ["id"])

    op.create_table(
        "scipion_objects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("projectId", sa.Integer(), nullable=False),
        sa.Column("protocolDbId", sa.Integer(), nullable=True),
        sa.Column("scipionObjId", sa.Integer(), nullable=False),
        sa.Column("parentObjectId", sa.Integer(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("className", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("creation", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["parentObjectId"], ["scipion_objects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["projectId"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["protocolDbId"], ["protocols.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("projectId", "protocolDbId", "path", name="ux_scipion_objects_project_protocol_path"),
        sa.UniqueConstraint(
            "projectId",
            "protocolDbId",
            "scipionObjId",
            name="ux_scipion_objects_project_protocol_obj",
        ),
    )
    op.create_index("idx_scipion_objects_metadata_gin", "scipion_objects", ["metadata"], postgresql_using="gin")
    op.create_index("idx_scipion_objects_parent", "scipion_objects", ["parentObjectId"])
    op.create_index("idx_scipion_objects_project_class", "scipion_objects", ["projectId", "className"])
    op.create_index("idx_scipion_objects_project_protocol", "scipion_objects", ["projectId", "protocolDbId"])
    op.create_index(op.f("ix_scipion_objects_id"), "scipion_objects", ["id"])

    op.create_table(
        "scipion_object_relations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("projectId", sa.Integer(), nullable=False),
        sa.Column("creatorObjectId", sa.Integer(), nullable=False),
        sa.Column("parentObjectId", sa.Integer(), nullable=False),
        sa.Column("childObjectId", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("parentExtended", sa.Text(), nullable=True),
        sa.Column("childExtended", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("creation", sa.DateTime(timezone=True), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["childObjectId"], ["scipion_objects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["creatorObjectId"], ["scipion_objects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parentObjectId"], ["scipion_objects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["projectId"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_scipion_object_relations_child", "scipion_object_relations", ["childObjectId"])
    op.create_index(
        "idx_scipion_object_relations_metadata_gin",
        "scipion_object_relations",
        ["metadata"],
        postgresql_using="gin",
    )
    op.create_index("idx_scipion_object_relations_parent", "scipion_object_relations", ["parentObjectId"])
    op.create_index("idx_scipion_object_relations_project_name", "scipion_object_relations", ["projectId", "name"])
    op.create_index(op.f("ix_scipion_object_relations_id"), "scipion_object_relations", ["id"])

    op.create_table(
        "scipion_sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("projectId", sa.Integer(), nullable=False),
        sa.Column("protocolDbId", sa.Integer(), nullable=True),
        sa.Column("objectId", sa.Integer(), nullable=True),
        sa.Column("outputName", sa.Text(), nullable=False),
        sa.Column("setClassName", sa.Text(), nullable=False),
        sa.Column("itemClassName", sa.Text(), nullable=False),
        sa.Column(
            "properties",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["objectId"], ["scipion_objects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["projectId"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["protocolDbId"], ["protocols.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("projectId", "protocolDbId", "outputName", name="ux_scipion_sets_project_protocol_output"),
    )
    op.create_index("idx_scipion_sets_project_protocol", "scipion_sets", ["projectId", "protocolDbId"])
    op.create_index("idx_scipion_sets_properties_gin", "scipion_sets", ["properties"], postgresql_using="gin")
    op.create_index(op.f("ix_scipion_sets_id"), "scipion_sets", ["id"])

    op.create_table(
        "scipion_set_columns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("setId", sa.Integer(), nullable=False),
        sa.Column("labelProperty", sa.Text(), nullable=False),
        sa.Column("columnName", sa.Text(), nullable=False),
        sa.Column("className", sa.Text(), nullable=True),
        sa.Column("valueType", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("indexed", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["setId"], ["scipion_sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("setId", "columnName", name="ux_scipion_set_columns_set_column"),
        sa.UniqueConstraint("setId", "labelProperty", name="ux_scipion_set_columns_set_label"),
    )
    op.create_index("idx_scipion_set_columns_label", "scipion_set_columns", ["labelProperty"])
    op.create_index(op.f("ix_scipion_set_columns_id"), "scipion_set_columns", ["id"])

    op.create_table(
        "scipion_set_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("setId", sa.Integer(), nullable=False),
        sa.Column("scipionItemId", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(["setId"], ["scipion_sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("setId", "scipionItemId", name="ux_scipion_set_items_set_item"),
    )
    op.create_index("idx_scipion_set_items_set", "scipion_set_items", ["setId"])
    op.create_index("idx_scipion_set_items_values_gin", "scipion_set_items", ["values"], postgresql_using="gin")
    op.create_index(op.f("ix_scipion_set_items_id"), "scipion_set_items", ["id"])

    op.create_table(
        "scipion_set_properties",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("setId", sa.Integer(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["setId"], ["scipion_sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("setId", "key", name="ux_scipion_set_properties_set_key"),
    )
    op.create_index("idx_scipion_set_properties_key", "scipion_set_properties", ["key"])
    op.create_index(op.f("ix_scipion_set_properties_id"), "scipion_set_properties", ["id"])


def downgrade() -> None:
    op.drop_table("scipion_set_properties")
    op.drop_table("scipion_set_items")
    op.drop_table("scipion_set_columns")
    op.drop_table("scipion_sets")
    op.drop_table("scipion_object_relations")
    op.drop_table("scipion_objects")
    op.drop_table("scipion_object_type_properties")
    op.drop_table("scipion_object_types")