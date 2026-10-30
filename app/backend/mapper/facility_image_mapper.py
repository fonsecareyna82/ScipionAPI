"""The queries of the facility's images: those of samples, boxes and grids, and of sessions and their datasets."""
from typing import Any, Dict, Optional

# Who an image belongs to, and its column
IMAGE_OWNER_COLUMNS = {"sample": "sampleId", "box": "boxId", "grid": "gridId",
                       "session": "sessionId", "dataset": "datasetId"}


def imagesJson(ownerColumn: str, ownerId: str) -> str:
    """The images of one owner as a tree lists them: what they are, never their bytes."""
    return ("""COALESCE((SELECT JSON_AGG(JSON_BUILD_OBJECT('id', i.id, 'caption', i.caption, 'createdAt', i."createdAt")
                                ORDER BY i.id)
                       FROM facility_images i WHERE i."%s" = %s), '[]'::JSON)""" % (ownerColumn, ownerId))


class FacilityImagePostgresqlMapper:
    def __init__(self, db):
        self.db = db

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
        """An image with the sample or the session it is in (the other one None)."""
        row = self.db.fetchOne(
            'SELECT i.id, i."contentType", i.data, i.caption, '
            'COALESCE(i."sampleId", b."sampleId", gb."sampleId") AS "sampleId", '
            'COALESCE(i."sessionId", d."sessionId") AS "sessionId" '
            "FROM facility_images i "
            'LEFT JOIN facility_grid_boxes b ON b.id = i."boxId" '
            'LEFT JOIN facility_grids g ON g.id = i."gridId" '
            'LEFT JOIN facility_grid_boxes gb ON gb.id = g."boxId" '
            'LEFT JOIN facility_session_datasets d ON d.id = i."datasetId" '
            "WHERE i.id = %s", (int(imageId),))
        return dict(row) if row else None

    def deleteImage(self, imageId: int) -> None:
        self.db.execute("DELETE FROM facility_images WHERE id = %s", (int(imageId),))
