"""When each account was created, so the administrators hear of new sign-ups.

Existing accounts take the time of this migration.

Revision ID: d4a7c2e8f915
Revises: c3f8a1d6e2b4
"""
from alembic import op


revision = "d4a7c2e8f915"
down_revision = "c3f8a1d6e2b4"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()')


def downgrade():
    op.execute('ALTER TABLE users DROP COLUMN IF EXISTS "createdAt"')
