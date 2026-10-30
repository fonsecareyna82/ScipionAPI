"""The queries of a facility's microscopes, their detectors and the detectors' calibrated pixel sizes."""
from typing import Any, Dict, List, Optional

MICROSCOPE_FIELDS = ("name", "model", "status", "energyFilter", "acquisitionSoftware", "voltageKv", "csMm",
                     "offloadPath", "sessionsEnabled", "notes")
DETECTOR_FIELDS = ("name", "metadataName", "energyFiltered", "gainPath", "gainFlip", "gainRotation", "notes")

LIST_MICROSCOPES_SQL = """
    SELECT m.id, m.name, m.model, m.status, m."energyFilter", m."acquisitionSoftware",
           m."voltageKv", m."csMm", m."offloadPath", m."sessionsEnabled", m.notes, m."createdAt", m."updatedAt",
           COALESCE((SELECT JSON_AGG(JSON_BUILD_OBJECT(
                         'id', d.id, 'name', d.name, 'metadataName', d."metadataName",
                         'energyFiltered', d."energyFiltered", 'gainPath', d."gainPath", 'gainFlip', d."gainFlip",
                         'gainRotation', d."gainRotation", 'notes', d.notes,
                         'pixelSizes', COALESCE((SELECT JSON_AGG(JSON_BUILD_OBJECT('magnification', p.magnification,
                                                                                   'pixelSize', p."pixelSize")
                                                                 ORDER BY p.magnification DESC)
                                                   FROM facility_detector_pixel_sizes p
                                                  WHERE p."detectorId" = d.id), '[]'::JSON))
                                     ORDER BY d.id)
                       FROM facility_detectors d WHERE d."microscopeId" = m.id), '[]'::JSON) AS detectors,
           (SELECT ph."updatedAt" FROM facility_microscope_photos ph WHERE ph."microscopeId" = m.id)
               AS "photoUpdatedAt"
      FROM facility_microscopes m
"""

SAVE_PHOTO_SQL = """
    INSERT INTO facility_microscope_photos ("microscopeId", "contentType", data)
    VALUES (%s, %s, %s)
    ON CONFLICT ("microscopeId") DO UPDATE
       SET "contentType" = EXCLUDED."contentType", data = EXCLUDED.data, "updatedAt" = NOW()
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


INSERT_MICROSCOPE_SQL = _insertSql("facility_microscopes", MICROSCOPE_FIELDS, {})
UPDATE_MICROSCOPE_SQL = _updateSql("facility_microscopes", MICROSCOPE_FIELDS, ', "updatedAt" = NOW()')
INSERT_DETECTOR_SQL = _insertSql("facility_detectors", DETECTOR_FIELDS, {"microscopeId": "%(microscopeId)s"})
UPDATE_DETECTOR_SQL = _updateSql("facility_detectors", DETECTOR_FIELDS)


class FacilityMicroscopePostgresqlMapper:
    def __init__(self, db):
        self.db = db

    def listMicroscopes(self) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.db.fetchAll(LIST_MICROSCOPES_SQL + " ORDER BY m.name") or []]

    def getMicroscope(self, microscopeId: int) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne(LIST_MICROSCOPES_SQL + " WHERE m.id = %s", (int(microscopeId),))
        return dict(row) if row else None

    def findMicroscopeIdByName(self, name: str) -> Optional[int]:
        row = self.db.fetchOne("SELECT id FROM facility_microscopes WHERE LOWER(name) = LOWER(%s)", (name,))
        return int(row["id"]) if row else None

    def saveMicroscope(self, microscopeId: Optional[int], values: Dict[str, Any],
                       detectors: List[Dict[str, Any]]) -> int:
        """Save a microscope and its detectors in one transaction: a detector with an id is updated, one
        without inserted, and the microscope's detectors missing from detectors deleted. Each detector's
        pixelSizes, (magnification, pixel size) pairs, replace its calibration."""
        with self.db.transaction():
            params = {field: values[field] for field in MICROSCOPE_FIELDS}
            if microscopeId is None:
                microscopeId = int(self.db.fetchOne(INSERT_MICROSCOPE_SQL, params)["id"])
            else:
                microscopeId = int(microscopeId)
                self.db.execute(UPDATE_MICROSCOPE_SQL, dict(params, id=microscopeId), commit=False)
            keptIds = []
            for detector in detectors:
                detectorParams = {field: detector[field] for field in DETECTOR_FIELDS}
                if detector.get("id") is None:
                    detectorId = int(self.db.fetchOne(INSERT_DETECTOR_SQL,
                                                      dict(detectorParams, microscopeId=microscopeId))["id"])
                else:
                    detectorId = int(detector["id"])
                    self.db.execute(UPDATE_DETECTOR_SQL, dict(detectorParams, id=detectorId), commit=False)
                keptIds.append(detectorId)
                self.db.execute('DELETE FROM facility_detector_pixel_sizes WHERE "detectorId" = %s',
                                (detectorId,), commit=False)
                for magnification, pixelSize in detector["pixelSizes"]:
                    self.db.execute('INSERT INTO facility_detector_pixel_sizes ("detectorId", magnification, '
                                    '"pixelSize") VALUES (%s, %s, %s)',
                                    (detectorId, int(magnification), float(pixelSize)), commit=False)
            self.db.execute('DELETE FROM facility_detectors WHERE "microscopeId" = %s AND NOT (id = ANY(%s))',
                            (microscopeId, keptIds), commit=False)
        return microscopeId

    def deleteMicroscope(self, microscopeId: int) -> None:
        self.db.execute("DELETE FROM facility_microscopes WHERE id = %s", (int(microscopeId),))

    def getPhoto(self, microscopeId: int) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne('SELECT "contentType", data, "updatedAt" FROM facility_microscope_photos '
                               'WHERE "microscopeId" = %s', (int(microscopeId),))
        return dict(row) if row else None

    def savePhoto(self, microscopeId: int, contentType: str, data: bytes) -> None:
        import psycopg2

        self.db.execute(SAVE_PHOTO_SQL, (int(microscopeId), contentType, psycopg2.Binary(data)))

    def deletePhoto(self, microscopeId: int) -> None:
        self.db.execute('DELETE FROM facility_microscope_photos WHERE "microscopeId" = %s', (int(microscopeId),))
