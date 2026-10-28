"""The queries of the streaming monitors (single particle and tomography) over the stored Sets.

Sets are stored flat: one row per item in ``scipion_set_items`` (``values`` keyed by the dotted attribute
paths), the items of a nested Set (the particles of a class, the tilt images of a tilt series) in a child
logical table, and counters (``itemsCount``, ``maxItemId``) in the Set's and the tables' properties. These
queries read the counters and the rows of one Set by its indexes; none groups a whole large Set.
"""
from typing import Any, Dict, List, Optional, Sequence


OUTPUT_SETS_SQL = """
    SELECT s.id AS "setId", p."protocolId", p."protocolClassName",
           LOWER(COALESCE(p.status, '')) AS status,
           COALESCE(NULLIF(p.params->>'runName', ''), p."protocolClassName") AS label,
           s."outputName", s."setClassName", s."itemClassName", s.properties, s."updatedAt"
      FROM scipion_sets s
      JOIN protocols p ON p.id = s."protocolDbId"
     WHERE s."projectId" = %s
       AND COALESCE(s.properties ->> 'runtimeReserved', 'false') <> 'true'
"""

INPUT_REFS_SQL = """
    SELECT "protocolId", "parentProtocolId", "parentOutputName"
      FROM protocol_input_refs
     WHERE "projectId" = %s AND "parentProtocolId" IS NOT NULL
"""

# The protocol graph's edges: a fallback for a protocol whose input refs miss a parent it depends on.
DEPENDENCIES_SQL = """
    SELECT parent."protocolId" AS "parentProtocolId", child."protocolId" AS "protocolId"
      FROM protocol_dependencies d
      JOIN protocols parent ON parent.id = d."parentProtocolDbId" AND parent."projectId" = d."projectId"
      JOIN protocols child ON child.id = d."childProtocolDbId" AND child."projectId" = d."projectId"
     WHERE d."projectId" = %s
"""

SET_RATES_SQL = """
    SELECT sets."setId",
           COUNT(recent.t) FILTER (WHERE recent.t >= %s) AS "lastWindow",
           COUNT(recent.t) FILTER (WHERE recent.t >= %s AND recent.t < %s) AS "previousWindow",
           COUNT(recent.t) AS "sampled",
           MIN(recent.t) AS "oldest",
           MAX(recent.t) AS "newest"
      FROM UNNEST(%s::int[]) AS sets("setId")
      CROSS JOIN LATERAL (
            SELECT COALESCE(i.creation, i."createdAt") AS t
              FROM scipion_set_items i
             WHERE i."setId" = sets."setId"
             ORDER BY i."scipionItemId" DESC
             LIMIT %s
      ) recent
     GROUP BY sets."setId"
"""

PROTOCOL_PARAM_SQL = """
    SELECT params->>%s AS value
      FROM protocols
     WHERE "projectId" = %s AND "protocolId" = %s
"""

# Rows are read in the order they were written (their row id), not by item id: parallel steps finish items
# out of order, and an item with a lower id written later must still be read.
SERIES_ITEMS_SQL = """
    SELECT id AS "rowId", "scipionItemId", enabled, label, COALESCE(creation, "createdAt") AS "time", "values"
      FROM scipion_set_items
     WHERE "setId" = %s AND id > %s
     ORDER BY id
     LIMIT %s
"""

# Whether the first item of a Set carries a value: what kind of analysis wrote it, for one row
FIRST_ITEM_HAS_VALUE_SQL = """
    SELECT jsonb_exists("values", %s) AS "has"
      FROM scipion_set_items
     WHERE "setId" = %s
     ORDER BY id
     LIMIT 1
"""

# A Set whose rows were all written again (a full sync) has no row left at or below the caller's cursor.
FIRST_ROW_SQL = """
    SELECT MIN(id) AS "firstRowId" FROM scipion_set_items WHERE "setId" = %s
"""

LATEST_ROWS_SQL = """
    SELECT id AS "rowId", "scipionItemId", enabled, label, COALESCE(creation, "createdAt") AS "time", "values"
      FROM scipion_set_items
     WHERE "setId" = %s
     ORDER BY id DESC
     LIMIT %s
"""

