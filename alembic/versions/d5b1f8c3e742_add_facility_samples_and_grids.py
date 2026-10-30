"""Add the samples of a facility, their grid boxes and their grids.

A light record of what reaches the microscope: a sample (its NZ code), the
boxes its grids were vitrified into, and each grid in its box position. A grid
keeps its id for good, as each DATA of an acquisition session will point to
the grid it was acquired on.

Revision ID: d5b1f8c3e742
Revises: c7e2a4b9d815
"""
from alembic import op


revision = "d5b1f8c3e742"
down_revision = "c7e2a4b9d815"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE facility_samples (
            id SERIAL PRIMARY KEY,
            code TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            "groupId" INTEGER REFERENCES user_groups(id) ON DELETE SET NULL,
            "ownerId" INTEGER REFERENCES users(id) ON DELETE SET NULL,
            "accessRoute" TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute('CREATE UNIQUE INDEX ux_facility_samples_code ON facility_samples (LOWER(code))')
    op.execute("""
        CREATE TABLE facility_grid_boxes (
            id SERIAL PRIMARY KEY,
            "sampleId" INTEGER NOT NULL REFERENCES facility_samples(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            "vitrificationCode" TEXT NOT NULL DEFAULT '',
            "vitrifiedOn" DATE,
            notes TEXT NOT NULL DEFAULT '',
            -- Checked at commit: a save may swap two boxes' labels
            CONSTRAINT ux_facility_grid_boxes_label UNIQUE ("sampleId", label) DEFERRABLE INITIALLY DEFERRED
        )
    """)
    op.execute("""
        CREATE TABLE facility_grids (
            id SERIAL PRIMARY KEY,
            "boxId" INTEGER NOT NULL REFERENCES facility_grid_boxes(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            "gridNumber" INTEGER,
            "gridType" TEXT NOT NULL DEFAULT '',
            concentration TEXT NOT NULL DEFAULT '',
            specimen TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'stored',
            notes TEXT NOT NULL DEFAULT '',
            -- Checked at commit: a save may swap two grids' positions
            CONSTRAINT ux_facility_grids_position UNIQUE ("boxId", position) DEFERRABLE INITIALLY DEFERRED,
            CONSTRAINT ck_facility_grids_position CHECK (position BETWEEN 1 AND 12),
            CONSTRAINT ck_facility_grids_status CHECK (status IN ('stored', 'loaded', 'used', 'discarded'))
        )
    """)
    op.execute('CREATE INDEX ix_facility_grid_boxes_sample ON facility_grid_boxes ("sampleId")')


def downgrade():
    op.execute("DROP TABLE IF EXISTS facility_grids")
    op.execute("DROP TABLE IF EXISTS facility_grid_boxes")
    op.execute("DROP TABLE IF EXISTS facility_samples")
