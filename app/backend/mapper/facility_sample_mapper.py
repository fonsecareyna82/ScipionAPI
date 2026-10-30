"""The queries of a facility's samples, their grid boxes and their grids."""
from typing import Any, Dict, List, Optional

SAMPLE_FIELDS = ("code", "description", "groupId", "ownerId", "accessRoute", "notes")
BOX_FIELDS = ("label", "vitrificationCode", "vitrifiedOn", "notes")
GRID_FIELDS = ("position", "gridNumber", "gridType", "concentration", "specimen", "status", "notes")

# The images of a sample, box or grid as the tree lists them: what they are, never their bytes
def _imagesJson(ownerColumn: str, ownerId: str) -> str:
    return ("""COALESCE((SELECT JSON_AGG(JSON_BUILD_OBJECT('id', i.id, 'caption', i.caption, 'createdAt', i."createdAt")
                                ORDER BY i.id)
                       FROM facility_images i WHERE i."%s" = %s), '[]'::JSON)""" % (ownerColumn, ownerId))


IMAGE_OWNER_COLUMNS = {"sample": "sampleId", "box": "boxId", "grid": "gridId"}

LIST_SAMPLES_SQL = """
    SELECT s.id, s.code, s.description, s."groupId", g.name AS "groupName", s."ownerId", u.email AS "ownerEmail",
           TRIM(COALESCE(u."firstName", '') || ' ' || COALESCE(u."lastName", '')) AS "ownerName",
           s."accessRoute", s.notes, s."createdAt", s."updatedAt",
           """ + _imagesJson("sampleId", "s.id") + """ AS images,
           COALESCE((SELECT JSON_AGG(JSON_BUILD_OBJECT(
                         'id', b.id, 'label', b.label, 'vitrificationCode', b."vitrificationCode",
                         'vitrifiedOn', b."vitrifiedOn", 'notes', b.notes,
                         'images', """ + _imagesJson("boxId", "b.id") + """,
                         'grids', COALESCE((SELECT JSON_AGG(JSON_BUILD_OBJECT(
                                                'id', gr.id, 'position', gr.position, 'gridNumber', gr."gridNumber",
                                                'gridType', gr."gridType", 'concentration', gr.concentration,
                                                'specimen', gr.specimen, 'status', gr.status, 'notes', gr.notes,
                                                'images', """ + _imagesJson("gridId", "gr.id") + """)
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

    # Images ------------------------------------------------------------------------------------
    def sampleIdOf(self, ownerKind: str, ownerId: int) -> Optional[int]:
        """The sample a sample, box or grid belongs to (None: there is no such one)."""
        sql = {
            "sample": "SELECT id AS \"sampleId\" FROM facility_samples WHERE id = %s",
            "box": 'SELECT "sampleId" FROM facility_grid_boxes WHERE id = %s',
            "grid": 'SELECT b."sampleId" FROM facility_grids g JOIN facility_grid_boxes b ON b.id = g."boxId" '
                    "WHERE g.id = %s",
        }[ownerKind]
        row = self.db.fetchOne(sql, (int(ownerId),))
        return int(row["sampleId"]) if row else None

    def countImages(self, ownerKind: str, ownerId: int) -> int:
        row = self.db.fetchOne('SELECT COUNT(*) AS n FROM facility_images WHERE "%s" = %%s'
                               % IMAGE_OWNER_COLUMNS[ownerKind], (int(ownerId),))
        return int(row["n"])

    def insertImage(self, ownerKind: str, ownerId: int, caption: str, contentType: str, data: bytes,
                    userId: Optional[int]) -> Dict[str, Any]:
        import psycopg2

        with self.db.transaction():
            row = self.db.fetchOne(
                'INSERT INTO facility_images ("%s", caption, "contentType", data, "createdBy") '
                'VALUES (%%s, %%s, %%s, %%s, %%s) RETURNING id, caption, "createdAt"' % IMAGE_OWNER_COLUMNS[ownerKind],
                (int(ownerId), caption, contentType, psycopg2.Binary(data), userId))
        return dict(row)

    def getImage(self, imageId: int) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne(
            'SELECT i.id, i."contentType", i.data, i.caption, '
            'COALESCE(i."sampleId", b."sampleId", gb."sampleId") AS "sampleId" '
            "FROM facility_images i "
            'LEFT JOIN facility_grid_boxes b ON b.id = i."boxId" '
            'LEFT JOIN facility_grids g ON g.id = i."gridId" '
            'LEFT JOIN facility_grid_boxes gb ON gb.id = g."boxId" '
            "WHERE i.id = %s", (int(imageId),))
        return dict(row) if row else None

    def deleteImage(self, imageId: int) -> None:
        self.db.execute("DELETE FROM facility_images WHERE id = %s", (int(imageId),))

    def groupExists(self, groupId: int) -> bool:
        return self.db.fetchOne("SELECT 1 AS found FROM user_groups WHERE id = %s", (int(groupId),)) is not None

    def userExists(self, userId: int) -> bool:
        return self.db.fetchOne("SELECT 1 AS found FROM users WHERE id = %s", (int(userId),)) is not None
