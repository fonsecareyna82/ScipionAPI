"""Resetting a forgotten password: a one-time link mailed to the account's address.

Only the token's hash is kept; it lasts an hour and is used once (a new one, or a reset, ends the others).

Revision ID: b4d8f2a6c391
Revises: a1c7e3f5b928
"""
from alembic import op


revision = "b4d8f2a6c391"
down_revision = "a1c7e3f5b928"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE password_resets (
            id BIGSERIAL PRIMARY KEY,
            "userId" INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            "tokenHash" TEXT NOT NULL UNIQUE,
            "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "expiresAt" TIMESTAMPTZ NOT NULL,
            "usedAt" TIMESTAMPTZ
        )
    """)
    op.execute('CREATE INDEX ix_password_resets_user ON password_resets ("userId", "createdAt" DESC)')


def downgrade():
    op.execute("DROP TABLE password_resets")
