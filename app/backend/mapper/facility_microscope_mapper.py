"""The queries of a facility's microscopes and their calibrated pixel sizes."""
from typing import Any, Dict, Iterable, List, Optional, Tuple

MICROSCOPE_FIELDS = ("name", "model", "status", "detectors", "energyFilter", "acquisitionSoftware", "voltageKv",
                     "csMm", "gainPath", "gainFlip", "gainRotation", "offloadPath", "sessionsEnabled", "notes")

LIST_MICROSCOPES_SQL = """
    SELECT m.id, m.name, m.model, m.status, m.detectors, m."energyFilter", m."acquisitionSoftware",
           m."voltageKv", m."csMm", m."gainPath", m."gainFlip", m."gainRotation", m."offloadPath",
           m."sessionsEnabled", m.notes, m."createdAt", m."updatedAt",
           COALESCE((SELECT JSON_AGG(JSON_BUILD_OBJECT('magnification', p.magnification,
                                                       'pixelSize', p."pixelSize")
                                     ORDER BY p.magnification DESC)
                       FROM facility_microscope_pixel_sizes p
                      WHERE p."microscopeId" = m.id), '[]'::JSON) AS "pixelSizes"
      FROM facility_microscopes m
"""

_COLUMNS = ", ".join('"%s"' % field if field != field.lower() else field for field in MICROSCOPE_FIELDS)
_PLACEHOLDERS = ", ".join("%%(%s)s" % field for field in MICROSCOPE_FIELDS)
_ASSIGNMENTS = ", ".join(('"%s"' % field if field != field.lower() else field) + " = %%(%s)s" % field
                         for field in MICROSCOPE_FIELDS)

INSERT_MICROSCOPE_SQL = "INSERT INTO facility_microscopes (%s) VALUES (%s) RETURNING id" % (_COLUMNS, _PLACEHOLDERS)
UPDATE_MICROSCOPE_SQL = 'UPDATE facility_microscopes SET %s, "updatedAt" = NOW() WHERE id = %%(id)s' % _ASSIGNMENTS


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

    def insertMicroscope(self, values: Dict[str, Any], pixelSizes: Iterable[Tuple[int, float]]) -> int:
        with self.db.transaction():
            row = self.db.fetchOne(INSERT_MICROSCOPE_SQL, {field: values[field] for field in MICROSCOPE_FIELDS})
            self._replacePixelSizes(int(row["id"]), pixelSizes)
        return int(row["id"])

    def updateMicroscope(self, microscopeId: int, values: Dict[str, Any],
                         pixelSizes: Iterable[Tuple[int, float]]) -> None:
        with self.db.transaction():
            params = {field: values[field] for field in MICROSCOPE_FIELDS}
            params["id"] = int(microscopeId)
            self.db.execute(UPDATE_MICROSCOPE_SQL, params, commit=False)
            self._replacePixelSizes(int(microscopeId), pixelSizes)

    def deleteMicroscope(self, microscopeId: int) -> None:
        self.db.execute("DELETE FROM facility_microscopes WHERE id = %s", (int(microscopeId),))

    def _replacePixelSizes(self, microscopeId: int, pixelSizes: Iterable[Tuple[int, float]]) -> None:
        self.db.execute('DELETE FROM facility_microscope_pixel_sizes WHERE "microscopeId" = %s',
                        (microscopeId,), commit=False)
        for magnification, pixelSize in pixelSizes:
            self.db.execute('INSERT INTO facility_microscope_pixel_sizes ("microscopeId", magnification, "pixelSize") '
                            "VALUES (%s, %s, %s)", (microscopeId, int(magnification), float(pixelSize)),
                            commit=False)
