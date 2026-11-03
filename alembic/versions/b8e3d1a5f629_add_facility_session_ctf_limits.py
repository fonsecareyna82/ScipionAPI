"""Add the CTF limits of a session: what its micrographs must meet to go on.

The processing's CTF consensus drops the micrographs whose defocus is out of a range or whose CTF fits only to a
poor resolution. The facility uses the same numbers for every sample, set in its templates; a session may set
its own (a sample that needs more defocus, or a looser resolution), which are written into the CTF consensus of
each DATA's project. Null keeps the template's value.

Revision ID: b8e3d1a5f629
Revises: a2d6f9c4e817
"""
from alembic import op


revision = "b8e3d1a5f629"
down_revision = "a2d6f9c4e817"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE facility_sessions
            ADD COLUMN "ctfMinDefocus" DOUBLE PRECISION,
            ADD COLUMN "ctfMaxDefocus" DOUBLE PRECISION,
            ADD COLUMN "ctfMaxResolution" DOUBLE PRECISION
    """)


def downgrade():
    op.execute('ALTER TABLE facility_sessions DROP COLUMN "ctfMinDefocus", DROP COLUMN "ctfMaxDefocus", '
               'DROP COLUMN "ctfMaxResolution"')
