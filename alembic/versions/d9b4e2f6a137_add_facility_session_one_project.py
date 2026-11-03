"""Let a session process all its DATA in one project.

Multigrid: grids of one session may be different samples (or tilted and not), each best in its own project,
or one sample at different concentrations or sampling, wanted together. oneProject (off: a project per DATA)
puts every DATA in the session's project, each in its own branch of the template's workflow.

Revision ID: d9b4e2f6a137
Revises: c2f7a9e4b618
"""
from alembic import op


revision = "d9b4e2f6a137"
down_revision = "c2f7a9e4b618"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE facility_sessions ADD COLUMN "oneProject" BOOLEAN NOT NULL DEFAULT FALSE')


def downgrade():
    op.execute('ALTER TABLE facility_sessions DROP COLUMN "oneProject"')
