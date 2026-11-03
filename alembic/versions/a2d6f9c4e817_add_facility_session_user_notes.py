"""Add the notes of a session its user sees.

A session's notes are the staff's; userNotes are what the technician tells its user (and the group's PI), who
see the session in "My sessions".

Revision ID: a2d6f9c4e817
Revises: f1c5b8e3a926
"""
from alembic import op


revision = "a2d6f9c4e817"
down_revision = "f1c5b8e3a926"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE facility_sessions ADD COLUMN "userNotes" TEXT NOT NULL DEFAULT \'\'')


def downgrade():
    op.execute('ALTER TABLE facility_sessions DROP COLUMN "userNotes"')
