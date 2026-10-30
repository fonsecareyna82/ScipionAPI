"""A facility's samples (their NZ code), the grid boxes they were vitrified into and the grids in each box.

A sample is saved with its whole tree at once. A box or grid that exists keeps its id (a session's DATA
will point to its grid), so the tree a client sends names them by id; one without an id is new, and the
sample's boxes and grids the tree leaves out are deleted.
"""
import datetime
from typing import Any, Dict, List, Optional, Set

from fastapi import HTTPException, status

from app.backend.api.services.facility_service import PHOTO_CONTENT_TYPE, photoForWeb
from app.backend.mapper.facility_sample_mapper import (
    BOX_FIELDS, GRID_FIELDS, IMAGE_OWNER_COLUMNS, SAMPLE_FIELDS, FacilitySamplePostgresqlMapper,
)

GRID_STATUSES = ("stored", "loaded", "used", "discarded")
# Images of a sample, box or grid (a box photo, a grid's atlas or screening shot): kept as WebP up to this
IMAGE_MAX_SIDE = 2048
IMAGES_PER_OWNER = 20
GRID_POSITIONS = range(1, 13)
TEXT_LIMIT = 2000


def _badRequest(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _text(payload: Dict[str, Any], field: str, limit: int = TEXT_LIMIT) -> str:
    value = str(payload.get(field) or "").strip()
    if len(value) > limit:
        raise _badRequest("%s is longer than %d characters" % (field, limit))
    return value


def _optionalId(payload: Dict[str, Any], field: str) -> Optional[int]:
    value = payload.get(field)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise _badRequest("%s must be an id" % field)


def _date(value: Any) -> Optional[datetime.date]:
    if value is None or value == "":
        return None
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        raise _badRequest("Dates are written YYYY-MM-DD: %s" % value)


class FacilitySampleService:
    def __init__(self, db):
        self.mapper = FacilitySamplePostgresqlMapper(db)

    def listSamples(self, text: str = "") -> List[Dict[str, Any]]:
        return self.mapper.listSamples(str(text or "").strip()[:100])

    def getSample(self, sampleId: int) -> Dict[str, Any]:
        sample = self.mapper.getSample(sampleId)
        if sample is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sample not found")
        return sample

    def _sampleValues(self, payload: Dict[str, Any], sampleId: Optional[int]) -> Dict[str, Any]:
        code = _text(payload, "code", 40)
        if not code:
            raise _badRequest("A sample needs a code (e.g. NZ251)")
        sameCode = self.mapper.findSampleIdByCode(code)
        if sameCode is not None and sameCode != sampleId:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A sample coded %s exists" % code)
        groupId = _optionalId(payload, "groupId")
        if groupId is not None and not self.mapper.groupExists(groupId):
            raise _badRequest("Unknown group: %s" % groupId)
        ownerId = _optionalId(payload, "ownerId")
        if ownerId is not None and not self.mapper.userExists(ownerId):
            raise _badRequest("Unknown user: %s" % ownerId)
        values = {"code": code, "description": _text(payload, "description", 500), "groupId": groupId,
                  "ownerId": ownerId, "accessRoute": _text(payload, "accessRoute", 200), "notes": _text(payload, "notes")}
        assert set(values) == set(SAMPLE_FIELDS)
        return values

    def _grid(self, payload: Dict[str, Any], knownGridIds: Set[int]) -> Dict[str, Any]:
        gridId = _optionalId(payload, "id")
        if gridId is not None and gridId not in knownGridIds:
            raise _badRequest("Grid %d is not one of this sample's" % gridId)
        try:
            position = int(payload.get("position"))
        except (TypeError, ValueError):
            position = 0
        if position not in GRID_POSITIONS:
            raise _badRequest("A grid's position in its box is 1 to 12")
        gridNumber = _optionalId(payload, "gridNumber")
        if gridNumber is not None and gridNumber < 0:
            raise _badRequest("A grid number is not negative")
        statusValue = str(payload.get("status") or "stored")
        if statusValue not in GRID_STATUSES:
            raise _badRequest("Unknown grid status: %s" % statusValue)
        values = {"position": position, "gridNumber": gridNumber, "gridType": _text(payload, "gridType", 100),
                  "concentration": _text(payload, "concentration", 100), "specimen": _text(payload, "specimen", 300),
                  "status": statusValue, "notes": _text(payload, "notes")}
        assert set(values) == set(GRID_FIELDS)
        return dict(values, id=gridId)

    def _boxes(self, rows: List[Dict[str, Any]], existing: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        knownBoxIds = {int(box["id"]) for box in (existing or {}).get("boxes") or []}
        knownGridIds = {int(grid["id"]) for box in (existing or {}).get("boxes") or [] for grid in box["grids"]}
        boxes, labels, gridIds = [], set(), set()
        for row in rows or []:
            boxId = _optionalId(row, "id")
            if boxId is not None and boxId not in knownBoxIds:
                raise _badRequest("Box %d is not one of this sample's" % boxId)
            label = _text(row, "label", 60)
            if not label:
                raise _badRequest("Each box needs a label")
            if label.lower() in labels:
                raise _badRequest("Two boxes are labelled %s" % label)
            labels.add(label.lower())
            grids, positions = [], set()
            for gridRow in row.get("grids") or []:
                grid = self._grid(gridRow, knownGridIds)
                if grid["position"] in positions:
                    raise _badRequest("Box %s has two grids in position %d" % (label, grid["position"]))
                positions.add(grid["position"])
                if grid["id"] is not None:
                    if grid["id"] in gridIds:
                        raise _badRequest("Grid %d is given twice" % grid["id"])
                    gridIds.add(grid["id"])
                grids.append(grid)
            values = {"label": label, "vitrificationCode": _text(row, "vitrificationCode", 40),
                      "vitrifiedOn": _date(row.get("vitrifiedOn")), "notes": _text(row, "notes")}
            assert set(values) == set(BOX_FIELDS)
            boxes.append(dict(values, id=boxId, grids=grids))
        return boxes

    def saveSample(self, payload: Dict[str, Any], sampleId: Optional[int] = None) -> Dict[str, Any]:
        existing = self.getSample(sampleId) if sampleId is not None else None
        values = self._sampleValues(payload, sampleId)
        boxes = self._boxes(payload.get("boxes") or [], existing)
        return self.getSample(self.mapper.saveSample(sampleId, values, boxes))

    # Images ----------------------------------------------------------------------------------------
    def addImage(self, ownerKind: str, ownerId: int, data: bytes, caption: str = "",
                 userId: Optional[int] = None) -> Dict[str, Any]:
        """Keep an image of a sample, box or grid; answers it and the sample it went to."""
        if ownerKind not in IMAGE_OWNER_COLUMNS:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown kind: %s" % ownerKind)
        sampleId = self.mapper.sampleIdOf(ownerKind, ownerId)
        if sampleId is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such %s" % ownerKind)
        if self.mapper.countImages(ownerKind, ownerId) >= IMAGES_PER_OWNER:
            raise _badRequest("A %s keeps up to %d images" % (ownerKind, IMAGES_PER_OWNER))
        caption = str(caption or "").strip()[:200]
        image = self.mapper.insertImage(ownerKind, ownerId, caption, PHOTO_CONTENT_TYPE,
                                        photoForWeb(data, IMAGE_MAX_SIDE), userId)
        return {"image": image, "sample": self.getSample(sampleId)}

    def getImage(self, imageId: int) -> Dict[str, Any]:
        image = self.mapper.getImage(imageId)
        if image is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
        return image

    def deleteImage(self, imageId: int) -> Dict[str, Any]:
        """Remove an image; answers the sample it was in."""
        image = self.getImage(imageId)
        self.mapper.deleteImage(imageId)
        return self.getSample(int(image["sampleId"]))

    def deleteSample(self, sampleId: int) -> Dict[str, Any]:
        sample = self.getSample(sampleId)
        self.mapper.deleteSample(sampleId)
        return sample
