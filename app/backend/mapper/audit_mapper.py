"""The queries of the audit log."""
import json
from typing import Any, Dict, List, Optional

INSERT_AUDIT_EVENT_SQL = """
    INSERT INTO audit_events ("userId", "userEmail", action, "targetType", "targetId", "targetName", details,
                              "clientAddress")
    VALUES (%(userId)s, %(userEmail)s, %(action)s, %(targetType)s, %(targetId)s, %(targetName)s,
            %(details)s::JSONB, %(clientAddress)s)
"""

# Newest first; "before" pages back by id, the filters are all optional
LIST_AUDIT_EVENTS_SQL = """
    SELECT id, "createdAt", "userId", "userEmail", action, "targetType", "targetId", "targetName", details,
           "clientAddress"
      FROM audit_events
     WHERE (%(before)s::BIGINT IS NULL OR id < %(before)s)
       AND (%(action)s::TEXT IS NULL OR action = %(action)s OR action LIKE %(action)s || '.%%')
       AND (%(userId)s::INTEGER IS NULL OR "userId" = %(userId)s)
       AND (%(since)s::TIMESTAMPTZ IS NULL OR "createdAt" >= %(since)s)
       AND (%(until)s::TIMESTAMPTZ IS NULL OR "createdAt" < %(until)s)
       AND (%(text)s::TEXT IS NULL
            OR "userEmail" ILIKE '%%' || %(text)s || '%%'
            OR "targetName" ILIKE '%%' || %(text)s || '%%'
            OR details::TEXT ILIKE '%%' || %(text)s || '%%')
     ORDER BY id DESC
     LIMIT %(limit)s
"""


class AuditPostgresqlMapper:
    def __init__(self, db):
        self.db = db

    def insertEvent(self, userId: Optional[int], userEmail: Optional[str], action: str,
                    targetType: Optional[str], targetId: Optional[str], targetName: Optional[str],
                    details: Dict[str, Any], clientAddress: Optional[str]) -> None:
        self.db.execute(INSERT_AUDIT_EVENT_SQL, {
            "userId": userId, "userEmail": userEmail, "action": action, "targetType": targetType,
            "targetId": targetId, "targetName": targetName, "details": json.dumps(details or {}, default=str),
            "clientAddress": clientAddress,
        })

    def listEvents(self, limit: int, before: Optional[int] = None, action: Optional[str] = None,
                   userId: Optional[int] = None, since=None, until=None,
                   text: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.db.fetchAll(LIST_AUDIT_EVENTS_SQL, {
            "limit": int(limit), "before": before, "action": action or None, "userId": userId,
            "since": since, "until": until, "text": (text or "").strip() or None,
        }) or []
