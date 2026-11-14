"""The queries of the help chat: the protocols of a project as it talks about them."""
from typing import Any, Dict, List, Optional

PROJECT_PROTOCOLS_SQL = """
    SELECT "protocolId", "protocolClassName" AS "className", LOWER(COALESCE(status, '')) AS status,
           COALESCE(NULLIF(params->>'runName', ''), "protocolClassName") AS label
      FROM protocols
     WHERE "projectId" = %s
     ORDER BY id
"""

PROTOCOL_SQL = """
    SELECT "protocolId", "protocolClassName" AS "className", LOWER(COALESCE(status, '')) AS status,
           COALESCE(NULLIF(params->>'runName', ''), "protocolClassName") AS label
      FROM protocols
     WHERE "projectId" = %s AND "protocolId" = %s
"""

# The sets a protocol made, with how many items each has
PROTOCOL_OUTPUTS_SQL = """
    SELECT s."outputName", s."setClassName", s."itemClassName",
           (SELECT COUNT(*) FROM scipion_set_items i WHERE i."setId" = s.id) AS size
      FROM scipion_sets s
      JOIN protocols p ON p.id = s."protocolDbId"
     WHERE s."projectId" = %s AND p."projectId" = %s AND p."protocolId" = %s
       AND COALESCE(s.properties ->> 'runtimeReserved', 'false') <> 'true'
     ORDER BY s."outputName"
"""

# What else a protocol made, one object each (a volume, a resolution…)
PROTOCOL_OBJECT_OUTPUTS_SQL = """
    SELECT COALESCE(NULLIF(o.path, ''), o.name) AS "outputName", o."className" AS "setClassName",
           NULL AS "itemClassName", NULL AS size
      FROM scipion_objects o
      JOIN protocols p ON p.id = o."protocolDbId"
     WHERE o."projectId" = %s AND p."projectId" = %s AND p."protocolId" = %s AND o."parentObjectId" IS NULL
       AND NOT EXISTS (SELECT 1 FROM scipion_sets s WHERE s."objectId" = o.id)
     ORDER BY "outputName"
"""


class HelpChatPostgresqlMapper:
    def __init__(self, db):
        self.db = db

    def projectProtocols(self, projectId: int) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.db.fetchAll(PROJECT_PROTOCOLS_SQL, (int(projectId),)) or []]

    def protocol(self, projectId: int, protocolId) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne(PROTOCOL_SQL, (int(projectId), str(protocolId)))
        return dict(row) if row else None

    def protocolOutputs(self, projectId: int, protocolId) -> List[Dict[str, Any]]:
        values = (int(projectId), int(projectId), str(protocolId))
        rows = (self.db.fetchAll(PROTOCOL_OUTPUTS_SQL, values) or []) + (
            self.db.fetchAll(PROTOCOL_OBJECT_OUTPUTS_SQL, values) or [])
        return [dict(row) for row in rows]
