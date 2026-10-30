"""What a protocol's summary depends on, read in one query so an unchanged summary is not computed again."""
from typing import Optional

# The protocol's row (status, params: its comment, error and runtime attributes such as summaryVar), its
# stored objects (scalar outputs keep their value there), and the sets of the protocol and of its
# parents (a summary often counts its inputs). A set's properties hold its size and its stream state,
# which closing a stream changes without moving "updatedAt".
PROTOCOL_SUMMARY_FINGERPRINT_SQL = """
    WITH protocol AS (
        SELECT id, status, "updatedAt"
          FROM protocols
         WHERE "projectId" = %(projectId)s AND "protocolId" = %(protocolId)s
         LIMIT 1
    ),
    related AS (
        SELECT id AS "protocolDbId" FROM protocol
        UNION
        SELECT r."parentProtocolDbId"
          FROM protocol_input_refs r, protocol
         WHERE r."projectId" = %(projectId)s AND r."protocolDbId" = protocol.id
           AND r."parentProtocolDbId" IS NOT NULL
    )
    SELECT protocol.status || '|' || protocol."updatedAt"::TEXT
           || '|' || COALESCE((SELECT MD5(STRING_AGG(o.id || ':' || o."updatedAt"::TEXT || ':'
                                                     || COALESCE(o.value, ''), ',' ORDER BY o.id))
                                 FROM scipion_objects o
                                WHERE o."projectId" = %(projectId)s AND o."protocolDbId" = protocol.id
                                  AND o."parentObjectId" IS NULL), '')
           || '|' || COALESCE((SELECT MD5(STRING_AGG(s.id || ':' || s."updatedAt"::TEXT || ':'
                                                     || COALESCE(s.properties::TEXT, ''), ',' ORDER BY s.id))
                                 FROM scipion_sets s
                                WHERE s."projectId" = %(projectId)s
                                  AND s."protocolDbId" IN (SELECT "protocolDbId" FROM related)), '')
           || '|' || COALESCE((SELECT MD5(STRING_AGG(r."inputName" || ':' || COALESCE(r."parentProtocolDbId", 0)
                                                     || ':' || COALESCE(r."parentOutputName", ''), ','
                                                     ORDER BY r."inputName", r."itemIndex"))
                                 FROM protocol_input_refs r
                                WHERE r."projectId" = %(projectId)s AND r."protocolDbId" = protocol.id), '')
           AS fingerprint
      FROM protocol
"""


class ProtocolSummaryMapper:
    def __init__(self, db):
        self.db = db

    def getFingerprint(self, projectId: int, protocolId: int) -> Optional[str]:
        """A text that changes whenever something the protocol's summary reads changes (None: no protocol)."""
        row = self.db.fetchOne(PROTOCOL_SUMMARY_FINGERPRINT_SQL,
                               {"projectId": int(projectId), "protocolId": str(protocolId)})
        return (row or {}).get("fingerprint")
