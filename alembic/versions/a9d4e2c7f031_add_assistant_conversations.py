"""The help chat's conversations: each user's own, with their messages, to go back to them later.

An assistant message keeps its whole answer (text, cards, steps) to be shown again as it was.

Revision ID: a9d4e2c7f031
Revises: f3c8a6d1b527
"""
from alembic import op


revision = "a9d4e2c7f031"
down_revision = "f3c8a6d1b527"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE assistant_conversations (
            id SERIAL PRIMARY KEY,
            "userId" INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            "projectId" INTEGER REFERENCES projects(id) ON DELETE SET NULL,
            title TEXT NOT NULL DEFAULT '',
            "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute('CREATE INDEX assistant_conversations_user ON assistant_conversations ("userId", "updatedAt" DESC)')
    op.execute("""
        CREATE TABLE assistant_messages (
            id SERIAL PRIMARY KEY,
            "conversationId" INTEGER NOT NULL REFERENCES assistant_conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            text TEXT NOT NULL DEFAULT '',
            answer JSONB,
            "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute('CREATE INDEX assistant_messages_conversation ON assistant_messages ("conversationId", id)')


def downgrade():
    op.execute("DROP TABLE assistant_messages")
    op.execute("DROP TABLE assistant_conversations")