ITEMS_BY_IDS_SQL = """
    SELECT id AS "rowId", "scipionItemId", enabled, label, COALESCE(creation, "createdAt") AS "time", "values"
      FROM scipion_set_items
     WHERE "setId" = %s AND "scipionItemId" = ANY(%s)
"""

# The classes of a SetOfClasses2D (its root rows) with the particles of each: the counter of its child table,
# kept by every flush, so no particle is read.
CLASSES_SQL = """
    SELECT i."scipionItemId" AS "classId", i.enabled,
           COALESCE((t.properties ->> 'itemsCount')::bigint, (i."values" ->> '_size')::bigint, 0) AS particles
      FROM scipion_set_items i
      LEFT JOIN scipion_set_tables t
        ON t."setId" = i."setId" AND t."parentItemId" = i."scipionItemId" AND t."tableKind" = 'child'
     WHERE i."setId" = %s
"""

MIC_COUNTS_SQL = """
    SELECT chunk.mic, COUNT(*) AS n, MAX(chunk.id) AS "lastRowId"
      FROM (SELECT id, COALESCE("values" ->> '_micId', "values" ->> '_coordinate._micId') AS mic
              FROM scipion_set_items
             WHERE "setId" = %s AND id > %s
             ORDER BY id
             LIMIT %s) chunk
     GROUP BY chunk.mic
"""

GET_SETTINGS_SQL = """
    SELECT settings FROM project_monitor_settings WHERE "projectId" = %s
"""

SAVE_SETTINGS_SQL = """
    INSERT INTO project_monitor_settings ("projectId", settings, "updatedBy", "updatedAt")
    VALUES (%s, %s, %s, NOW())
    ON CONFLICT ("projectId") DO UPDATE
       SET settings = EXCLUDED.settings, "updatedBy" = EXCLUDED."updatedBy", "updatedAt" = NOW()
"""

# -- tomography ------------------------------------------------------------------

TILT_SERIES_SQL = """
    SELECT i."scipionItemId" AS "itemId", i.enabled, i."updatedAt",
           COALESCE(i.creation, i."createdAt") AS "time",
           i."values" ->> '_tsId' AS "tsId",
           i."values" ->> '_size' AS size,
           i."values" ->> '_samplingRate' AS "samplingRate",
           i."values" ->> '_hasAlignment' AS "hasAlignment",
           (t.properties ->> 'itemsCount')::int AS tilts,
           t."updatedAt" AS "tiltsUpdatedAt"
      FROM scipion_set_items i
      LEFT JOIN scipion_set_tables t
        ON t."setId" = i."setId" AND t."parentItemId" = i."scipionItemId" AND t."tableKind" = 'child'
     WHERE i."setId" = %s
"""

# What the tilt images of these tilt series hold
TILT_IMAGES_SQL = """
    SELECT t."parentItemId" AS "itemId",
           COUNT(*) AS tilts,
           COUNT(*) FILTER (WHERE ti.enabled) AS enabled,
           MIN((ti."values" ->> '_tiltAngle')::float) FILTER (WHERE ti.enabled) AS "angleMin",
           MAX((ti."values" ->> '_tiltAngle')::float) FILTER (WHERE ti.enabled) AS "angleMax",
           MAX((ti."values" ->> '_acquisition._accumDose')::float) AS dose
      FROM scipion_set_tables t
      JOIN scipion_set_table_items ti ON ti."tableId" = t.id
     WHERE t."setId" = %s AND t."tableKind" = 'child' AND t."parentItemId" = ANY(%s)
     GROUP BY t."parentItemId"
"""

