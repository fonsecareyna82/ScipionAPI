"""Index the child-table lookup and stop maintaining redundant item indexes.

Nested Set reads and writes look up a child table by (setId, parentItemId);
with only a setId index that lookup scans every child table of the Set. The
dropped item indexes repeat the primary key or the leading column of the
unique (scope, item) constraints, which keep serving those lookups.

Revision ID: 6b00be24a501
Revises: b75a4e291c0f
"""
from alembic import op


revision = "6b00be24a501"
down_revision = "b75a4e291c0f"
branch_labels = None
depends_on = None

CHILD_LOOKUP_INDEX = "idx_scipion_set_tables_set_parent"
CHILD_LOOKUP_DEFINITION = 'ON scipion_set_tables ("setId", "parentItemId")'

REDUNDANT_INDEXES = (
    ("ix_scipion_set_items_id", "ON scipion_set_items (id)"),
    ("idx_scipion_set_items_set", 'ON scipion_set_items ("setId")'),
    ("idx_scipion_set_table_items_table", 'ON scipion_set_table_items ("tableId")'),
)


def _rebuild(name, definition):
    # A failed concurrent build leaves an invalid index; drop it first so a
    # retry always ends with a valid one.
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS " + name)
    op.execute("CREATE INDEX CONCURRENTLY " + name + " " + definition)


def upgrade():
    with op.get_context().autocommit_block():
        _rebuild(CHILD_LOOKUP_INDEX, CHILD_LOOKUP_DEFINITION)
        for name, _ in REDUNDANT_INDEXES:
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS " + name)


def downgrade():
    with op.get_context().autocommit_block():
        for name, definition in REDUNDANT_INDEXES:
            _rebuild(name, definition)
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS " + CHILD_LOOKUP_INDEX)
