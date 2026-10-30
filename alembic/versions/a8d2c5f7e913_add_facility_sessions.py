"""Add the facility's acquisition sessions and their datasets.

A session is one stay on a microscope: who it is for, its EMhub booking, its
state, and the folders the microscope writes. Those are its datasets: one ATLAS
and up to twelve DATA_NN (multigrid), each DATA the grid it was taken from, and
later the detector that took it and the project that processes it. Its name
makes the folder names the operator types into EPU, so it holds still once the
acquisition starts.

A microscope or a grid that a session used stays (RESTRICT): the session is
the history of what was acquired. Sessions and datasets keep images too (a
screenshot of the atlas, of a grid square).

Revision ID: a8d2c5f7e913
Revises: f4c8e1a7b392
"""
from alembic import op


revision = "a8d2c5f7e913"
down_revision = "f4c8e1a7b392"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE facility_sessions (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            "microscopeId" INTEGER NOT NULL REFERENCES facility_microscopes(id) ON DELETE RESTRICT,
            technique TEXT NOT NULL DEFAULT 'spa',
            status TEXT NOT NULL DEFAULT 'planned',
            "groupId" INTEGER REFERENCES user_groups(id) ON DELETE SET NULL,
            "userId" INTEGER REFERENCES users(id) ON DELETE SET NULL,
            "bookingRef" TEXT NOT NULL DEFAULT '',
            "scheduledOn" DATE,
            "startedAt" TIMESTAMPTZ,
            "finishedAt" TIMESTAMPTZ,
            notes TEXT NOT NULL DEFAULT '',
            "createdBy" INTEGER REFERENCES users(id) ON DELETE SET NULL,
            "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ux_facility_sessions_name UNIQUE (name),
            CONSTRAINT ck_facility_sessions_technique CHECK (technique IN ('spa', 'tomo')),
            CONSTRAINT ck_facility_sessions_status CHECK (status IN ('planned', 'acquiring', 'finished', 'archived'))
        )
    """)
    op.execute('CREATE INDEX ix_facility_sessions_microscope ON facility_sessions ("microscopeId")')
    op.execute('CREATE INDEX ix_facility_sessions_status ON facility_sessions (status)')
    op.execute("""
        CREATE TABLE facility_session_datasets (
            id SERIAL PRIMARY KEY,
            "sessionId" INTEGER NOT NULL REFERENCES facility_sessions(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            number INTEGER NOT NULL,
            "gridId" INTEGER REFERENCES facility_grids(id) ON DELETE RESTRICT,
            "detectorId" INTEGER REFERENCES facility_detectors(id) ON DELETE SET NULL,
            notes TEXT NOT NULL DEFAULT '',
            CONSTRAINT ux_facility_session_datasets_number UNIQUE ("sessionId", number) DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT ck_facility_session_datasets_kind CHECK (
                (kind = 'atlas' AND number = 0 AND "gridId" IS NULL) OR (kind = 'data' AND number BETWEEN 1 AND 12))
        )
    """)
    op.execute('CREATE INDEX ix_facility_session_datasets_grid ON facility_session_datasets ("gridId") '
               'WHERE "gridId" IS NOT NULL')
    op.execute("""
        ALTER TABLE facility_images
            ADD COLUMN "sessionId" INTEGER REFERENCES facility_sessions(id) ON DELETE CASCADE,
            ADD COLUMN "datasetId" INTEGER REFERENCES facility_session_datasets(id) ON DELETE CASCADE,
            DROP CONSTRAINT ck_facility_images_one_owner,
            ADD CONSTRAINT ck_facility_images_one_owner
                CHECK (num_nonnulls("sampleId", "boxId", "gridId", "sessionId", "datasetId") = 1)
    """)
    op.execute('CREATE INDEX ix_facility_images_session ON facility_images ("sessionId") WHERE "sessionId" IS NOT NULL')
    op.execute('CREATE INDEX ix_facility_images_dataset ON facility_images ("datasetId") WHERE "datasetId" IS NOT NULL')


def downgrade():
    op.execute('DELETE FROM facility_images WHERE "sessionId" IS NOT NULL OR "datasetId" IS NOT NULL')
    op.execute("""
        ALTER TABLE facility_images
            DROP CONSTRAINT ck_facility_images_one_owner,
            DROP COLUMN "sessionId",
            DROP COLUMN "datasetId",
            ADD CONSTRAINT ck_facility_images_one_owner CHECK (num_nonnulls("sampleId", "boxId", "gridId") = 1)
    """)
    op.execute("DROP TABLE IF EXISTS facility_session_datasets")
    op.execute("DROP TABLE IF EXISTS facility_sessions")
