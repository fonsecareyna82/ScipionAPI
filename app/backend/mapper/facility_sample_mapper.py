"""The queries of a facility's samples, their grid boxes and their grids."""
from typing import Any, Dict, List, Optional

SAMPLE_FIELDS = ("code", "description", "groupId", "ownerId", "accessRoute", "notes")
BOX_FIELDS = ("label", "vitrificationCode", "vitrifiedOn", "notes")
GRID_FIELDS = ("position", "gridNumber", "gridType", "concentration", "specimen", "status", "notes")

LIST_SAMPLES_SQL = """
    SELECT s.id, s.code, s.description, s."groupId", g.name AS "groupName", s."ownerId", u.email AS "ownerEmail",
           TRIM(COALESCE(u."firstName", '') || ' ' || COALESCE(u."lastName", '')) AS "ownerName",
           s."accessRoute", s.notes, s."createdAt", s."updatedAt",
           COALESCE((SELECT JSON_AGG(JSON_BUILD_OBJECT(
                         'id', b.id, 'label', b.label, 'vitrificationCode', b."vitrificationCode",
                         'vitrifiedOn', b."vitrifiedOn", 'notes', b.notes,
                         'grids', COALESCE((SELECT JSON_AGG(JSON_BUILD_OBJECT(
                                                'id', gr.id, 'position', gr.position, 'gridNumber', gr."gridNumber",
                                                'gridType', gr."gridType", 'concentration', gr.concentration,
                                                'specimen', gr.specimen, 'status', gr.status, 'notes', gr.notes)
                                            ORDER BY gr.position)
                                              FROM facility_grids gr WHERE gr."boxId" = b.id), '[]'::JSON))
                       ORDER BY b.id)
                       FROM facility_grid_boxes b WHERE b."sampleId" = s.id), '[]'::JSON) AS boxes
      FROM facility_samples s
      LEFT JOIN user_groups g ON g.id = s."groupId"
      LEFT JOIN users u ON u.id = s."ownerId"
"""


def _quoted(field: str) -> str:
    return '"%s"' % field if field != field.lower() else field


def _insertSql(table: str, fields, extra: Dict[str, str]) -> str:
    columns = [_quoted(field) for field in fields] + [_quoted(name) for name in extra]
    values = ["%%(%s)s" % field for field in fields] + list(extra.values())
    return "INSERT INTO %s (%s) VALUES (%s) RETURNING id" % (table, ", ".join(columns), ", ".join(values))


def _updateSql(table: str, fields, extra: str = "") -> str:
    assignments = ", ".join("%s = %%(%s)s" % (_quoted(field), field) for field in fields)
    return "UPDATE %s SET %s%s WHERE id = %%(id)s" % (table, assignments, extra)


INSERT_SAMPLE_SQL = _insertSql("facility_samples", SAMPLE_FIELDS, {})
UPDATE_SAMPLE_SQL = _updateSql("facility_samples", SAMPLE_FIELDS, ', "updatedAt" = NOW()')
INSERT_BOX_SQL = _insertSql("facility_grid_boxes", BOX_FIELDS, {"sampleId": "%(sampleId)s"})
UPDATE_BOX_SQL = _updateSql("facility_grid_boxes", BOX_FIELDS)
INSERT_GRID_SQL = _insertSql("facility_grids", GRID_FIELDS, {"boxId": "%(boxId)s"})
UPDATE_GRID_SQL = _updateSql("facility_grids", GRID_FIELDS + ("boxId",))


class FacilitySamplePostgresqlMapper:
    def __init__(self, db):
        self.db = db

    def listSamples(self, text: str = "") -> List[Dict[str, Any]]:
        if text:
            # The text as typed: its % and _ are no wildcards
            pattern = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            rows = self.db.fetchAll(LIST_SAMPLES_SQL + ' WHERE s.code ILIKE %s OR s.description ILIKE %s '
                                    'ORDER BY s."createdAt" DESC, s.id DESC', (pattern, pattern))
        else:
            rows = self.db.fetchAll(LIST_SAMPLES_SQL + ' ORDER BY s."createdAt" DESC, s.id DESC')
        return [dict(row) for row in rows or []]

    def getSample(self, sampleId: int) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne(LIST_SAMPLES_SQL + " WHERE s.id = %s", (int(sampleId),))
        return dict(row) if row else None

    def findSampleIdByCode(self, code: str) -> Optional[int]:
        row = self.db.fetchOne("SELECT id FROM facility_samples WHERE LOWER(code) = LOWER(%s)", (code,))
        return int(row["id"]) if row else None

    def saveSample(self, sampleId: Optional[int], values: Dict[str, Any], boxes: List[Dict[str, Any]]) -> int:
        """Save a sample and its whole tree in one transaction: rows with an id are updated, without one
        inserted, and the sample's boxes and grids missing from boxes deleted."""
        with self.db.transaction():
            params = {field: values[field] for field in SAMPLE_FIELDS}
            if sampleId is None:
                sampleId = int(self.db.fetchOne(INSERT_SAMPLE_SQL, params)["id"])
            else:
                self.db.execute(UPDATE_SAMPLE_SQL, dict(params, id=int(sampleId)), commit=False)
            keptBoxIds, keptGridIds = [], []
            for box in boxes:
                boxParams = {field: box[field] for field in BOX_FIELDS}
                if box.get("id") is None:
                    boxId = int(self.db.fetchOne(INSERT_BOX_SQL, dict(boxParams, sampleId=sampleId))["id"])
                else:
                    boxId = int(box["id"])
                    self.db.execute(UPDATE_BOX_SQL, dict(boxParams, id=boxId), commit=False)
                keptBoxIds.append(boxId)
                for grid in box["grids"]:
                    gridParams = {field: grid[field] for field in GRID_FIELDS}
                    if grid.get("id") is None:
                        keptGridIds.append(int(self.db.fetchOne(INSERT_GRID_SQL, dict(gridParams, boxId=boxId))["id"]))
                    else:
                        self.db.execute(UPDATE_GRID_SQL, dict(gridParams, boxId=boxId, id=int(grid["id"])),
                                        commit=False)
                        keptGridIds.append(int(grid["id"]))
            self.db.execute('DELETE FROM facility_grids g USING facility_grid_boxes b '
                            'WHERE g."boxId" = b.id AND b."sampleId" = %s AND NOT (g.id = ANY(%s))',
                            (sampleId, keptGridIds), commit=False)
            self.db.execute('DELETE FROM facility_grid_boxes WHERE "sampleId" = %s AND NOT (id = ANY(%s))',
                            (sampleId, keptBoxIds), commit=False)
        return sampleId

    def deleteSample(self, sampleId: int) -> None:
        self.db.execute("DELETE FROM facility_samples WHERE id = %s", (int(sampleId),))

    def groupExists(self, groupId: int) -> bool:
        return self.db.fetchOne("SELECT 1 AS found FROM user_groups WHERE id = %s", (int(groupId),)) is not None

    def userExists(self, userId: int) -> bool:
        return self.db.fetchOne("SELECT 1 AS found FROM users WHERE id = %s", (int(userId),)) is not None
