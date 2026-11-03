"""Add the facility's alerts: what went wrong in a session, for its operators to know at once.

The watcher opens an alert when a DATA acquiring gets no more movies, when making its project fails, or when a
protocol of its project fails, and resolves it when that is over. An open alert of a kind is never opened twice
for the same DATA (and protocol). The staff acknowledge it ("I am on it"); it is mailed to the operators once,
when the facility has a mail server.

Revision ID: f1c5b8e3a926
Revises: e7a3c1f9d254
"""
from alembic import op


revision = "f1c5b8e3a926"
down_revision = "e7a3c1f9d254"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE facility_alerts (
            id SERIAL PRIMARY KEY,
            kind TEXT NOT NULL,
            "sessionId" INTEGER NOT NULL REFERENCES facility_sessions(id) ON DELETE CASCADE,
            "datasetId" INTEGER NOT NULL REFERENCES facility_session_datasets(id) ON DELETE CASCADE,
            "projectId" INTEGER REFERENCES projects(id) ON DELETE SET NULL,
            "protocolId" TEXT NOT NULL DEFAULT '',
            message TEXT NOT NULL,
            "openedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "resolvedAt" TIMESTAMPTZ,
            "acknowledgedAt" TIMESTAMPTZ,
            "acknowledgedBy" INTEGER REFERENCES users(id) ON DELETE SET NULL,
            "emailedAt" TIMESTAMPTZ,
            "emailError" TEXT,
            CONSTRAINT ck_facility_alerts_kind CHECK (kind IN ('stalled', 'processingFailed', 'protocolFailed'))
        )
    """)
    op.execute('CREATE UNIQUE INDEX ux_facility_alerts_open ON facility_alerts (kind, "datasetId", "protocolId") '
               'WHERE "resolvedAt" IS NULL')
    op.execute('CREATE INDEX ix_facility_alerts_session ON facility_alerts ("sessionId")')


def downgrade():
    op.execute("DROP TABLE IF EXISTS facility_alerts")
