"""Keep a record of every protocol run: who launched it, where it ran, for how long and with which GPUs.

The protocols table only knows a protocol's last run (a restart overwrites it), so the computing each user, group
and protocol takes over a month cannot be read from it. protocol_runs keeps one row per run, written by the
worker that executes it: when it starts, a heartbeat while it runs (lastSeenAt), and when it ends. A run whose
worker was killed keeps no end; it is taken to have ended at its last heartbeat.

Rows outlive their project (the usage of a deleted project still counts) and their user.

Revision ID: e6c2a9f4b183
Revises: b9e4c1d7a258
"""
from alembic import op


revision = "e6c2a9f4b183"
down_revision = "b9e4c1d7a258"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE protocol_runs (
            id BIGSERIAL PRIMARY KEY,
            "projectId" INTEGER REFERENCES projects(id) ON DELETE SET NULL,
            "projectPath" TEXT,
            "protocolId" TEXT NOT NULL,
            "protocolClassName" TEXT,
            "protocolLabel" TEXT,
            "userId" INTEGER REFERENCES users(id) ON DELETE SET NULL,
            "executionId" TEXT,
            "coordinatorRunId" TEXT,
            host TEXT,
            "queueName" TEXT,
            "queueJobId" TEXT,
            gpus INTEGER NOT NULL DEFAULT 0,
            "gpuIds" TEXT,
            threads INTEGER,
            mpi INTEGER,
            streaming BOOLEAN NOT NULL DEFAULT FALSE,
            "startedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "lastSeenAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "endedAt" TIMESTAMPTZ,
            status TEXT
        )
    """)
    op.execute('CREATE INDEX ix_protocol_runs_started ON protocol_runs ("startedAt")')
    op.execute('CREATE INDEX ix_protocol_runs_user ON protocol_runs ("userId", "startedAt")')
    op.execute('CREATE INDEX ix_protocol_runs_protocol ON protocol_runs ("projectId", "protocolId")')
    op.execute('CREATE INDEX ix_protocol_runs_open ON protocol_runs ("lastSeenAt") WHERE "endedAt" IS NULL')


def downgrade():
    op.execute("DROP TABLE protocol_runs")
