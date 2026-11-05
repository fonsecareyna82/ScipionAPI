"""No limit on the protocols a user runs at once, by default.

maxConcurrentRunsPerUser was 4 by default, and Settings stores every instance value when it is saved: an
installation that saved its settings keeps that 4 as if someone had chosen it. A 4 becomes 0 (no limit), the new
default; any other value was chosen and stays.

Revision ID: b9e4c1d7a258
Revises: a7d3f9c2e584
"""
from alembic import op


revision = "b9e4c1d7a258"
down_revision = "a7d3f9c2e584"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE instance_settings
           SET settings = jsonb_set(settings, '{maxConcurrentRunsPerUser}', '0'::jsonb)
         WHERE settings ->> 'maxConcurrentRunsPerUser' = '4'
    """)


def downgrade():
    op.execute("""
        UPDATE instance_settings
           SET settings = jsonb_set(settings, '{maxConcurrentRunsPerUser}', '4'::jsonb)
         WHERE settings ->> 'maxConcurrentRunsPerUser' = '0'
    """)
