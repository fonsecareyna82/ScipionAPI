"""The queries of how long a facility keeps its finished sessions' data, and what of them was deleted."""
import json
from typing import Any, Dict, List, Optional

from app.backend.mapper.postgresql import PostgresqlFlatMapper

DELETING_STATUS = PostgresqlFlatMapper.DELETING_STATUS

# The finished sessions with what their data take and what was deleted; finishedOn is the day in the facility
LIST_FINISHED_SQL = """
    SELECT s.id, s.name, s.status, s."microscopeId", m.name AS "microscopeName", s.technique,
           s."groupId", g.name AS "groupName", s."userId", u.email AS "userEmail",
           TRIM(COALESCE(u."firstName", '') || ' ' || COALESCE(u."lastName", '')) AS "userName",
           s."finishedAt", (s."finishedAt" AT TIME ZONE %(tz)s)::DATE AS "finishedOn",
           s."rawKeepUntil", s."processedKeepUntil", s."rawDeletedAt", s."processedDeletedAt",
           TRIM(COALESCE(rd."firstName", '') || ' ' || COALESCE(rd."lastName", '')) AS "rawDeletedByName",
           rd.email AS "rawDeletedByEmail",
           TRIM(COALESCE(pd."firstName", '') || ' ' || COALESCE(pd."lastName", '')) AS "processedDeletedByName",
           pd.email AS "processedDeletedByEmail",
           s."retentionNotices",
           (SELECT COALESCE(SUM(d."movieCount"), 0) FROM facility_session_datasets d
             WHERE d."sessionId" = s.id AND d.kind = 'data') AS "movieCount",
           (SELECT COALESCE(SUM(d."movieBytes"), 0) FROM facility_session_datasets d
             WHERE d."sessionId" = s.id AND d.kind = 'data') AS "movieBytes",
           COALESCE((SELECT JSON_AGG(JSON_BUILD_OBJECT('id', p.id, 'name', p.name, 'ownerId', p."ownerId",
                                                      'bytes', du."totalBytes") ORDER BY p.id)
                       FROM projects p
                       LEFT JOIN project_disk_usage du ON du."projectId" = p.id
                      WHERE p.id IN (SELECT d."projectId" FROM facility_session_datasets d
                                      WHERE d."sessionId" = s.id AND d."projectId" IS NOT NULL)
                        AND p.status IS DISTINCT FROM %(deleting)s), '[]'::JSON) AS projects
      FROM facility_sessions s
      JOIN facility_microscopes m ON m.id = s."microscopeId"
      LEFT JOIN user_groups g ON g.id = s."groupId"
      LEFT JOIN users u ON u.id = s."userId"
      LEFT JOIN users rd ON rd.id = s."rawDeletedBy"
      LEFT JOIN users pd ON pd.id = s."processedDeletedBy"
     WHERE s."finishedAt" IS NOT NULL AND s.status IN ('finished', 'archived')
"""

# Who a session's notices go to: its user and the PIs of its group, each once
NOTICE_RECIPIENTS_SQL = """
    SELECT DISTINCT u.email FROM users u
     WHERE u.email IS NOT NULL AND u.email <> '' AND u."isActive"
       AND (u.id = %(userId)s OR u.id IN (SELECT m."userId" FROM user_group_members m
                                           WHERE m."groupId" = %(groupId)s AND m."groupRole" = 'pi'))
     ORDER BY u.email
"""


class FacilityRetentionPostgresqlMapper:
    def __init__(self, db):
        self.db = db

    def listFinished(self, timezone: str, sessionId: Optional[int] = None) -> List[Dict[str, Any]]:
        sql = LIST_FINISHED_SQL + (" AND s.id = %(sessionId)s" if sessionId is not None else "") + \
            ' ORDER BY s."finishedAt", s.id'
        rows = self.db.fetchAll(sql, {"tz": timezone, "deleting": DELETING_STATUS,
                                      "sessionId": int(sessionId) if sessionId is not None else None})
        return [dict(row) for row in rows or []]

    def saveKeepUntil(self, sessionId: int, rawKeepUntil, processedKeepUntil) -> None:
        """The dates the staff gave a session (None: the facility's days); its notices start again."""
        self.db.execute('UPDATE facility_sessions SET "rawKeepUntil" = %s, "processedKeepUntil" = %s, '
                        '"updatedAt" = NOW() WHERE id = %s', (rawKeepUntil, processedKeepUntil, int(sessionId)))

    def markDeleted(self, sessionId: int, kind: str, userId: Optional[int]) -> None:
        """Record that a session's raw data or projects were deleted (kind: raw or processed), and by whom."""
        column = {"raw": "raw", "processed": "processed"}[kind]
        self.db.execute('UPDATE facility_sessions SET "%sDeletedAt" = NOW(), "%sDeletedBy" = %%s, '
                        '"updatedAt" = NOW() WHERE id = %%s' % (column, column), (userId, int(sessionId)))

    def unmarkRawDeleted(self, sessionId: int) -> None:
        self.db.execute('UPDATE facility_sessions SET "rawDeletedAt" = NULL, "rawDeletedBy" = NULL, '
                        '"updatedAt" = NOW() WHERE id = %s', (int(sessionId),))

    def archive(self, sessionId: int) -> None:
        """A finished session whose data are gone is history: archived."""
        self.db.execute("UPDATE facility_sessions SET status = 'archived', \"updatedAt\" = NOW() "
                        "WHERE id = %s AND status = 'finished'", (int(sessionId),))

    def saveNotices(self, sessionId: int, notices: Dict[str, Any]) -> None:
        self.db.execute('UPDATE facility_sessions SET "retentionNotices" = %s::JSONB WHERE id = %s',
                        (json.dumps(notices, default=str), int(sessionId)))

    def noticeRecipients(self, userId: Optional[int], groupId: Optional[int]) -> List[str]:
        rows = self.db.fetchAll(NOTICE_RECIPIENTS_SQL, {"userId": userId, "groupId": groupId})
        return [row["email"] for row in rows or []]
