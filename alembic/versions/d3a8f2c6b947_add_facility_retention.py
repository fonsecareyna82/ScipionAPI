"""How long a facility keeps a session's data, and what was deleted.

A finished session's data are kept the facility's days (rawRetentionDays, processedRetentionDays) unless the staff
give it another date (rawKeepUntil, processedKeepUntil). The staff record when the raw data were deleted (by hand:
the facility deletes them, not ScipionWeb) and when its projects were (ScipionWeb deletes those), and by whom.
retentionNotices keeps which notices its user was mailed before each date, so none is sent twice.

Revision ID: d3a8f2c6b947
Revises: e6c2a9f4b183
"""
from alembic import op


revision = "d3a8f2c6b947"
down_revision = "e6c2a9f4b183"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE facility_sessions
            ADD COLUMN "rawKeepUntil" DATE,
            ADD COLUMN "processedKeepUntil" DATE,
            ADD COLUMN "rawDeletedAt" TIMESTAMPTZ,
            ADD COLUMN "rawDeletedBy" INTEGER REFERENCES users(id) ON DELETE SET NULL,
            ADD COLUMN "processedDeletedAt" TIMESTAMPTZ,
            ADD COLUMN "processedDeletedBy" INTEGER REFERENCES users(id) ON DELETE SET NULL,
            ADD COLUMN "retentionNotices" JSONB NOT NULL DEFAULT '{}'::JSONB
    """)
    op.execute('CREATE INDEX ix_facility_sessions_finished ON facility_sessions ("finishedAt") '
               'WHERE "finishedAt" IS NOT NULL')


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_facility_sessions_finished")
    op.execute("""
        ALTER TABLE facility_sessions
            DROP COLUMN "retentionNotices",
            DROP COLUMN "processedDeletedBy",
            DROP COLUMN "processedDeletedAt",
            DROP COLUMN "rawDeletedBy",
            DROP COLUMN "rawDeletedAt",
            DROP COLUMN "processedKeepUntil",
            DROP COLUMN "rawKeepUntil"
    """)
