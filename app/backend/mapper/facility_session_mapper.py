"""The queries of a facility's acquisition sessions and their datasets (the ATLAS and DATA_NN folders)."""
import json
from typing import Any, Dict, List, Optional

from app.backend.mapper.facility_image_mapper import FacilityImagePostgresqlMapper, imagesJson

SESSION_FIELDS = ("name", "microscopeId", "technique", "status", "groupId", "userId", "bookingRef", "scheduledOn",
                  "startedAt", "finishedAt", "notes", "templateId", "autoProcess")
DATASET_FIELDS = ("kind", "number", "gridId", "detectorId", "notes")

LIST_SESSIONS_SQL = """
    SELECT s.id, s.name, s."microscopeId", m.name AS "microscopeName", s.technique, s.status,
           s."groupId", g.name AS "groupName", s."userId", u.email AS "userEmail",
           TRIM(COALESCE(u."firstName", '') || ' ' || COALESCE(u."lastName", '')) AS "userName",
           s."bookingRef", s."scheduledOn", s."startedAt", s."finishedAt", s.notes, s."createdBy",
           s."createdAt", s."updatedAt", m."offloadPath", s."templateId", s."autoProcess",
           """ + imagesJson("sessionId", "s.id") + """ AS images,
           COALESCE((SELECT JSON_AGG(JSON_BUILD_OBJECT(
                         'id', d.id, 'kind', d.kind, 'number', d.number, 'gridId', d."gridId",
                         'detectorId', d."detectorId", 'notes', d.notes,
                         -- The detector the staff gave it, else the one its first movie names
                         'detectorName', COALESCE(det.name, d.acquisition->>'detectorName'),
                         'movieCount', d."movieCount", 'movieBytes', d."movieBytes",
                         'firstMovieAt', d."firstMovieAt", 'lastMovieAt', d."lastMovieAt", 'scannedAt', d."scannedAt",
                         'acquisition', d.acquisition, 'folderFound', (d."scanState"->>'exists')::BOOLEAN,
                         'projectId', d."projectId", 'processing', d.processing,
                         'minutesSinceLastMovie', EXTRACT(EPOCH FROM NOW() - d."lastMovieAt") / 60,
                         'grid', CASE WHEN gr.id IS NULL THEN NULL ELSE JSON_BUILD_OBJECT(
                                     'gridNumber', gr."gridNumber", 'position', gr.position, 'gridType', gr."gridType",
                                     'specimen', gr.specimen, 'status', gr.status, 'boxLabel', b.label,
                                     'sampleId', smp.id, 'sampleCode', smp.code) END,
                         'images', """ + imagesJson("datasetId", "d.id") + """)
                                     ORDER BY d.number)
                       FROM facility_session_datasets d
                       LEFT JOIN facility_grids gr ON gr.id = d."gridId"
                       LEFT JOIN facility_grid_boxes b ON b.id = gr."boxId"
                       LEFT JOIN facility_samples smp ON smp.id = b."sampleId"
                       LEFT JOIN facility_detectors det ON det.id = d."detectorId"
                      WHERE d."sessionId" = s.id), '[]'::JSON) AS datasets
      FROM facility_sessions s
      JOIN facility_microscopes m ON m.id = s."microscopeId"
      LEFT JOIN user_groups g ON g.id = s."groupId"
      LEFT JOIN users u ON u.id = s."userId"
"""

_ORDER = ' ORDER BY COALESCE(s."scheduledOn", s."createdAt"::DATE) DESC, s.id DESC'


def _quoted(field: str) -> str:
    return '"%s"' % field if field != field.lower() else field


INSERT_SESSION_SQL = "INSERT INTO facility_sessions (id, %s, \"createdBy\") VALUES (%%(id)s, %s, %%(createdBy)s)" % (
    ", ".join(_quoted(field) for field in SESSION_FIELDS), ", ".join("%%(%s)s" % field for field in SESSION_FIELDS))
UPDATE_SESSION_SQL = 'UPDATE facility_sessions SET %s, "updatedAt" = NOW() WHERE id = %%(id)s' % ", ".join(
    "%s = %%(%s)s" % (_quoted(field), field) for field in SESSION_FIELDS)
INSERT_DATASET_SQL = 'INSERT INTO facility_session_datasets ("sessionId", %s) VALUES (%%(sessionId)s, %s) RETURNING id' % (
    ", ".join(_quoted(field) for field in DATASET_FIELDS), ", ".join("%%(%s)s" % field for field in DATASET_FIELDS))
UPDATE_DATASET_SQL = "UPDATE facility_session_datasets SET %s WHERE id = %%(id)s" % ", ".join(
    "%s = %%(%s)s" % (_quoted(field), field) for field in DATASET_FIELDS)


