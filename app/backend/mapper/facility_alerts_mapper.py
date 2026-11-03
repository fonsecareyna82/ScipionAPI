"""The queries of the facility's alerts: what is wrong now in the sessions, and the alerts kept for it."""
from typing import Any, Dict, Iterable, List, Optional

# What is wrong now, by kind: one row per DATA (and protocol), with what the alert says
CURRENT_SQL = {
    # A DATA acquiring whose newest movie is older than the stall time
    "stalled": """
        SELECT d.id AS "datasetId", d."sessionId", d."projectId", '' AS "protocolId", d.folder, s.name AS "sessionName",
               m.name AS "microscopeName", d."movieCount", d."lastMovieAt",
               EXTRACT(EPOCH FROM NOW() - d."lastMovieAt") / 60 AS minutes, NULL AS detail
          FROM facility_session_datasets d
          JOIN facility_sessions s ON s.id = d."sessionId"
          JOIN facility_microscopes m ON m.id = s."microscopeId"
         WHERE s.status = 'acquiring' AND d.kind = 'data' AND d."movieCount" > 0
           AND d."lastMovieAt" < NOW() - %(stall)s * INTERVAL '1 minute'
    """,
    # A DATA whose project could not be made or launched
    "processingFailed": """
        SELECT d.id AS "datasetId", d."sessionId", d."projectId", '' AS "protocolId", d.folder, s.name AS "sessionName",
               m.name AS "microscopeName", d."movieCount", d."lastMovieAt", NULL AS minutes,
               d.processing->>'message' AS detail
          FROM facility_session_datasets d
          JOIN facility_sessions s ON s.id = d."sessionId"
          JOIN facility_microscopes m ON m.id = s."microscopeId"
         WHERE s.status = 'acquiring' AND d.kind = 'data' AND d.processing->>'state' = 'error'
    """,
    # A failed protocol of a DATA's project (a project shared by DATA: told once, on its first DATA)
    "protocolFailed": """
        SELECT DISTINCT ON (p."projectId", p."protocolId")
               d.id AS "datasetId", d."sessionId", d."projectId", p."protocolId"::TEXT AS "protocolId", d.folder,
               s.name AS "sessionName", m.name AS "microscopeName", d."movieCount", d."lastMovieAt", NULL AS minutes,
               p."protocolClassName" AS detail
          FROM protocols p
          JOIN facility_session_datasets d ON d."projectId" = p."projectId"
          JOIN facility_sessions s ON s.id = d."sessionId"
          JOIN facility_microscopes m ON m.id = s."microscopeId"
         WHERE s.status IN ('acquiring', 'finished') AND p.status = 'failed'
         ORDER BY p."projectId", p."protocolId", d.id
    """,
}

OPEN_ALERT_SQL = """
    INSERT INTO facility_alerts (kind, "sessionId", "datasetId", "projectId", "protocolId", message)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (kind, "datasetId", "protocolId") WHERE "resolvedAt" IS NULL DO NOTHING
    RETURNING id
"""

LIST_ALERTS_SQL = """
    SELECT a.id, a.kind, a."sessionId", s.name AS "sessionName", a."datasetId", d.folder, a."projectId", a."protocolId",
           m.name AS "microscopeName", a.message, a."openedAt", a."resolvedAt", a."acknowledgedAt",
           a."acknowledgedBy", TRIM(COALESCE(u."firstName", '') || ' ' || COALESCE(u."lastName", '')) AS "acknowledgedByName",
           u.email AS "acknowledgedByEmail", a."emailedAt", a."emailError"
      FROM facility_alerts a
      JOIN facility_sessions s ON s.id = a."sessionId"
      JOIN facility_session_datasets d ON d.id = a."datasetId"
      JOIN facility_microscopes m ON m.id = s."microscopeId"
      LEFT JOIN users u ON u.id = a."acknowledgedBy"
"""