# What the CTF of the tilts of these CTF series hold; failed fits carry the -999 defocus
CTF_TILTS_SQL = """
    SELECT t."parentItemId" AS "itemId",
           COUNT(*) AS tilts,
           COUNT(*) FILTER (WHERE (ci."values" ->> '_defocusU')::float <= -998 OR NOT ci.enabled) AS failed,
           AVG((ci."values" ->> '_defocusU')::float)
               FILTER (WHERE (ci."values" ->> '_defocusU')::float > 0 AND ci.enabled) AS "defocusU",
           AVG((ci."values" ->> '_defocusV')::float)
               FILTER (WHERE (ci."values" ->> '_defocusU')::float > 0 AND ci.enabled) AS "defocusV",
           AVG(ABS((ci."values" ->> '_defocusU')::float - (ci."values" ->> '_defocusV')::float))
               FILTER (WHERE (ci."values" ->> '_defocusU')::float > 0 AND ci.enabled) AS astigmatism,
           MAX((ci."values" ->> '_resolution')::float)
               FILTER (WHERE (ci."values" ->> '_resolution')::float > 0 AND ci.enabled) AS resolution
      FROM scipion_set_tables t
      JOIN scipion_set_table_items ci ON ci."tableId" = t.id
     WHERE t."setId" = %s AND t."tableKind" = 'child' AND t."parentItemId" = ANY(%s)
     GROUP BY t."parentItemId"
"""

ROOT_ROWS_SQL = """
    SELECT "scipionItemId" AS "itemId", enabled, "updatedAt", "values" ->> '_tsId' AS "tsId",
           "values" ->> '_fileName' AS "fileName", "values" ->> '_filename' AS "filename",
           "values" ->> '_hasResidualInfo' AS "hasResidualInfo"
      FROM scipion_set_items
     WHERE "setId" = %s
"""

# The coordinates of a 3D picking per tomogram (the tsId of the tomogram each one is on)
COORDINATES_3D_PER_TOMOGRAM_SQL = """
    SELECT "values" ->> '_tomoId' AS "tomoId", COUNT(*) AS count
      FROM scipion_set_items
     WHERE "setId" = %s
     GROUP BY 1
"""

ALIGNED_SQL = """
    SELECT 1 AS aligned FROM scipion_set_items
     WHERE "setId" = %s AND LOWER(COALESCE("values" ->> '_hasAlignment', '')) IN ('true', '1')
     LIMIT 1
"""

# The tilt images of one tilt series, and the CTF of each tilt, for the detail of a tilt series
TILTS_OF_SQL = """
    SELECT ti."scipionItemId" AS "itemId", ti.enabled, ti."values"
      FROM scipion_set_tables t
      JOIN scipion_set_table_items ti ON ti."tableId" = t.id
     WHERE t."setId" = %s AND t."tableKind" = 'child' AND t."parentItemId" = %s
"""


