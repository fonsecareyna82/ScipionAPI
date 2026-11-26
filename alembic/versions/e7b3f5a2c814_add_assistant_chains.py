"""The chains of protocols the AI assistant added from a template, to run them stretch by stretch.

A chain keeps its protocols in order, each one's parents inside it, its stops (after which it waits for the user),
the stops already passed and the protocols launched.

Revision ID: e7b3f5a2c814
Revises: d5a1c7e3f902
"""
from alembic import op


revision = "e7b3f5a2c814"
down_revision = "d5a1c7e3f902"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE assistant_chains (
            id SERIAL PRIMARY KEY,
            "projectId" INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            "userId" INTEGER REFERENCES users(id) ON DELETE SET NULL,
            "templateId" TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            "protocolIds" JSONB NOT NULL DEFAULT '[]'::JSONB,
            parents JSONB NOT NULL DEFAULT '{}'::JSONB,
            stops JSONB NOT NULL DEFAULT '[]'::JSONB,
            passed JSONB NOT NULL DEFAULT '[]'::JSONB,
            launched JSONB NOT NULL DEFAULT '[]'::JSONB,
            "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute('CREATE INDEX assistant_chains_project ON assistant_chains ("projectId")')


def downgrade():
    op.execute("DROP TABLE assistant_chains")
