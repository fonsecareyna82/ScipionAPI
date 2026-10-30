"""Add a photo to each microscope of a facility.

Kept in the database (reduced to a web image when uploaded, a few hundred KB),
so it goes with the database backups and depends on no folder of the server.

Revision ID: c7e2a4b9d815
Revises: a3d9e5f1c260
"""
from alembic import op


revision = "c7e2a4b9d815"
down_revision = "a3d9e5f1c260"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE facility_microscope_photos (
            "microscopeId" INTEGER PRIMARY KEY REFERENCES facility_microscopes(id) ON DELETE CASCADE,
            "contentType" TEXT NOT NULL,
            data BYTEA NOT NULL,
            "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS facility_microscope_photos")
