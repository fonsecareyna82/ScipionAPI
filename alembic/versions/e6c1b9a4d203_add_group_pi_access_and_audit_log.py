"""What a group's PIs may do in its members' projects, and the audit log.

Each group says the access its PIs get to the projects its members own (none, view, work or
manage; view to start with). The audit log keeps who did what to whom: sign-ins, accounts,
roles, groups, sharing, settings, plugins and workers. The actor's email is kept with the
event, so it still reads when the account is deleted.

Revision ID: e6c1b9a4d203
Revises: d4a7c2e8f915
"""
from alembic import op


revision = "e6c1b9a4d203"
down_revision = "d4a7c2e8f915"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE user_groups ADD COLUMN IF NOT EXISTS "piAccess" TEXT NOT NULL DEFAULT 'view'
            CHECK ("piAccess" IN ('none', 'view', 'work', 'manage'))
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_events (
            id BIGSERIAL PRIMARY KEY,
            "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "userId" INTEGER REFERENCES users(id) ON DELETE SET NULL,
            "userEmail" TEXT,
            action TEXT NOT NULL,
            "targetType" TEXT,
            "targetId" TEXT,
            "targetName" TEXT,
            details JSONB NOT NULL DEFAULT '{}'::JSONB,
            "clientAddress" TEXT
        )
    """)
    op.execute('CREATE INDEX IF NOT EXISTS idx_audit_events_created ON audit_events ("createdAt" DESC, id DESC)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_audit_events_user ON audit_events ("userId", "createdAt" DESC)')
    op.execute('CREATE INDEX IF NOT EXISTS idx_audit_events_action ON audit_events (action, "createdAt" DESC)')


def downgrade():
    op.execute("DROP TABLE IF EXISTS audit_events")
    op.execute('ALTER TABLE user_groups DROP COLUMN IF EXISTS "piAccess"')
