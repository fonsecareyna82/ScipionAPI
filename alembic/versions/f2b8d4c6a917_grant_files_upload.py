"""Give the new files.upload permission to the roles that may download files.

Uploading from one's computer into a project's Uploads folder is new; the roles
of an existing installation that hold files.download (User, Technician and
Facility manager, as created, or an administrator's own) get it too, as new
installations do. The Administrator role holds every permission anyway.

Revision ID: f2b8d4c6a917
Revises: e6c1b9a4d203
"""
from alembic import op


revision = "f2b8d4c6a917"
down_revision = "e6c1b9a4d203"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        INSERT INTO access_role_permissions ("roleId", permission)
        SELECT "roleId", 'files.upload'
          FROM access_role_permissions
         WHERE permission = 'files.download'
        ON CONFLICT DO NOTHING
    """)


def downgrade():
    op.execute("DELETE FROM access_role_permissions WHERE permission = 'files.upload'")
