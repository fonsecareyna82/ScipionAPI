"""Notifications for the users: in the web (the bell) and by mail, as each user chooses.

notifications is the outbox: every notice for a user (or, without one, for a mail address only: the facility's
alert list) with its state by mail. Nothing is mailed while a request waits: a background sender mails the pending
ones, retrying the failures, and the daily digest. notification_preferences keeps how each user wants each kind
(instant, digest, web, off); notification_settings the mail server (moved here from the facility's settings, so
ScipionWeb mails also without a facility), the public address of the web, the digest's hour and the defaults.

Revision ID: f8b2d6e4a193
Revises: d3a8f2c6b947
"""
from alembic import op


revision = "f8b2d6e4a193"
down_revision = "d3a8f2c6b947"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE notification_settings (
            key TEXT PRIMARY KEY,
            value JSONB NOT NULL,
            "updatedBy" INTEGER REFERENCES users(id) ON DELETE SET NULL,
            "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE notifications (
            id BIGSERIAL PRIMARY KEY,
            "userId" INTEGER REFERENCES users(id) ON DELETE CASCADE,
            email TEXT,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            link TEXT NOT NULL DEFAULT '',
            "inWeb" BOOLEAN NOT NULL DEFAULT TRUE,
            "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "readAt" TIMESTAMPTZ,
            "emailState" TEXT NOT NULL DEFAULT 'pending',
            "emailAttempts" INTEGER NOT NULL DEFAULT 0,
            "emailNextAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "emailedAt" TIMESTAMPTZ,
            "emailError" TEXT,
            CONSTRAINT ck_notifications_email_state CHECK ("emailState" IN ('pending', 'digest', 'sent', 'failed', 'skipped')),
            CONSTRAINT ck_notifications_recipient CHECK ("userId" IS NOT NULL OR email IS NOT NULL)
        )
    """)
    op.execute('CREATE INDEX ix_notifications_user ON notifications ("userId", "createdAt" DESC)')
    op.execute('CREATE INDEX ix_notifications_pending ON notifications ("emailNextAt") WHERE "emailState" = \'pending\'')
    op.execute('CREATE INDEX ix_notifications_digest ON notifications ("userId") WHERE "emailState" = \'digest\'')
    op.execute("""
        CREATE TABLE notification_preferences (
            "userId" INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            channel TEXT NOT NULL,
            PRIMARY KEY ("userId", kind),
            CONSTRAINT ck_notification_preferences_channel CHECK (channel IN ('instant', 'digest', 'web', 'off'))
        )
    """)
    # The mail server the facility had becomes everyone's; its list of alert addresses stays the facility's
    op.execute("""
        INSERT INTO notification_settings (key, value, "updatedBy", "updatedAt")
        SELECT 'mail', value - 'recipients', "updatedBy", "updatedAt" FROM facility_settings WHERE key = 'mail'
    """)
    op.execute("""
        INSERT INTO facility_settings (key, value, "updatedBy", "updatedAt")
        SELECT 'alertRecipients', TO_JSONB(COALESCE(value->>'recipients', '')), "updatedBy", "updatedAt"
          FROM facility_settings WHERE key = 'mail'
    """)
    op.execute("DELETE FROM facility_settings WHERE key = 'mail'")


def downgrade():
    op.execute("""
        INSERT INTO facility_settings (key, value, "updatedBy", "updatedAt")
        SELECT 'mail', m.value || JSONB_BUILD_OBJECT('recipients', COALESCE(
                   (SELECT r.value #>> '{}' FROM facility_settings r WHERE r.key = 'alertRecipients'), '')),
               m."updatedBy", m."updatedAt"
          FROM notification_settings m WHERE m.key = 'mail'
    """)
    op.execute("DELETE FROM facility_settings WHERE key = 'alertRecipients'")
    op.execute("DROP TABLE notification_preferences")
    op.execute("DROP TABLE notifications")
    op.execute("DROP TABLE notification_settings")
