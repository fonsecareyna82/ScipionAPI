"""Signing out of the institution too, so the next person at the same browser is asked who they are.

An institution's sign-in service keeps its own session in the browser: without ending it, the next person to
press its button on the same computer would come in as the one before. signOutAtProvider (on by default) makes
ScipionWeb's sign-out end it too; the ID token of the sign-in travels with its one-time code (idToken), as the
provider asks for it to sign out without asking.

Revision ID: b3e7d9f1c264
Revises: a8d2f6c4e159
"""
from alembic import op


revision = "b3e7d9f1c264"
down_revision = "a8d2f6c4e159"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE sign_in_providers ADD COLUMN "signOutAtProvider" BOOLEAN NOT NULL DEFAULT TRUE')
    op.execute('ALTER TABLE sign_in_requests ADD COLUMN "idToken" TEXT')


def downgrade():
    op.execute('ALTER TABLE sign_in_requests DROP COLUMN "idToken"')
    op.execute('ALTER TABLE sign_in_providers DROP COLUMN "signOutAtProvider"')
