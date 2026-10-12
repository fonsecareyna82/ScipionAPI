"""Stop maintaining a JSON GIN for nested logical items.

Nested child rows are always read within one logical table, which the
("tableId", "scipionItemId") index already narrows to a small population.
Maintaining the GIN roughly doubled the cost of writing child rows.

Revision ID: 9d064ee31b1b
Revises: 41c8d93e7a62
"""
from alembic import op


revision = "9d064ee31b1b"
down_revision = "41c8d93e7a62"
branch_labels = None
depends_on = None

NESTED_INDEX = "idx_scipion_set_table_items_nested_values_gin"


def upgrade():
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS " + NESTED_INDEX)


def downgrade():
    # A failed concurrent build can leave an invalid index; rebuild it on
    # retry instead of accepting it through IF NOT EXISTS.
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS " + NESTED_INDEX)
        op.execute(
            "CREATE INDEX CONCURRENTLY " + NESTED_INDEX
            + ' ON scipion_set_table_items USING gin ("values")'
            + ' WHERE "parentItemId" IS NOT NULL'
        )
