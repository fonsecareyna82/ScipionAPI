"""Running a facility in ScipionWeb: its mode and its microscopes.

Facility mode is set per installation (``SCIPIONWEB_FACILITY_MODE``, off by default). Off, ScipionWeb
is what it always was: the facility routes answer as if they did not exist and the web shows no
facility menu. Projects never depend on it; a session only points to the projects it makes.
"""
import math
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import HTTPException, status

from app.backend.api.permissions import hasPermission
from app.backend.mapper.facility_microscope_mapper import MICROSCOPE_FIELDS, FacilityMicroscopePostgresqlMapper

MICROSCOPE_STATUSES = ("operational", "maintenance", "out_of_service")
GAIN_FLIPS = ("none", "horizontal", "vertical")
GAIN_ROTATIONS = (0, 90, 180, 270)
# A nominal pixel read from the acquisition metadata matches a calibrated one within this (A): EPU writes
# them with more or fewer decimals than the calibration table
PIXEL_SIZE_TOLERANCE = 0.02
FACILITY_PERMISSIONS = ("facility.monitor", "facility.thresholds", "facility.sessions", "facility.manage")
# A microscope's photo: what may be uploaded, and what it is kept as (a web image, a few hundred KB)
PHOTO_MAX_UPLOAD_BYTES = 15 * 1024 * 1024
PHOTO_MAX_SIDE = 1600
PHOTO_CONTENT_TYPE = "image/webp"
TEXT_LIMIT = 2000


def facilityModeEnabled() -> bool:
    return str(os.environ.get("SCIPIONWEB_FACILITY_MODE") or "").strip().lower() in ("1", "true", "yes", "on")


def requireFacilityMode() -> None:
    """A route dependency: without facility mode the facility routes do not exist."""
    if not facilityModeEnabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facility mode is off")


def facilityStatus(user: dict) -> Dict[str, Any]:
    """What the web needs to draw the facility menu for user."""
    enabled = facilityModeEnabled()
    permissions = [name for name in FACILITY_PERMISSIONS if enabled and hasPermission(user, name)]
    return {"enabled": enabled, "permissions": permissions}


def isFacilityStaff(user: dict) -> bool:
    return any(hasPermission(user, name) for name in FACILITY_PERMISSIONS)


def calibratedPixelSize(pixelSizes: Iterable[Dict[str, Any]], magnification: Optional[float] = None,
                        nominalPixelSize: Optional[float] = None,
                        tolerance: float = PIXEL_SIZE_TOLERANCE) -> Optional[float]:
    """The calibrated pixel size of a microscope for an acquisition, or None to keep the nominal one.

    By magnification when the metadata gives it; otherwise the calibrated size nearest the nominal one,
    if within tolerance.
    """
    table = [(int(row["magnification"]), float(row["pixelSize"])) for row in pixelSizes or ()]
    if magnification is not None:
        for tableMagnification, pixelSize in table:
            if tableMagnification == int(round(float(magnification))):
                return pixelSize
    if nominalPixelSize is not None and table:
        nearest = min(table, key=lambda row: abs(row[1] - float(nominalPixelSize)))
        if abs(nearest[1] - float(nominalPixelSize)) <= tolerance:
            return nearest[1]
    return None


def _badRequest(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _text(payload: Dict[str, Any], field: str, limit: int = TEXT_LIMIT) -> str:
    value = str(payload.get(field) or "").strip()
    if len(value) > limit:
        raise _badRequest("%s is longer than %d characters" % (field, limit))
    return value


def _positiveNumber(payload: Dict[str, Any], field: str) -> Optional[float]:
    value = payload.get(field)
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise _badRequest("%s must be a number" % field)
    if not math.isfinite(number) or number <= 0:
        raise _badRequest("%s must be a positive number" % field)
    return number


def _pixelSizes(rows: Iterable[Dict[str, Any]]) -> List[Tuple[int, float]]:
    table: Dict[int, float] = {}
    for row in rows or ():
        try:
            magnification = int(row.get("magnification"))
            pixelSize = float(row.get("pixelSize"))
        except (TypeError, ValueError, AttributeError):
            raise _badRequest("Each calibrated pixel size needs a magnification and a pixel size")
        if magnification <= 0 or not math.isfinite(pixelSize) or not 0 < pixelSize < 100:
            raise _badRequest("Magnifications must be positive and pixel sizes between 0 and 100 A")
        if magnification in table:
            raise _badRequest("Magnification %d is calibrated twice" % magnification)
        table[magnification] = pixelSize
    return sorted(table.items(), reverse=True)


def photoForWeb(data: bytes) -> bytes:
    """An uploaded photo as a WebP of at most PHOTO_MAX_SIDE, turned as the camera held it; 400 if no image."""
    import io

    from PIL import Image, ImageOps, UnidentifiedImageError

    if not data:
        raise _badRequest("The photo is empty")
    if len(data) > PHOTO_MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="Photos may be up to %d MB" % (PHOTO_MAX_UPLOAD_BYTES // (1024 * 1024)))
    try:
        image = Image.open(io.BytesIO(data))
        if image.format not in ("PNG", "JPEG", "WEBP"):
            raise _badRequest("The photo must be a PNG, JPEG or WebP image")
        image = ImageOps.exif_transpose(image)
        image.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE))
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        output = io.BytesIO()
        image.save(output, format="WEBP", quality=85)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise _badRequest("The photo is not an image that can be read")
    return output.getvalue()


