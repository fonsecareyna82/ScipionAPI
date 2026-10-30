"""Add the microscopes of a facility and their calibrated pixel sizes.

The first piece of running a facility in ScipionWeb (facility mode): each
microscope keeps what processing needs to know of it besides what its movies
say (Cs, gain reference and its orientation, where it writes its data) and the
calibrated pixel size at each magnification, which replaces the nominal one
read from the acquisition metadata.

Revision ID: a3d9e5f1c260
Revises: f2b8d4c6a917
"""
from alembic import op


revision = "a3d9e5f1c260"
down_revision = "f2b8d4c6a917"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE facility_microscopes (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            model TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'operational',
            detectors TEXT NOT NULL DEFAULT '',
            "energyFilter" TEXT NOT NULL DEFAULT '',
            "acquisitionSoftware" TEXT NOT NULL DEFAULT '',
            "voltageKv" DOUBLE PRECISION,
            "csMm" DOUBLE PRECISION,
            "gainPath" TEXT NOT NULL DEFAULT '',
            "gainFlip" TEXT NOT NULL DEFAULT 'none',
            "gainRotation" INTEGER NOT NULL DEFAULT 0,
            "offloadPath" TEXT NOT NULL DEFAULT '',
            "sessionsEnabled" BOOLEAN NOT NULL DEFAULT FALSE,
            notes TEXT NOT NULL DEFAULT '',
            "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_facility_microscopes_status
                CHECK (status IN ('operational', 'maintenance', 'out_of_service')),
            CONSTRAINT ck_facility_microscopes_gain_flip
                CHECK ("gainFlip" IN ('none', 'horizontal', 'vertical')),
            CONSTRAINT ck_facility_microscopes_gain_rotation
                CHECK ("gainRotation" IN (0, 90, 180, 270))
        )
    """)
    op.execute("""
        CREATE TABLE facility_microscope_pixel_sizes (
            "microscopeId" INTEGER NOT NULL REFERENCES facility_microscopes(id) ON DELETE CASCADE,
            magnification INTEGER NOT NULL,
            "pixelSize" DOUBLE PRECISION NOT NULL,
            PRIMARY KEY ("microscopeId", magnification),
            CONSTRAINT ck_facility_microscope_pixel_sizes_positive
                CHECK (magnification > 0 AND "pixelSize" > 0)
        )
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS facility_microscope_pixel_sizes")
    op.execute("DROP TABLE IF EXISTS facility_microscopes")
