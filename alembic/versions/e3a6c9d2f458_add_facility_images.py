"""Add images to a facility's samples, grid boxes and grids.

Several images each (a photo of a box, the atlas or a screening shot of a grid),
kept in the database as web images so they go with its backups. An image
belongs to exactly one sample, box or grid, and goes with it.

Revision ID: e3a6c9d2f458
Revises: d5b1f8c3e742
"""
from alembic import op


revision = "e3a6c9d2f458"
down_revision = "d5b1f8c3e742"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE facility_images (
            id SERIAL PRIMARY KEY,
            "sampleId" INTEGER REFERENCES facility_samples(id) ON DELETE CASCADE,
            "boxId" INTEGER REFERENCES facility_grid_boxes(id) ON DELETE CASCADE,
            "gridId" INTEGER REFERENCES facility_grids(id) ON DELETE CASCADE,
            caption TEXT NOT NULL DEFAULT '',
            "contentType" TEXT NOT NULL,
            data BYTEA NOT NULL,
            "createdBy" INTEGER REFERENCES users(id) ON DELETE SET NULL,
            "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_facility_images_one_owner CHECK (num_nonnulls("sampleId", "boxId", "gridId") = 1)
        )
    """)
    op.execute('CREATE INDEX ix_facility_images_sample ON facility_images ("sampleId") WHERE "sampleId" IS NOT NULL')
    op.execute('CREATE INDEX ix_facility_images_box ON facility_images ("boxId") WHERE "boxId" IS NOT NULL')
    op.execute('CREATE INDEX ix_facility_images_grid ON facility_images ("gridId") WHERE "gridId" IS NOT NULL')


def downgrade():
    op.execute("DROP TABLE IF EXISTS facility_images")