class FacilityService:
    def __init__(self, db):
        self.mapper = FacilityMicroscopePostgresqlMapper(db)

    def listMicroscopes(self) -> List[Dict[str, Any]]:
        return self.mapper.listMicroscopes()

    def getMicroscope(self, microscopeId: int) -> Dict[str, Any]:
        microscope = self.mapper.getMicroscope(microscopeId)
        if microscope is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Microscope not found")
        return microscope

    def _microscopeValues(self, payload: Dict[str, Any], microscopeId: Optional[int]) -> Dict[str, Any]:
        name = _text(payload, "name", 100)
        if not name:
            raise _badRequest("A microscope needs a name")
        sameName = self.mapper.findMicroscopeIdByName(name)
        if sameName is not None and sameName != microscopeId:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A microscope named %s exists" % name)
        statusValue = str(payload.get("status") or "operational")
        if statusValue not in MICROSCOPE_STATUSES:
            raise _badRequest("Unknown microscope status: %s" % statusValue)
        gainFlip = str(payload.get("gainFlip") or "none")
        if gainFlip not in GAIN_FLIPS:
            raise _badRequest("Unknown gain flip: %s" % gainFlip)
        try:
            gainRotation = int(payload.get("gainRotation") or 0)
        except (TypeError, ValueError):
            gainRotation = -1
        if gainRotation not in GAIN_ROTATIONS:
            raise _badRequest("The gain rotation is 0, 90, 180 or 270 degrees")
        values = {
            "name": name,
            "model": _text(payload, "model", 200),
            "status": statusValue,
            "detectors": _text(payload, "detectors", 500),
            "energyFilter": _text(payload, "energyFilter", 200),
            "acquisitionSoftware": _text(payload, "acquisitionSoftware", 500),
            "voltageKv": _positiveNumber(payload, "voltageKv"),
            "csMm": _positiveNumber(payload, "csMm"),
            "gainPath": _text(payload, "gainPath"),
            "gainFlip": gainFlip,
            "gainRotation": gainRotation,
            "offloadPath": _text(payload, "offloadPath"),
            "sessionsEnabled": bool(payload.get("sessionsEnabled")),
            "notes": _text(payload, "notes"),
        }
        assert set(values) == set(MICROSCOPE_FIELDS)
        return values

    def saveMicroscope(self, payload: Dict[str, Any], microscopeId: Optional[int] = None) -> Dict[str, Any]:
        if microscopeId is not None:
            self.getMicroscope(microscopeId)
        values = self._microscopeValues(payload, microscopeId)
        pixelSizes = _pixelSizes(payload.get("pixelSizes") or [])
        if microscopeId is None:
            microscopeId = self.mapper.insertMicroscope(values, pixelSizes)
        else:
            self.mapper.updateMicroscope(microscopeId, values, pixelSizes)
        return self.getMicroscope(microscopeId)

    def getPhoto(self, microscopeId: int) -> Dict[str, Any]:
        self.getMicroscope(microscopeId)
        photo = self.mapper.getPhoto(microscopeId)
        if photo is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This microscope has no photo")
        return photo

    def savePhoto(self, microscopeId: int, data: bytes) -> Dict[str, Any]:
        """Keep an uploaded PNG, JPEG or WebP photo, reduced to PHOTO_MAX_SIDE and stored as WebP."""
        self.getMicroscope(microscopeId)
        self.mapper.savePhoto(microscopeId, PHOTO_CONTENT_TYPE, photoForWeb(data))
        return self.getMicroscope(microscopeId)

    def deletePhoto(self, microscopeId: int) -> Dict[str, Any]:
        self.getMicroscope(microscopeId)
        self.mapper.deletePhoto(microscopeId)
        return self.getMicroscope(microscopeId)

    def deleteMicroscope(self, microscopeId: int) -> Dict[str, Any]:
        microscope = self.getMicroscope(microscopeId)
        self.mapper.deleteMicroscope(microscopeId)
        return microscope
