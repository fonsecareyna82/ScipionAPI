"""Index the foreign keys that cascading deletes look up.

Deleting a protocol (or a project) makes PostgreSQL find, for every deleted
protocol, its objects, Sets and steps by "protocolDbId", and for every deleted
object the Sets that point to it by "objectId". The existing indexes start
with "projectId", so each of those lookups scanned the whole table.

Revision ID: 7a1c2e9d4f30
Revises: 6b00be24a501
"""
from alembic import op


revision = "7a1c2e9d4f30"
down_revision = "6b00be24a501"
branch_labels = None
depends_on = None

INDEXES = (
    ("idx_scipion_objects_protocol_db_id", 'ON scipion_objects ("protocolDbId")'),
    ("idx_scipion_sets_protocol_db_id", 'ON scipion_sets ("protocolDbId")'),
    ("idx_scipion_sets_object_id", 'ON scipion_sets ("objectId")'),
    ("idx_protocol_steps_protocol_db_id", 'ON protocol_steps ("protocolDbId")'),
)


def upgrade():
    with op.get_context().autocommit_block():
        for name, definition in INDEXES:
            # A failed concurrent build leaves an invalid index; drop it first
            # so a retry always ends with a valid one.
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS " + name)
            op.execute("CREATE INDEX CONCURRENTLY " + name + " " + definition)


def downgrade():
    with op.get_context().autocommit_block():
        for name, _ in INDEXES:
            op.execute("DROP INDEX CONCURRENTLY IF EXISTS " + name)