WATCH_LOCK_SQL = "SELECT pg_try_advisory_lock(hashtext('facility_session_watch')) AS locked"
WATCH_UNLOCK_SQL = "SELECT pg_advisory_unlock(hashtext('facility_session_watch')) AS unlocked"

LIST_WATCHED_DATASETS_SQL = """
    SELECT d.id, d."sessionId", s.name AS "sessionName", d.number, d."detectorId", d."movieCount",
           d."firstMovieAt", d.acquisition IS NOT NULL AS "acquisitionRead", d."scanState",
           s."microscopeId", m."offloadPath"
      FROM facility_session_datasets d
      JOIN facility_sessions s ON s.id = d."sessionId"
      JOIN facility_microscopes m ON m.id = s."microscopeId"
     WHERE s.status = 'acquiring' AND d.kind = 'data'
     ORDER BY s.id, d.number
"""

# The DATA whose first movie was read and whose project is to be made: by itself when their session processes
# so (and they were never tried), or because the staff asked again
LIST_DATASETS_TO_PROCESS_SQL = """
    SELECT d.id, d."sessionId", s.name AS "sessionName", d.number, d."detectorId", d.acquisition, d.processing,
           s."templateId", s."userId", s."createdBy", s."groupId", s."microscopeId", m."offloadPath",
           smp.code AS "sampleCode", b.label AS "boxLabel", gr."gridNumber"
      FROM facility_session_datasets d
      JOIN facility_sessions s ON s.id = d."sessionId"
      JOIN facility_microscopes m ON m.id = s."microscopeId"
      LEFT JOIN facility_grids gr ON gr.id = d."gridId"
      LEFT JOIN facility_grid_boxes b ON b.id = gr."boxId"
      LEFT JOIN facility_samples smp ON smp.id = b."sampleId"
     WHERE d.kind = 'data' AND d."projectId" IS NULL AND s.status = 'acquiring' AND s."templateId" <> ''
       AND d.acquisition IS NOT NULL AND d.acquisition->>'error' IS NULL AND m."offloadPath" <> ''
       AND (d.processing->>'state' = 'queued' OR (s."autoProcess" AND d.processing IS NULL))
     ORDER BY s.id, d.number
"""

SAVE_SCAN_SQL = """
    UPDATE facility_session_datasets
       SET "movieCount" = %(movieCount)s, "movieBytes" = %(movieBytes)s,
           "firstMovieAt" = COALESCE("firstMovieAt", %(firstMovieAt)s), "lastMovieAt" = %(lastMovieAt)s,
           "scannedAt" = NOW(), "scanState" = %(scanState)s::JSONB,
           acquisition = COALESCE(%(acquisition)s::JSONB, acquisition)
     WHERE id = %(id)s
"""


