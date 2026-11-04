"""The queries of the facility's bookable resources and their bookings."""
from typing import Any, Dict, List, Optional

RESOURCE_FIELDS = ("name", "microscopeId", "color", "unit", "minHours", "maxHours", "dayStart",
                   "requiresAuthorization", "active", "notes")
BOOKING_FIELDS = ("resourceId", "kind", "status", "startsAt", "endsAt", "proposedStartsAt", "proposedEndsAt", "title",
                  "ownerId", "groupId", "operatorId", "technique", "priority", "justification", "notes",
                  "requestedBy", "decidedBy", "decidedAt", "decisionReason", "sessionId")


def _quoted(field: str) -> str:
    return '"%s"' % field if field != field.lower() else field


LIST_RESOURCES_SQL = """
    SELECT r.id, r.name, r."microscopeId", m.name AS "microscopeName",
           COALESCE(m."sessionsEnabled", FALSE) AS "runsSessions", r.color, r.unit, r."minHours", r."maxHours",
           r."dayStart", r."requiresAuthorization", r.active, r.notes, r."createdAt", r."updatedAt"
      FROM facility_resources r
      LEFT JOIN facility_microscopes m ON m.id = r."microscopeId"
"""

# A microscope made after the resources were: it gets its own
ADD_MICROSCOPE_RESOURCES_SQL = """
    INSERT INTO facility_resources (name, "microscopeId")
    SELECT m.name || CASE WHEN EXISTS (SELECT 1 FROM facility_resources o WHERE o.name = m.name)
                          THEN ' (' || m.id || ')' ELSE '' END, m.id
      FROM facility_microscopes m
     WHERE NOT EXISTS (SELECT 1 FROM facility_resources r WHERE r."microscopeId" = m.id)
"""

INSERT_RESOURCE_SQL = "INSERT INTO facility_resources (%s) VALUES (%s) RETURNING id" % (
    ", ".join(_quoted(field) for field in RESOURCE_FIELDS), ", ".join("%%(%s)s" % field for field in RESOURCE_FIELDS))
UPDATE_RESOURCE_SQL = 'UPDATE facility_resources SET %s, "updatedAt" = NOW() WHERE id = %%(id)s' % ", ".join(
    "%s = %%(%s)s" % (_quoted(field), field) for field in RESOURCE_FIELDS)

_PERSON = "TRIM(COALESCE(%s.\"firstName\", '') || ' ' || COALESCE(%s.\"lastName\", ''))"

LIST_BOOKINGS_SQL = """
    SELECT b.id, b."resourceId", r.name AS "resourceName", r.color AS "resourceColor", r."microscopeId",
           b.kind, b.status, b."startsAt", b."endsAt", b."proposedStartsAt", b."proposedEndsAt", b.title,
           b."ownerId", """ + _PERSON % ("o", "o") + """ AS "ownerName", o.email AS "ownerEmail",
           b."groupId", g.name AS "groupName",
           b."operatorId", """ + _PERSON % ("op", "op") + """ AS "operatorName",
           b.technique, b.priority, b.justification, b.notes,
           b."requestedBy", """ + _PERSON % ("rq", "rq") + """ AS "requestedByName",
           b."decidedBy", """ + _PERSON % ("dc", "dc") + """ AS "decidedByName", b."decidedAt", b."decisionReason",
           b."sessionId", s.name AS "sessionName", s.status AS "sessionStatus", b."createdAt", b."updatedAt"
      FROM facility_bookings b
      JOIN facility_resources r ON r.id = b."resourceId"
      LEFT JOIN users o ON o.id = b."ownerId"
      LEFT JOIN users op ON op.id = b."operatorId"
      LEFT JOIN users rq ON rq.id = b."requestedBy"
      LEFT JOIN users dc ON dc.id = b."decidedBy"
      LEFT JOIN user_groups g ON g.id = b."groupId"
      LEFT JOIN facility_sessions s ON s.id = b."sessionId"
"""

INSERT_BOOKING_SQL = "INSERT INTO facility_bookings (%s) VALUES (%s) RETURNING id" % (
    ", ".join(_quoted(field) for field in BOOKING_FIELDS), ", ".join("%%(%s)s" % field for field in BOOKING_FIELDS))
UPDATE_BOOKING_SQL = 'UPDATE facility_bookings SET %s, "updatedAt" = NOW() WHERE id = %%(id)s' % ", ".join(
    "%s = %%(%s)s" % (_quoted(field), field) for field in BOOKING_FIELDS)

# The confirmed bookings and blocks of a resource that take some of a time (another than the one being saved)
OVERLAPS_SQL = """
    SELECT b.id, b.kind, b."startsAt", b."endsAt", b.title
      FROM facility_bookings b
     WHERE b."resourceId" = %(resourceId)s AND b.status = 'confirmed' AND b.id <> %(id)s
       AND b."startsAt" < %(endsAt)s AND b."endsAt" > %(startsAt)s
     ORDER BY b."startsAt"
"""


