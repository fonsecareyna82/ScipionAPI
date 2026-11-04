"""Add the facility's bookable resources and their bookings.

A resource is what is booked: a microscope (linked to it, so its confirmed bookings become its sessions), a
plunger, a high-pressure freezer, a confocal… each with how it is charged (by session, hour, half hour or as a
service), the shortest and longest booking a user may ask for, and when its day starts (the Talos' runs from
09:00 to 08:59 the next day).

A booking is a request of a user (requested) that the facility confirms, answers with another time
(alternative, which the user accepts or declines), or rejects; the facility books directly too, and blocks a
resource for downtime, maintenance or a special use. Two confirmed bookings of a resource never overlap (checked
by the service with the resource locked). Its priority is the request's level (0 the facility … 4 external),
copied when it is made and changed only by the facility. A confirmed booking of a microscope that runs sessions
has its planned session.

Each microscope gets its resource here.

Revision ID: c4e9a2f7b351
Revises: b8e3d1a5f629
"""
from alembic import op


revision = "c4e9a2f7b351"
down_revision = "b8e3d1a5f629"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE facility_resources (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            "microscopeId" INTEGER REFERENCES facility_microscopes(id) ON DELETE SET NULL,
            color TEXT NOT NULL DEFAULT '',
            unit TEXT NOT NULL DEFAULT 'session',
            "minHours" DOUBLE PRECISION,
            "maxHours" DOUBLE PRECISION,
            "dayStart" TEXT NOT NULL DEFAULT '09:00',
            "requiresAuthorization" BOOLEAN NOT NULL DEFAULT FALSE,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            notes TEXT NOT NULL DEFAULT '',
            "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ux_facility_resources_name UNIQUE (name),
            CONSTRAINT ux_facility_resources_microscope UNIQUE ("microscopeId"),
            CONSTRAINT ck_facility_resources_unit CHECK (unit IN ('session', 'hour', 'half_hour', 'service')),
            CONSTRAINT ck_facility_resources_hours CHECK (
                ("minHours" IS NULL OR "minHours" > 0) AND ("maxHours" IS NULL OR "maxHours" > 0)
                AND ("minHours" IS NULL OR "maxHours" IS NULL OR "minHours" <= "maxHours"))
        )
    """)
    op.execute("""
        CREATE TABLE facility_bookings (
            id SERIAL PRIMARY KEY,
            "resourceId" INTEGER NOT NULL REFERENCES facility_resources(id) ON DELETE RESTRICT,
            kind TEXT NOT NULL DEFAULT 'booking',
            status TEXT NOT NULL DEFAULT 'requested',
            "startsAt" TIMESTAMPTZ NOT NULL,
            "endsAt" TIMESTAMPTZ NOT NULL,
            "proposedStartsAt" TIMESTAMPTZ,
            "proposedEndsAt" TIMESTAMPTZ,
            title TEXT NOT NULL DEFAULT '',
            "ownerId" INTEGER REFERENCES users(id) ON DELETE SET NULL,
            "groupId" INTEGER REFERENCES user_groups(id) ON DELETE SET NULL,
            "operatorId" INTEGER REFERENCES users(id) ON DELETE SET NULL,
            technique TEXT,
            priority INTEGER,
            justification TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            "requestedBy" INTEGER REFERENCES users(id) ON DELETE SET NULL,
            "decidedBy" INTEGER REFERENCES users(id) ON DELETE SET NULL,
            "decidedAt" TIMESTAMPTZ,
            "decisionReason" TEXT NOT NULL DEFAULT '',
            "sessionId" INTEGER REFERENCES facility_sessions(id) ON DELETE SET NULL,
            "createdAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            "updatedAt" TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_facility_bookings_kind CHECK (kind IN ('booking', 'downtime', 'maintenance', 'special')),
            CONSTRAINT ck_facility_bookings_status CHECK (
                status IN ('requested', 'confirmed', 'alternative', 'rejected', 'cancelled')),
            CONSTRAINT ck_facility_bookings_times CHECK ("endsAt" > "startsAt"),
            CONSTRAINT ck_facility_bookings_proposed CHECK (
                ("proposedStartsAt" IS NULL AND "proposedEndsAt" IS NULL)
                OR ("proposedStartsAt" IS NOT NULL AND "proposedEndsAt" > "proposedStartsAt")),
            CONSTRAINT ck_facility_bookings_technique CHECK (technique IS NULL OR technique IN ('spa', 'tomo')),
            CONSTRAINT ck_facility_bookings_priority CHECK (priority IS NULL OR priority BETWEEN 0 AND 4)
        )
    """)
    op.execute('CREATE INDEX ix_facility_bookings_resource_time ON facility_bookings ("resourceId", "startsAt")')
    op.execute('CREATE INDEX ix_facility_bookings_owner ON facility_bookings ("ownerId")')
    op.execute('CREATE INDEX ix_facility_bookings_status ON facility_bookings (status)')
    op.execute('CREATE UNIQUE INDEX ux_facility_bookings_session ON facility_bookings ("sessionId") '
               'WHERE "sessionId" IS NOT NULL')
    op.execute("""
        INSERT INTO facility_resources (name, "microscopeId")
        SELECT name, id FROM facility_microscopes ORDER BY id
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS facility_bookings")
    op.execute("DROP TABLE IF EXISTS facility_resources")
