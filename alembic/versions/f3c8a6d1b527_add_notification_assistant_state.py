"""Whether the AI assistant explained a failure notice: null until it looked at it, then done, failed or off.

While the assistant explains failures, a failure notice waits for it (at most a few minutes) before it is mailed.

Revision ID: f3c8a6d1b527
Revises: e7b3f5a2c814
"""
from alembic import op


revision = "f3c8a6d1b527"
down_revision = "e7b3f5a2c814"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE notifications ADD COLUMN "assistantState" TEXT')


def downgrade():
    op.execute('ALTER TABLE notifications DROP COLUMN "assistantState"')