class FacilityBookingPostgresqlMapper:
    def __init__(self, db):
        self.db = db

    # Resources ---------------------------------------------------------------------------------
    def listResources(self, activeOnly: bool = False) -> List[Dict[str, Any]]:
        self.db.execute(ADD_MICROSCOPE_RESOURCES_SQL)
        where = " WHERE r.active" if activeOnly else ""
        return [dict(row) for row in self.db.fetchAll(LIST_RESOURCES_SQL + where + " ORDER BY r.name, r.id") or []]

    def getResource(self, resourceId: int) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne(LIST_RESOURCES_SQL + " WHERE r.id = %s", (int(resourceId),))
        return dict(row) if row else None

    def findResourceIdByName(self, name: str) -> Optional[int]:
        row = self.db.fetchOne("SELECT id FROM facility_resources WHERE LOWER(name) = LOWER(%s)", (name,))
        return int(row["id"]) if row else None

    def resourceIdOfMicroscope(self, microscopeId: int) -> Optional[int]:
        row = self.db.fetchOne('SELECT id FROM facility_resources WHERE "microscopeId" = %s', (int(microscopeId),))
        return int(row["id"]) if row else None

    def microscopeExists(self, microscopeId: int) -> bool:
        return self.db.fetchOne("SELECT 1 AS found FROM facility_microscopes WHERE id = %s",
                                (int(microscopeId),)) is not None

    def saveResource(self, values: Dict[str, Any], resourceId: Optional[int] = None) -> int:
        params = {field: values[field] for field in RESOURCE_FIELDS}
        if resourceId is None:
            return int(self.db.executeReturningOne(INSERT_RESOURCE_SQL, params)["id"])
        self.db.execute(UPDATE_RESOURCE_SQL, dict(params, id=int(resourceId)))
        return int(resourceId)

    def resourceHasBookings(self, resourceId: int) -> bool:
        return self.db.fetchOne('SELECT 1 AS found FROM facility_bookings WHERE "resourceId" = %s LIMIT 1',
                                (int(resourceId),)) is not None

    def deleteResource(self, resourceId: int) -> None:
        self.db.execute("DELETE FROM facility_resources WHERE id = %s", (int(resourceId),))

    # Bookings ----------------------------------------------------------------------------------
    def listBookings(self, start=None, end=None, resourceIds: Optional[List[int]] = None,
                     statuses: Optional[List[str]] = None, ownerId: Optional[int] = None) -> List[Dict[str, Any]]:
        conditions, params = [], []
        if start is not None:
            conditions.append('COALESCE(GREATEST(b."endsAt", b."proposedEndsAt"), b."endsAt") > %s')
            params.append(start)
        if end is not None:
            conditions.append('COALESCE(LEAST(b."startsAt", b."proposedStartsAt"), b."startsAt") < %s')
            params.append(end)
        if resourceIds:
            conditions.append('b."resourceId" = ANY(%s)')
            params.append([int(resourceId) for resourceId in resourceIds])
        if statuses:
            conditions.append("b.status = ANY(%s)")
            params.append(list(statuses))
        if ownerId is not None:
            conditions.append('b."ownerId" = %s')
            params.append(int(ownerId))
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        order = ' ORDER BY b."startsAt", b.id'
        return [dict(row) for row in self.db.fetchAll(LIST_BOOKINGS_SQL + where + order, tuple(params)) or []]

    def getBooking(self, bookingId: int) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne(LIST_BOOKINGS_SQL + " WHERE b.id = %s", (int(bookingId),))
        return dict(row) if row else None

    def bookingOfSession(self, sessionId: int) -> Optional[int]:
        row = self.db.fetchOne('SELECT id FROM facility_bookings WHERE "sessionId" = %s', (int(sessionId),))
        return int(row["id"]) if row else None

    def lockResource(self, resourceId: int) -> None:
        """Hold a resource until the transaction ends: two saves of its bookings cannot both pass the check."""
        self.db.execute("SELECT id FROM facility_resources WHERE id = %s FOR UPDATE", (int(resourceId),), commit=False)

    def overlaps(self, resourceId: int, startsAt, endsAt, bookingId: Optional[int] = None) -> List[Dict[str, Any]]:
        rows = self.db.fetchAll(OVERLAPS_SQL, {"resourceId": int(resourceId), "startsAt": startsAt, "endsAt": endsAt,
                                               "id": int(bookingId) if bookingId is not None else -1})
        return [dict(row) for row in rows or []]

    def insertBooking(self, values: Dict[str, Any]) -> int:
        return int(self.db.executeReturningOne(INSERT_BOOKING_SQL, {field: values[field] for field in BOOKING_FIELDS})["id"])

    def updateBooking(self, bookingId: int, values: Dict[str, Any]) -> None:
        self.db.execute(UPDATE_BOOKING_SQL, dict({field: values[field] for field in BOOKING_FIELDS},
                                                 id=int(bookingId)), commit=False)

    def localDate(self, moment, timezone: str):
        """The day a moment falls on in the facility's time zone."""
        return self.db.fetchOne("SELECT (%s::TIMESTAMPTZ AT TIME ZONE %s)::DATE AS day", (moment, timezone))["day"]

    def timezoneExists(self, timezone: str) -> bool:
        return self.db.fetchOne("SELECT 1 AS found FROM pg_timezone_names WHERE name = %s", (timezone,)) is not None

    # People ------------------------------------------------------------------------------------
    def groupsOf(self, userId: int) -> List[Dict[str, Any]]:
        rows = self.db.fetchAll('SELECT g.id, g.name, m."groupRole" FROM user_group_members m '
                                'JOIN user_groups g ON g.id = m."groupId" WHERE m."userId" = %s ORDER BY g.name',
                                (int(userId),))
        return [dict(row) for row in rows or []]

    def getUser(self, userId: int) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne('SELECT id, email, "firstName", "lastName", "isActive" FROM users WHERE id = %s',
                               (int(userId),))
        return dict(row) if row else None

    def groupExists(self, groupId: int) -> bool:
        return self.db.fetchOne("SELECT 1 AS found FROM user_groups WHERE id = %s", (int(groupId),)) is not None