# Who holds a permission: by a role of their own or of a group they are in; a system role holds them all
USERS_WITH_PERMISSION_SQL = """
    SELECT DISTINCT u.id, u.email, u."firstName", u."lastName"
      FROM users u
     WHERE u."isActive" AND u.email <> '' AND EXISTS (
            SELECT 1 FROM access_roles r
              LEFT JOIN access_role_permissions rp ON rp."roleId" = r.id AND rp.permission = %(permission)s
             WHERE (r."isSystem" OR rp.permission IS NOT NULL)
               AND (r.id IN (SELECT ur."roleId" FROM user_access_roles ur WHERE ur."userId" = u.id)
                    OR r.id IN (SELECT gr."roleId" FROM user_group_roles gr
                                  JOIN user_group_members gm ON gm."groupId" = gr."groupId"
                                 WHERE gm."userId" = u.id)))
     ORDER BY u.email
"""


class FacilityAlertsPostgresqlMapper:
    def __init__(self, db):
        self.db = db

    def currentProblems(self, kind: str, stallMinutes: float) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.db.fetchAll(CURRENT_SQL[kind], {"stall": float(stallMinutes)}) or []]

    def openAlert(self, kind: str, problem: Dict[str, Any], message: str) -> Optional[int]:
        """Open an alert for a problem; None when one is open for it already."""
        with self.db.transaction():
            row = self.db.fetchOne(OPEN_ALERT_SQL, (kind, problem["sessionId"], problem["datasetId"],
                                                    problem.get("projectId"), problem.get("protocolId") or "", message))
        return int(row["id"]) if row else None

    def resolveGone(self, kind: str, present: Iterable[tuple]) -> int:
        """Resolve the open alerts of a kind whose (datasetId, protocolId) is no longer a problem."""
        keys = ["%d:%s" % (int(datasetId), protocolId or "") for datasetId, protocolId in present]
        with self.db.transaction():
            rows = self.db.fetchAll(
                'UPDATE facility_alerts SET "resolvedAt" = NOW() WHERE kind = %s AND "resolvedAt" IS NULL '
                'AND NOT ("datasetId"::TEXT || \':\' || "protocolId" = ANY(%s)) RETURNING id', (kind, keys))
        return len(rows or [])

    def listAlerts(self, openOnly: bool = True, limit: int = 200) -> List[Dict[str, Any]]:
        where = ' WHERE a."resolvedAt" IS NULL' if openOnly else ""
        return [dict(row) for row in self.db.fetchAll(
            LIST_ALERTS_SQL + where + ' ORDER BY a."openedAt" DESC, a.id DESC LIMIT %s', (int(limit),)) or []]

    def getAlert(self, alertId: int) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne(LIST_ALERTS_SQL + " WHERE a.id = %s", (int(alertId),))
        return dict(row) if row else None

    def acknowledge(self, alertId: int, userId: Optional[int]) -> None:
        self.db.execute('UPDATE facility_alerts SET "acknowledgedAt" = COALESCE("acknowledgedAt", NOW()), '
                        '"acknowledgedBy" = COALESCE("acknowledgedBy", %s) WHERE id = %s', (userId, int(alertId)))

    def alertsToMail(self, withinMinutes: float) -> List[Dict[str, Any]]:
        """The open alerts not mailed yet (nor failed to be), opened within the last minutes."""
        return [dict(row) for row in self.db.fetchAll(
            LIST_ALERTS_SQL + ' WHERE a."resolvedAt" IS NULL AND a."emailedAt" IS NULL AND a."emailError" IS NULL '
                              'AND a."openedAt" > NOW() - %s * INTERVAL \'1 minute\' ORDER BY a.id',
            (float(withinMinutes),)) or []]

    def markMailed(self, alertIds: List[int], error: Optional[str] = None) -> None:
        if not alertIds:
            return
        if error is None:
            self.db.execute('UPDATE facility_alerts SET "emailedAt" = NOW() WHERE id = ANY(%s)', (list(alertIds),))
        else:
            self.db.execute('UPDATE facility_alerts SET "emailError" = %s WHERE id = ANY(%s)',
                            (error[:500], list(alertIds)))

    def usersWithPermission(self, permission: str) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.db.fetchAll(USERS_WITH_PERMISSION_SQL, {"permission": permission}) or []]
