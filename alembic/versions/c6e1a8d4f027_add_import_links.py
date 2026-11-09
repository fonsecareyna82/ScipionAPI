"""What was brought from another system (EMhub), and what it became here.

One row per record imported: its system, its kind (user, group, resource, booking, session), its id there and
the id it has here. Importing again finds them and does not make them twice; a later sync updates them.

Revision ID: c6e1a8d4f027
Revises: b4d8f2a6c391
"""
from alembic import op


revision = "c6e1a8d4f027"
down_revision = "b4d8f2a6c391"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE import_links (
            source TEXT NOT NULL,
            kind TEXT NOT NULL,
            "sourceId" TEXT NOT NULL,
            "targetId" INTEGER NOT NULL,
            "importedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (source, kind, "sourceId")
        )
    """)


def downgrade():
    op.execute("DROP TABLE import_links")
