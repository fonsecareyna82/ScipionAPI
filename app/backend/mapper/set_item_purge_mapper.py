"""The queries that remove, in batches, the items of deleted Sets and Set tables.

A trigger queues the id of every deleted Set and Set table in
scipion_set_item_purges; its items stay until these queries remove them.
"""
from typing import Any, Dict, List

# Only one server process purges at a time; the others skip their turn
PURGE_LOCK_SQL = "SELECT pg_try_advisory_lock(hashtext('scipion_set_item_purges')) AS locked"
PURGE_UNLOCK_SQL = "SELECT pg_advisory_unlock(hashtext('scipion_set_item_purges'))"

NEXT_PURGES_SQL = """
    SELECT id, "setId", "tableId"
      FROM scipion_set_item_purges
     ORDER BY id
     LIMIT %s
"""

DELETE_SET_ITEMS_SQL = """
    DELETE FROM scipion_set_items
     WHERE id IN (SELECT id FROM scipion_set_items WHERE "setId" = %s LIMIT %s)
"""

DELETE_TABLE_ITEMS_SQL = """
    DELETE FROM scipion_set_table_items
     WHERE id IN (SELECT id FROM scipion_set_table_items WHERE "tableId" = %s LIMIT %s)
"""

FINISH_PURGE_SQL = "DELETE FROM scipion_set_item_purges WHERE id = %s"

HAS_PURGES_SQL = "SELECT EXISTS (SELECT 1 FROM scipion_set_item_purges) AS pending"


class SetItemPurgePostgresqlMapper:
    def __init__(self, db):
        self.db = db

    def tryLock(self) -> bool:
        row = self.db.fetchOne(PURGE_LOCK_SQL) or {}
        return bool(row.get("locked"))

    def unlock(self) -> None:
        self.db.fetchOne(PURGE_UNLOCK_SQL)

    def hasPendingPurges(self) -> bool:
        row = self.db.fetchOne(HAS_PURGES_SQL) or {}
        return bool(row.get("pending"))

    def listPurges(self, limit: int) -> List[Dict[str, Any]]:
        return self.db.fetchAll(NEXT_PURGES_SQL, (int(limit),)) or []

    def deleteItemsBatch(self, purge: Dict[str, Any], batchSize: int) -> int:
        """Remove up to batchSize items of the queued Set or table; returns how many were removed."""
        if purge.get("setId") is not None:
            cursor = self.db.execute(DELETE_SET_ITEMS_SQL, (int(purge["setId"]), int(batchSize)))
        else:
            cursor = self.db.execute(DELETE_TABLE_ITEMS_SQL, (int(purge["tableId"]), int(batchSize)))
        return int(cursor.rowcount or 0)

    def finishPurge(self, purgeId: int) -> None:
        self.db.execute(FINISH_PURGE_SQL, (int(purgeId),))
