"""An account being deleted: it cannot sign in, its projects go, and its row is removed once they are gone.

A user owns projects (projects.ownerId has no delete rule), so their row can only go after them; the projects are
deleted in the background. deletingAt marks the account meanwhile (hidden from the lists, and finished at the
next start if the API stops before).

Revision ID: a1c7e3f5b928
Revises: f8b2d6e4a193
"""
from alembic import op


revision = "a1c7e3f5b928"
down_revision = "f8b2d6e4a193"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE users ADD COLUMN "deletingAt" TIMESTAMPTZ')


def downgrade():
    op.execute('ALTER TABLE users DROP COLUMN "deletingAt"')
