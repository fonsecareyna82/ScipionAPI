"""Make a facility's conventions its own: the name of its sessions and the folders of each microscope.

Facilities name sessions and folders their own way. facility_settings keeps the facility's choices (the
pattern of a session's name, e.g. {date:%Y_%m_%d}_{user}_{id:06d}). Each microscope has a short code for
names, the pattern of its DATA and ATLAS folders (no ATLAS pattern: no atlas) and how many grids its autoloader
takes. A dataset keeps the folder it was given, so a later change of a pattern never renames the folders a
microscope is writing.

Revision ID: e7a3c1f9d254
Revises: d9b4e2f6a137
"""
from alembic import op


revision = "e7a3c1f9d254"
down_revision = "d9b4e2f6a137"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE facility_settings (
            key TEXT PRIMARY KEY,
            value JSONB NOT NULL,
            "updatedBy" INTEGER REFERENCES users(id) ON DELETE SET NULL,
            "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        ALTER TABLE facility_microscopes
            ADD COLUMN code TEXT NOT NULL DEFAULT '',
            ADD COLUMN "dataFolderPattern" TEXT NOT NULL DEFAULT '{session}_DATA_{n:02d}',
            ADD COLUMN "atlasFolderPattern" TEXT NOT NULL DEFAULT '{session}_ATLAS',
            ADD COLUMN "gridSlots" INTEGER NOT NULL DEFAULT 12,
            ADD CONSTRAINT ck_facility_microscopes_grid_slots CHECK ("gridSlots" BETWEEN 1 AND 99)
    """)
    op.execute("""
        ALTER TABLE facility_session_datasets
            ADD COLUMN folder TEXT NOT NULL DEFAULT '',
            DROP CONSTRAINT ck_facility_session_datasets_kind,
            ADD CONSTRAINT ck_facility_session_datasets_kind CHECK (
                (kind = 'atlas' AND number = 0 AND "gridId" IS NULL) OR (kind = 'data' AND number BETWEEN 1 AND 99))
    """)
    # The folders of the sessions there are: the names they were made with
    op.execute("""
        UPDATE facility_session_datasets d
           SET folder = s.name || CASE WHEN d.kind = 'atlas' THEN '_ATLAS' ELSE '_DATA_' || LPAD(d.number::TEXT, 2, '0') END
          FROM facility_sessions s
         WHERE s.id = d."sessionId"
    """)


def downgrade():
    op.execute("DELETE FROM facility_session_datasets WHERE kind = 'data' AND number > 12")
    op.execute("""
        ALTER TABLE facility_session_datasets
            DROP COLUMN folder,
            DROP CONSTRAINT ck_facility_session_datasets_kind,
            ADD CONSTRAINT ck_facility_session_datasets_kind CHECK (
                (kind = 'atlas' AND number = 0 AND "gridId" IS NULL) OR (kind = 'data' AND number BETWEEN 1 AND 12))
    """)
    op.execute("""
        ALTER TABLE facility_microscopes
            DROP CONSTRAINT ck_facility_microscopes_grid_slots,
            DROP COLUMN code,
            DROP COLUMN "dataFolderPattern",
            DROP COLUMN "atlasFolderPattern",
            DROP COLUMN "gridSlots"
    """)
    op.execute("DROP TABLE IF EXISTS facility_settings")
