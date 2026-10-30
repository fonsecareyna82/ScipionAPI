"""Add what the watcher of a session's folders records on each dataset.

While a session acquires, the watcher looks at each DATA folder on its microscope's offload: how many movies
it holds and how big, when the first and the newest arrived, and what the first one's metadata says
(detector, magnification, calibrated pixel, dose, frames). scanState keeps, per folder of movies, what the
last look found, so the next one reads only the folders that changed.

Revision ID: b5e9d3a1c704
Revises: a8d2c5f7e913
"""
from alembic import op


revision = "b5e9d3a1c704"
down_revision = "a8d2c5f7e913"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE facility_session_datasets
            ADD COLUMN "movieCount" INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN "movieBytes" BIGINT NOT NULL DEFAULT 0,
            ADD COLUMN "firstMovieAt" TIMESTAMPTZ,
            ADD COLUMN "lastMovieAt" TIMESTAMPTZ,
            ADD COLUMN "scannedAt" TIMESTAMPTZ,
            ADD COLUMN acquisition JSONB,
            ADD COLUMN "scanState" JSONB NOT NULL DEFAULT '{}'::JSONB
    """)


def downgrade():
    op.execute("""
        ALTER TABLE facility_session_datasets
            DROP COLUMN "movieCount",
            DROP COLUMN "movieBytes",
            DROP COLUMN "firstMovieAt",
            DROP COLUMN "lastMovieAt",
            DROP COLUMN "scannedAt",
            DROP COLUMN acquisition,
            DROP COLUMN "scanState"
    """)
