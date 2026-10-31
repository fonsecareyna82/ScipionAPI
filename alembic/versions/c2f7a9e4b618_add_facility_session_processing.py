"""Add the processing of a session's datasets: its template, and each DATA's project.

A session names the workflow template its DATA are processed with (one of the workflows the web lists: local
or from WorkflowHub) and whether that happens by itself, as EMhub does: when a DATA's first movie has been
read, a project is made for it from the template, filled with what the movie says, and launched in streaming.
Each DATA keeps its project (SET NULL: deleting the project leaves the dataset) and how its processing went.

Revision ID: c2f7a9e4b618
Revises: b5e9d3a1c704
"""
from alembic import op


revision = "c2f7a9e4b618"
down_revision = "b5e9d3a1c704"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE facility_sessions
            ADD COLUMN "templateId" TEXT NOT NULL DEFAULT '',
            ADD COLUMN "autoProcess" BOOLEAN NOT NULL DEFAULT TRUE
    """)
    op.execute("""
        ALTER TABLE facility_session_datasets
            ADD COLUMN "projectId" INTEGER REFERENCES projects(id) ON DELETE SET NULL,
            ADD COLUMN processing JSONB
    """)


def downgrade():
    op.execute('ALTER TABLE facility_session_datasets DROP COLUMN "projectId", DROP COLUMN processing')
    op.execute('ALTER TABLE facility_sessions DROP COLUMN "templateId", DROP COLUMN "autoProcess"')
