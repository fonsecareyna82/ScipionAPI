"""What a help chat conversation is: an ordinary one ('') or the tutor guiding a new user step by step ('tutor').

Revision ID: b6e2d9f4a158
Revises: a9d4e2c7f031
"""
from alembic import op


revision = "b6e2d9f4a158"
down_revision = "a9d4e2c7f031"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE assistant_conversations ADD COLUMN mode TEXT NOT NULL DEFAULT ''")


def downgrade():
    op.execute("ALTER TABLE assistant_conversations DROP COLUMN mode")
