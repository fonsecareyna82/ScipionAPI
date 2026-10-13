"""Stop maintaining a JSON GIN for root Set items.

The Set-scoped item index still serves normal reads. The JSON GIN only helps
discover the type of an undeclared JSON field that is rare or absent; keeping
it substantially increases bulk item write cost.

Revision ID: b75a4e291c0f
Revises: 9d064ee31b1b
"""
from alembic import op


revision = "b75a4e291c0f"
down_revision = "9d064ee31b1b"
branch_labels = None
depends_on = None

ROOT_INDEX = "idx_scipion_set_items_values_gin"


def upgrade():
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS " + ROOT_INDEX)


def downgrade():
    # A failed concurrent build can leave an invalid index. Remove it first
    # so retrying the downgrade builds a valid replacement.
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS " + ROOT_INDEX)
        op.execute(
            "CREATE INDEX CONCURRENTLY " + ROOT_INDEX
            + ' ON scipion_set_items USING gin ("values")'
        )
