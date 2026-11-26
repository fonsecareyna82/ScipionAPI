"""How much each user asked the AI assistant each day, for its daily limit and for the administrators.

One row per user and day: the questions asked and the tokens the model read and wrote for them.

Revision ID: d5a1c7e3f902
Revises: b3e7d9f1c264
"""
from alembic import op


revision = "d5a1c7e3f902"
down_revision = "b3e7d9f1c264"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE assistant_usage (
            "userId" INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            day DATE NOT NULL,
            questions INTEGER NOT NULL DEFAULT 0,
            "inputTokens" BIGINT NOT NULL DEFAULT 0,
            "outputTokens" BIGINT NOT NULL DEFAULT 0,
            PRIMARY KEY ("userId", day)
        )
    """)


def downgrade():
    op.execute("DROP TABLE assistant_usage")
