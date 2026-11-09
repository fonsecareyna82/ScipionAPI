"""Disk quotas: how much the projects of a user, or of a group's members, may take.

A quota is a limit in bytes for a user or a group, set by an administrator; the projects count by their owner
(as measured in project_disk_usage). At 100 % new launches in those projects are refused (what runs goes on);
notifiedLevel keeps the last level told (80 or 100), so each is told once until usage drops again.

Revision ID: d7f3b1e9a462
Revises: c6e1a8d4f027
"""
from alembic import op


revision = "d7f3b1e9a462"
down_revision = "c6e1a8d4f027"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE storage_quotas (
            id SERIAL PRIMARY KEY,
            kind TEXT NOT NULL,
            "targetId" INTEGER NOT NULL,
            "limitBytes" BIGINT NOT NULL,
            "notifiedLevel" INTEGER NOT NULL DEFAULT 0,
            "updatedBy" INTEGER REFERENCES users(id) ON DELETE SET NULL,
            "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ux_storage_quotas_target UNIQUE (kind, "targetId"),
            CONSTRAINT ck_storage_quotas_kind CHECK (kind IN ('user', 'group')),
            CONSTRAINT ck_storage_quotas_limit CHECK ("limitBytes" > 0)
        )
    """)
    # A quota goes with its user or group
    op.execute("""
        CREATE FUNCTION storage_quotas_forget() RETURNS TRIGGER AS $$
        BEGIN
            DELETE FROM storage_quotas WHERE kind = TG_ARGV[0] AND "targetId" = OLD.id;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("CREATE TRIGGER storage_quotas_forget_user AFTER DELETE ON users "
               "FOR EACH ROW EXECUTE PROCEDURE storage_quotas_forget('user')")
    op.execute("CREATE TRIGGER storage_quotas_forget_group AFTER DELETE ON user_groups "
               "FOR EACH ROW EXECUTE PROCEDURE storage_quotas_forget('group')")


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS storage_quotas_forget_group ON user_groups")
    op.execute("DROP TRIGGER IF EXISTS storage_quotas_forget_user ON users")
    op.execute("DROP FUNCTION IF EXISTS storage_quotas_forget()")
    op.execute("DROP TABLE storage_quotas")
