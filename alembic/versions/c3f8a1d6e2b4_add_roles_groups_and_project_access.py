"""Roles made of permissions, groups of users, and access levels when sharing a project.

An administrator creates roles (sets of the permissions the code checks) and
gives them to users and to groups; a user holds the permissions of their own
roles and of their groups' roles. Administrator is the system role: it holds
every permission and cannot be changed. Existing administrators get it, every
other user gets User. A project is now shared with a user or with a group, at
one of three levels: view, work or manage. The former "full" shares let their
users work on the project but not delete or share it, so they become "work".

Revision ID: c3f8a1d6e2b4
Revises: b7d2e9f41c08
"""
from alembic import op


revision = "c3f8a1d6e2b4"
down_revision = "b7d2e9f41c08"
branch_labels = None
depends_on = None

# The catalogue as it was when the roles were introduced (app/backend/api/permissions.py)
_ROLES = (
    ("Administrator", "Everything, now and in the future", True, False, ()),
    ("Facility manager", "Runs the facility: users, groups, microscopes and templates", False, False,
     ("users.manage", "groups.manage", "projects.create", "projects.share", "projects.viewAll",
      "files.browseServer", "files.download", "facility.monitor", "facility.thresholds", "facility.sessions",
      "facility.manage")),
    ("Technician", "Facility staff: sessions, the monitor and the projects of the facility", False, False,
     ("projects.create", "projects.share", "projects.viewAll", "files.browseServer", "files.download",
      "facility.monitor", "facility.thresholds", "facility.sessions")),
    ("User", "Works on their own projects and the ones shared with them", False, True,
     ("projects.create", "projects.share", "files.download")),
    ("Guest", "Only sees what is shared with them", False, False, ()),
)


def upgrade():
    op.execute("""
        CREATE TABLE access_roles (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            "isSystem" BOOLEAN NOT NULL DEFAULT FALSE,
            "isDefault" BOOLEAN NOT NULL DEFAULT FALSE,
            "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE access_role_permissions (
            "roleId" INTEGER NOT NULL REFERENCES access_roles(id) ON DELETE CASCADE,
            permission TEXT NOT NULL,
            PRIMARY KEY ("roleId", permission)
        )
    """)
    op.execute("""
        CREATE TABLE user_access_roles (
            "userId" INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            "roleId" INTEGER NOT NULL REFERENCES access_roles(id) ON DELETE CASCADE,
            PRIMARY KEY ("userId", "roleId")
        )
    """)
    op.execute("""
        CREATE TABLE user_groups (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE user_group_members (
            "groupId" INTEGER NOT NULL REFERENCES user_groups(id) ON DELETE CASCADE,
            "userId" INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            "groupRole" TEXT NOT NULL DEFAULT 'member' CHECK ("groupRole" IN ('member', 'pi')),
            PRIMARY KEY ("groupId", "userId")
        )
    """)
    op.execute('CREATE INDEX idx_user_group_members_user ON user_group_members ("userId")')
    op.execute("""
        CREATE TABLE user_group_roles (
            "groupId" INTEGER NOT NULL REFERENCES user_groups(id) ON DELETE CASCADE,
            "roleId" INTEGER NOT NULL REFERENCES access_roles(id) ON DELETE CASCADE,
            PRIMARY KEY ("groupId", "roleId")
        )
    """)

    for name, description, isSystem, isDefault, permissions in _ROLES:
        op.execute(
            "INSERT INTO access_roles (name, description, \"isSystem\", \"isDefault\") VALUES (%s, %s, %s, %s)"
            % (_literal(name), _literal(description), isSystem, isDefault))
        for permission in permissions:
            op.execute(
                "INSERT INTO access_role_permissions (\"roleId\", permission) "
                "SELECT id, %s FROM access_roles WHERE name = %s" % (_literal(permission), _literal(name)))
    op.execute("""
        INSERT INTO user_access_roles ("userId", "roleId")
        SELECT u.id, r.id
          FROM users u
          JOIN access_roles r ON r.name = CASE WHEN LOWER(COALESCE(u.role, '')) = 'admin'
                                               THEN 'Administrator' ELSE 'User' END
    """)

    # Projects are shared with a user or with a group, at a level
    op.execute('ALTER TABLE project_shares ALTER COLUMN "userId" DROP NOT NULL')
    op.execute('ALTER TABLE project_shares ADD COLUMN "groupId" INTEGER '
               'REFERENCES user_groups(id) ON DELETE CASCADE')
    op.execute("""
        ALTER TABLE project_shares ADD CONSTRAINT ck_project_shares_one_target
            CHECK (("userId" IS NULL) <> ("groupId" IS NULL))
    """)
    op.execute('CREATE UNIQUE INDEX ux_project_shares_project_group ON project_shares ("projectId", "groupId") '
               'WHERE "groupId" IS NOT NULL')
    op.execute("UPDATE project_shares SET permission = 'work' WHERE permission NOT IN ('view', 'work', 'manage')")
    op.execute("ALTER TABLE project_shares ALTER COLUMN permission SET DEFAULT 'work'")
    op.execute("""
        ALTER TABLE project_shares ADD CONSTRAINT ck_project_shares_level
            CHECK (permission IN ('view', 'work', 'manage'))
    """)


def downgrade():
    op.execute("ALTER TABLE project_shares DROP CONSTRAINT IF EXISTS ck_project_shares_level")
    op.execute("UPDATE project_shares SET permission = 'full'")
    op.execute("ALTER TABLE project_shares ALTER COLUMN permission SET DEFAULT 'full'")
    op.execute("DROP INDEX IF EXISTS ux_project_shares_project_group")
    op.execute("DELETE FROM project_shares WHERE \"groupId\" IS NOT NULL")
    op.execute("ALTER TABLE project_shares DROP CONSTRAINT IF EXISTS ck_project_shares_one_target")
    op.execute('ALTER TABLE project_shares DROP COLUMN IF EXISTS "groupId"')
    op.execute('ALTER TABLE project_shares ALTER COLUMN "userId" SET NOT NULL')
    for table in ("user_group_roles", "user_group_members", "user_groups", "user_access_roles",
                  "access_role_permissions", "access_roles"):
        op.execute("DROP TABLE IF EXISTS %s" % table)


def _literal(text):
    return "'%s'" % str(text).replace("'", "''")