class FacilitySessionPostgresqlMapper(FacilityImagePostgresqlMapper):
    def listSessions(self, statuses: Optional[List[str]] = None, text: str = "") -> List[Dict[str, Any]]:
        conditions, params = [], []
        if statuses:
            conditions.append("s.status = ANY(%s)")
            params.append(list(statuses))
        if text:
            # The text as typed: its % and _ are no wildcards
            pattern = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            conditions.append('(s.name ILIKE %s OR s."bookingRef" ILIKE %s OR u.email ILIKE %s OR '
                              "COALESCE(u.\"firstName\", '') || ' ' || COALESCE(u.\"lastName\", '') ILIKE %s OR "
                              "g.name ILIKE %s)")
            params.extend([pattern] * 5)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        return [dict(row) for row in self.db.fetchAll(LIST_SESSIONS_SQL + where + _ORDER, tuple(params)) or []]

    def getSession(self, sessionId: int) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne(LIST_SESSIONS_SQL + " WHERE s.id = %s", (int(sessionId),))
        return dict(row) if row else None

    def findSessionIdByName(self, name: str) -> Optional[int]:
        row = self.db.fetchOne("SELECT id FROM facility_sessions WHERE LOWER(name) = LOWER(%s)", (name,))
        return int(row["id"]) if row else None

    def nextSessionId(self) -> int:
        """An id for a new session, known before it is saved: its name carries it."""
        row = self.db.fetchOne("SELECT NEXTVAL(PG_GET_SERIAL_SEQUENCE('facility_sessions', 'id')) AS id")
        return int(row["id"])

    def saveSession(self, sessionId: int, isNew: bool, values: Dict[str, Any], datasets: List[Dict[str, Any]],
                    createdBy: Optional[int] = None) -> int:
        """Save a session and its datasets in one transaction: a dataset with an id is updated, one
        without inserted, and the session's datasets missing from datasets deleted."""
        with self.db.transaction():
            params = dict({field: values[field] for field in SESSION_FIELDS}, id=int(sessionId))
            if isNew:
                self.db.execute(INSERT_SESSION_SQL, dict(params, createdBy=createdBy), commit=False)
            else:
                self.db.execute(UPDATE_SESSION_SQL, params, commit=False)
            keptIds = []
            for dataset in datasets:
                datasetParams = {field: dataset[field] for field in DATASET_FIELDS}
                if dataset.get("id") is None:
                    keptIds.append(int(self.db.fetchOne(INSERT_DATASET_SQL,
                                                        dict(datasetParams, sessionId=int(sessionId)))["id"]))
                else:
                    self.db.execute(UPDATE_DATASET_SQL, dict(datasetParams, id=int(dataset["id"])), commit=False)
                    keptIds.append(int(dataset["id"]))
            self.db.execute('DELETE FROM facility_session_datasets WHERE "sessionId" = %s AND NOT (id = ANY(%s))',
                            (int(sessionId), keptIds), commit=False)
        return int(sessionId)

    def deleteSession(self, sessionId: int) -> None:
        self.db.execute("DELETE FROM facility_sessions WHERE id = %s", (int(sessionId),))

    def gridExists(self, gridId: int) -> bool:
        return self.db.fetchOne("SELECT 1 AS found FROM facility_grids WHERE id = %s", (int(gridId),)) is not None

    def groupExists(self, groupId: int) -> bool:
        return self.db.fetchOne("SELECT 1 AS found FROM user_groups WHERE id = %s", (int(groupId),)) is not None

    def getUser(self, userId: int) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne('SELECT id, email, "firstName", "lastName" FROM users WHERE id = %s', (int(userId),))
        return dict(row) if row else None

    def getGroupName(self, groupId: int) -> Optional[str]:
        row = self.db.fetchOne("SELECT name FROM user_groups WHERE id = %s", (int(groupId),))
        return row["name"] if row else None

    # The watcher of the folders --------------------------------------------------------------
    def tryWatchLock(self) -> bool:
        """Only one server process looks at the folders at a time; the others skip their turn."""
        row = self.db.fetchOne(WATCH_LOCK_SQL) or {}
        return bool(row.get("locked"))

    def unlockWatch(self) -> None:
        self.db.fetchOne(WATCH_UNLOCK_SQL)

    def listWatchedDatasets(self) -> List[Dict[str, Any]]:
        """The DATA of the sessions acquiring, with their microscope's offload folder."""
        return [dict(row) for row in self.db.fetchAll(LIST_WATCHED_DATASETS_SQL) or []]

    def saveScan(self, datasetId: int, movieCount: int, movieBytes: int, firstMovieAt, lastMovieAt,
                 scanState: Dict[str, Any], acquisition: Optional[Dict[str, Any]]) -> None:
        """Keep what a look at a dataset's folder found; an acquisition already read is kept when None."""
        self.db.execute(SAVE_SCAN_SQL, {
            "id": int(datasetId), "movieCount": int(movieCount), "movieBytes": int(movieBytes),
            "firstMovieAt": firstMovieAt, "lastMovieAt": lastMovieAt, "scanState": json.dumps(scanState),
            "acquisition": json.dumps(acquisition) if acquisition is not None else None})

    # Processing ------------------------------------------------------------------------------
    def listDatasetsToProcess(self) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.db.fetchAll(LIST_DATASETS_TO_PROCESS_SQL) or []]

    def saveProcessing(self, datasetId: int, processing: Dict[str, Any], projectId: Optional[int] = None) -> None:
        """Keep how a DATA's processing goes; a project, once given, stays."""
        self.db.execute('UPDATE facility_session_datasets SET processing = %s::JSONB, '
                        '"projectId" = COALESCE(%s, "projectId") WHERE id = %s',
                        (json.dumps(processing, default=str), projectId, int(datasetId)))

    def getDatasetForProcessing(self, datasetId: int) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne('SELECT d.id, d."sessionId", d.kind, d."projectId", d.acquisition, d.processing, '
                               's."templateId", s.status FROM facility_session_datasets d '
                               'JOIN facility_sessions s ON s.id = d."sessionId" WHERE d.id = %s', (int(datasetId),))
        return dict(row) if row else None

    # Images ------------------------------------------------------------------------------------
    def sessionIdOf(self, ownerKind: str, ownerId: int) -> Optional[int]:
        """The session a session or dataset belongs to (None: there is no such one)."""
        sql = {
            "session": 'SELECT id AS "sessionId" FROM facility_sessions WHERE id = %s',
            "dataset": 'SELECT "sessionId" FROM facility_session_datasets WHERE id = %s',
        }[ownerKind]
        row = self.db.fetchOne(sql, (int(ownerId),))
        return int(row["sessionId"]) if row else None
