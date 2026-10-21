"""The queries of the launch history of protocols."""
from typing import Any, Dict, List, Optional


INSERT_LAUNCH_SQL = """
    INSERT INTO protocol_launches ("projectId", "protocolDbId", "protocolId", "userId", mode, params)
    VALUES (%s, %s, %s, %s, %s, %s)
"""

LIST_LAUNCHES_SQL = """
    SELECT l.id, l.mode, l.params, l."launchedAt", l."userId",
           u.email, u."firstName", u."lastName"
      FROM protocol_launches l
      LEFT JOIN users u ON u.id = l."userId"
     WHERE l."projectId" = %s AND l."protocolId" = %s
     ORDER BY l."launchedAt" DESC, l.id DESC
     LIMIT %s
"""


class ProtocolLaunchPostgresqlMapper:
    def __init__(self, db):
        self.db = db

    def insertLaunch(self, projectId: int, protocolDbId: int, protocolId, userId: Optional[int], mode: str,
                     params: Dict[str, Any]) -> None:
        from app.backend.mapper.postgresql import _toJsonParam

        self.db.execute(INSERT_LAUNCH_SQL, (int(projectId), int(protocolDbId), str(protocolId),
                                            int(userId) if userId is not None else None, mode, _toJsonParam(params)))

    def listLaunches(self, projectId: int, protocolId, limit: int) -> List[Dict[str, Any]]:
        """The launches of a protocol with who launched them, newest first."""
        return self.db.fetchAll(LIST_LAUNCHES_SQL, (int(projectId), str(protocolId), int(limit))) or []
