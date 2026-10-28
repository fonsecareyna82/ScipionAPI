"""Remove the items of a deleted Set in the background instead of inside the delete.

Deleting a Set (a Reset, a Restart, deleting a protocol or a project) used to
remove its items through foreign-key cascades in the same statement: millions
of rows while the user waits. The items keep no foreign key now; when a Set or
one of its tables is deleted, a trigger queues its id in
scipion_set_item_purges in the same transaction, and the server removes the
queued items in batches afterwards. Set and table ids are never reused, so no
reader can see an item whose Set is gone.

Revision ID: b7d2e9f41c08
Revises: 9c4e2a7b1d63
"""
from alembic import op


revision = "b7d2e9f41c08"
down_revision = "9c4e2a7b1d63"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE scipion_set_item_purges (
            id bigserial PRIMARY KEY,
            "setId" integer,
            "tableId" integer,
            "queuedAt" timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_scipion_set_item_purges_one_target
                CHECK (("setId" IS NULL) <> ("tableId" IS NULL))
        )
    """)
    op.execute('ALTER TABLE scipion_set_items DROP CONSTRAINT IF EXISTS "scipion_set_items_setId_fkey"')
    op.execute('ALTER TABLE scipion_set_table_items DROP CONSTRAINT IF EXISTS "scipion_set_table_items_tableId_fkey"')
    op.execute("""
        CREATE FUNCTION queue_set_items_purge() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            INSERT INTO scipion_set_item_purges ("setId") SELECT id FROM removed_rows;
            RETURN NULL;
        END
        $$
    """)
    op.execute("""
        CREATE FUNCTION queue_set_table_items_purge() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            INSERT INTO scipion_set_item_purges ("tableId") SELECT id FROM removed_rows;
            RETURN NULL;
        END
        $$
    """)
    # Per statement, so a cascade removing thousands of tables queues them with one insert
    op.execute("""
        CREATE TRIGGER trg_scipion_sets_queue_items_purge
            AFTER DELETE ON scipion_sets
            REFERENCING OLD TABLE AS removed_rows
            FOR EACH STATEMENT EXECUTE FUNCTION queue_set_items_purge()
    """)
    op.execute("""
        CREATE TRIGGER trg_scipion_set_tables_queue_items_purge
            AFTER DELETE ON scipion_set_tables
            REFERENCING OLD TABLE AS removed_rows
            FOR EACH STATEMENT EXECUTE FUNCTION queue_set_table_items_purge()
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_scipion_set_tables_queue_items_purge ON scipion_set_tables")
    op.execute("DROP TRIGGER IF EXISTS trg_scipion_sets_queue_items_purge ON scipion_sets")
    op.execute("DROP FUNCTION IF EXISTS queue_set_table_items_purge()")
    op.execute("DROP FUNCTION IF EXISTS queue_set_items_purge()")
    # The cascades come back only over items whose Set or table still exists
    op.execute("""
        DELETE FROM scipion_set_items i
         WHERE NOT EXISTS (SELECT 1 FROM scipion_sets s WHERE s.id = i."setId")
    """)
    op.execute("""
        DELETE FROM scipion_set_table_items i
         WHERE NOT EXISTS (SELECT 1 FROM scipion_set_tables t WHERE t.id = i."tableId")
    """)
    op.execute("""
        ALTER TABLE scipion_set_items ADD CONSTRAINT "scipion_set_items_setId_fkey"
            FOREIGN KEY ("setId") REFERENCES scipion_sets(id) ON DELETE CASCADE
    """)
    op.execute("""
        ALTER TABLE scipion_set_table_items ADD CONSTRAINT "scipion_set_table_items_tableId_fkey"
            FOREIGN KEY ("tableId") REFERENCES scipion_set_tables(id) ON DELETE CASCADE
    """)
    op.execute("DROP TABLE IF EXISTS scipion_set_item_purges")
