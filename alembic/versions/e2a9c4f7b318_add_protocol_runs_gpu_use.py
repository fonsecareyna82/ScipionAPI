"""How much a run really used its GPUs, besides how many it was given.

While a run with GPUs goes on, its worker looks at those GPUs every few seconds: how busy each one was with the
run's processes, and how much memory they held. gpuSamples counts those looks, gpuBusySum adds up each look's
mean busy percentage (so the mean is gpuBusySum / gpuSamples) and gpuMemoryPeakBytes keeps the most memory the
run held at once. A run never looked at (no GPUs, sent to a queue, or a machine that cannot tell) keeps 0 samples.

Revision ID: e2a9c4f7b318
Revises: d7f3b1e9a462
"""
from alembic import op


revision = "e2a9c4f7b318"
down_revision = "d7f3b1e9a462"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE protocol_runs
            ADD COLUMN "gpuSamples" INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN "gpuBusySum" DOUBLE PRECISION NOT NULL DEFAULT 0,
            ADD COLUMN "gpuMemoryPeakBytes" BIGINT
    """)


def downgrade():
    op.execute("""
        ALTER TABLE protocol_runs
            DROP COLUMN "gpuSamples",
            DROP COLUMN "gpuBusySum",
            DROP COLUMN "gpuMemoryPeakBytes"
    """)
