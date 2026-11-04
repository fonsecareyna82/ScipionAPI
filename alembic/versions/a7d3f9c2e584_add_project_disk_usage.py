"""Measure the disk each project uses, and give each user a folder of their own for their projects.

project_disk_usage keeps the last measure of each project (what it takes on the disk, in all and in its Runs and
Uploads folders), when it was made, and when someone asked for a new one; a background measurer of the API keeps
it up to date. users.projectsFolder is the folder, under the projects folder, where a user's new projects go
(like each user's ScipionUserData in Scipion): chosen when they make their first project and kept afterwards.
Projects made before stay where they are.

The new storage.view permission (every user's, group's and project's disk) goes to the roles that manage users.

Revision ID: a7d3f9c2e584
Revises: c4e9a2f7b351
"""
from alembic import op


revision = "a7d3f9c2e584"
down_revision = "c4e9a2f7b351"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE users ADD COLUMN "projectsFolder" TEXT')
    op.execute('CREATE UNIQUE INDEX ux_users_projects_folder ON users ("projectsFolder") '
               'WHERE "projectsFolder" IS NOT NULL')
    op.execute("""
        CREATE TABLE project_disk_usage (
            "projectId" INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
            "totalBytes" BIGINT,
            files BIGINT,
            "runsBytes" BIGINT,
            "uploadsBytes" BIGINT,
            location TEXT,
            "measuredPath" TEXT,
            "measuredAt" TIMESTAMPTZ,
            "durationSeconds" REAL,
            error TEXT,
            "startedAt" TIMESTAMPTZ,
            "requestedAt" TIMESTAMPTZ
        )
    """)
    op.execute("""
        INSERT INTO access_role_permissions ("roleId", permission)
        SELECT "roleId", 'storage.view'
          FROM access_role_permissions
         WHERE permission = 'users.manage'
        ON CONFLICT DO NOTHING
    """)


def downgrade():
    op.execute("DELETE FROM access_role_permissions WHERE permission = 'storage.view'")
    op.execute("DROP TABLE project_disk_usage")
    op.execute("DROP INDEX ux_users_projects_folder")
    op.execute('ALTER TABLE users DROP COLUMN "projectsFolder"')
