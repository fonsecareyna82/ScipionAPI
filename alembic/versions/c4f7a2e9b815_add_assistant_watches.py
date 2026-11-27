"""The streams the assistant watches for a user: until when, how the stream was when it began, and what it already
told.

Revision ID: c4f7a2e9b815
Revises: b6e2d9f4a158
"""
from alembic import op


revision = "c4f7a2e9b815"
down_revision = "b6e2d9f4a158"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE assistant_watches (
            id SERIAL PRIMARY KEY,
            "userId" INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            "projectId" INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            until TIMESTAMPTZ NOT NULL,
            "endedAt" TIMESTAMPTZ,
            "endedReason" TEXT NOT NULL DEFAULT '',
            reference JSONB,
            state JSONB NOT NULL DEFAULT '{}'::JSONB
        )
    """)
    op.execute('CREATE UNIQUE INDEX assistant_watches_active ON assistant_watches ("userId", "projectId") '
               'WHERE "endedAt" IS NULL')


def downgrade():
    op.execute("DROP TABLE assistant_watches")
