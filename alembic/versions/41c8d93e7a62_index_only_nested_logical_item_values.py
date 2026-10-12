"""Avoid maintaining a second JSON GIN for canonical root items.

Revision ID: 41c8d93e7a62
Revises: 0267ba193cae
"""
from alembic import op


revision = "41c8d93e7a62"
down_revision = "0267ba193cae"
branch_labels = None
depends_on = None

FULL_INDEX = "idx_scipion_set_table_items_values_gin"
NESTED_INDEX = "idx_scipion_set_table_items_nested_values_gin"


def _replaceIndex(destination, definition, obsolete):
    # A failed concurrent build can leave an invalid index. Rebuild it on
    # retry; IF NOT EXISTS alone would incorrectly accept that invalid index.
    # Keep the previous index until its replacement has been built successfully.
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS " + destination)
        op.execute(definition)
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS " + obsolete)


def upgrade():
    _replaceIndex(
        NESTED_INDEX,
        'CREATE INDEX CONCURRENTLY ' + NESTED_INDEX
        + ' ON scipion_set_table_items USING gin ("values")'
        + ' WHERE "parentItemId" IS NOT NULL',
        FULL_INDEX,
    )


def downgrade():
    _replaceIndex(
        FULL_INDEX,
        'CREATE INDEX CONCURRENTLY ' + FULL_INDEX
        + ' ON scipion_set_table_items USING gin ("values")',
        NESTED_INDEX,
    )