class StreamingMonitorPostgresqlMapper:
    def __init__(self, db):
        self.db = db

    # -- the processing chain ----------------------------------------------------

    def listOutputSets(self, projectId: int) -> List[Dict[str, Any]]:
        """The published output Sets of a project, with their protocol and counters."""
        return self.db.fetchAll(OUTPUT_SETS_SQL, (int(projectId),)) or []

    def listInputRefs(self, projectId: int) -> List[Dict[str, Any]]:
        """Which output of which protocol each protocol reads."""
        return self.db.fetchAll(INPUT_REFS_SQL, (int(projectId),)) or []

    def listDependencies(self, projectId: int) -> List[Dict[str, Any]]:
        """The protocol graph's edges (child and parent protocolId)."""
        return self.db.fetchAll(DEPENDENCIES_SQL, (int(projectId),)) or []

    # -- items of a Set -------------------------------------------------------------

    def countRecentItems(self, setIds: Sequence[int], lastFrom, previousFrom, previousTo,
                         sample: int) -> List[Dict[str, Any]]:
        """Per Set, among its newest ``sample`` items, how many were created in the last window and in the
        one before, how many were looked at and the oldest of them."""
        return self.db.fetchAll(SET_RATES_SQL, (lastFrom, previousFrom, previousTo, list(setIds), int(sample))) or []

    def getProtocolParam(self, projectId: int, protocolId: str, name: str) -> Optional[str]:
        """One parameter of a protocol as it was saved (a string), or None."""
        row = self.db.fetchOne(PROTOCOL_PARAM_SQL, (str(name), int(projectId), str(protocolId))) or {}
        value = row.get("value")
        return None if value is None else str(value)

    def listItemsAfterRow(self, setId: int, afterRowId: int, limit: int) -> List[Dict[str, Any]]:
        """The items of a Set written after a row, in the order they were written."""
        return self.db.fetchAll(SERIES_ITEMS_SQL, (int(setId), int(afterRowId), int(limit))) or []

    def firstItemHasValue(self, setId: int, key: str) -> bool:
        """Whether the first item written to a Set carries the value ``key``."""
        row = self.db.fetchOne(FIRST_ITEM_HAS_VALUE_SQL, (str(key), int(setId))) or {}
        return bool(row.get("has"))

    def getFirstRowId(self, setId: int) -> Optional[int]:
        row = self.db.fetchOne(FIRST_ROW_SQL, (int(setId),)) or {}
        first = row.get("firstRowId")
        return None if first is None else int(first)

    def listLatestItems(self, setId: int, limit: int) -> List[Dict[str, Any]]:
        """The last items written to a Set, newest first."""
        return self.db.fetchAll(LATEST_ROWS_SQL, (int(setId), int(limit))) or []

    def listItemsByIds(self, setId: int, itemIds: Sequence[int]) -> List[Dict[str, Any]]:
        return self.db.fetchAll(ITEMS_BY_IDS_SQL, (int(setId), list(itemIds))) or []

    def listClasses(self, setId: int) -> List[Dict[str, Any]]:
        """The classes of a SetOfClasses with the items of each, from their child tables' counters."""
        return self.db.fetchAll(CLASSES_SQL, (int(setId),)) or []

    def countItemsPerMicrograph(self, setId: int, afterRowId: int, limit: int) -> List[Dict[str, Any]]:
        """Per micrograph, the items of a Set (coordinates, particles) written after a row, at most ``limit``
        rows."""
        return self.db.fetchAll(MIC_COUNTS_SQL, (int(setId), int(afterRowId), int(limit))) or []

    # -- thresholds -----------------------------------------------------------------

    def getSettings(self, projectId: int) -> Optional[Any]:
        """The monitor settings of a project, or None when it has none."""
        row = self.db.fetchOne(GET_SETTINGS_SQL, (int(projectId),))
        return None if row is None else row.get("settings")

    def saveSettings(self, projectId: int, settings: Dict[str, Any], userId: Optional[int]) -> None:
        from app.backend.mapper.postgresql import _toJsonParam

        self.db.execute(SAVE_SETTINGS_SQL, (int(projectId), _toJsonParam(settings),
                                            int(userId) if userId is not None else None))

    # -- tomography -------------------------------------------------------------------

    def listTiltSeries(self, setId: int) -> List[Dict[str, Any]]:
        """The tilt series of a Set with the tilt images their child tables hold."""
        return self.db.fetchAll(TILT_SERIES_SQL, (int(setId),)) or []

    def summarizeTiltImages(self, setId: int, itemIds: Sequence[int]) -> List[Dict[str, Any]]:
        """Per tilt series: its tilt images, the enabled ones, their angle range and the highest dose."""
        return self.db.fetchAll(TILT_IMAGES_SQL, (int(setId), list(itemIds))) or []

    def summarizeCtfTilts(self, setId: int, itemIds: Sequence[int]) -> List[Dict[str, Any]]:
        """Per CTF series: its tilts, the failed ones, the mean defocus and astigmatism and the worst
        resolution."""
        return self.db.fetchAll(CTF_TILTS_SQL, (int(setId), list(itemIds))) or []

    def listRootItems(self, setId: int) -> List[Dict[str, Any]]:
        """The items of a Set with their tsId and file names."""
        return self.db.fetchAll(ROOT_ROWS_SQL, (int(setId),)) or []

    def countCoordinates3dPerTomogram(self, setId: int) -> List[Dict[str, Any]]:
        """How many coordinates of a SetOfCoordinates3D are on each tomogram (by its tsId)."""
        return self.db.fetchAll(COORDINATES_3D_PER_TOMOGRAM_SQL, (int(setId),)) or []

    def hasAlignedItem(self, setId: int) -> bool:
        """Whether a SetOfTiltSeries holds an aligned tilt series."""
        return bool(self.db.fetchAll(ALIGNED_SQL, (int(setId),)))

    def listChildItems(self, setId: int, parentItemId: int) -> List[Dict[str, Any]]:
        """The items of the child table of one item: the tilt images of a tilt series, the CTF of its tilts."""
        return self.db.fetchAll(TILTS_OF_SQL, (int(setId), int(parentItemId))) or []
