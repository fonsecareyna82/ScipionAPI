"""The queries of explaining a failed protocol: its status and what its failed steps said."""
from typing import Any, Dict, List, Optional

PROTOCOL_STATUS_SQL = """
    SELECT id, "protocolClassName", LOWER(COALESCE(status, '')) AS status
      FROM protocols
     WHERE "projectId" = %s AND "protocolId" = %s
"""

FAILED_STEP_ERRORS_SQL = """
    SELECT error
      FROM protocol_steps
     WHERE "projectId" = %s AND "protocolId" = %s
       AND LOWER(COALESCE(status, '')) = 'failed'
       AND error IS NOT NULL AND BTRIM(error) <> ''
     ORDER BY "stepIndex"
"""


class ProtocolFailurePostgresqlMapper:
    def __init__(self, db):
        self.db = db

    def protocol(self, projectId: int, protocolId) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne(PROTOCOL_STATUS_SQL, (int(projectId), str(protocolId)))
        return dict(row) if row else None

    def failedStepErrors(self, projectId: int, protocolId) -> List[str]:
        rows = self.db.fetchAll(FAILED_STEP_ERRORS_SQL, (int(projectId), str(protocolId))) or []
        return [str(row["error"]) for row in rows]
