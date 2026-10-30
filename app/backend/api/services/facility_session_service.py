"""A facility's acquisition sessions: who a stay on a microscope is for, and the folders it writes.

A session's name makes its folders, ``<name>_ATLAS`` and ``<name>_DATA_NN``, the names the operator types into
EPU; it follows the facility's convention (``YYYY_MM_DD_<Name-Surname>_<6-digit id>``) unless one is given, and
holds still once the acquisition starts. Each DATA is a grid of a sample (multigrid: up to twelve), so a dataset
says what was acquired; the session keeps its ATLAS always. A session saved with its datasets keeps their ids:
the watcher will record on them the detector that took them and the project that processes them.
"""
import datetime
import re
import unicodedata
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.backend.api.services.facility_sample_service import IMAGE_MAX_SIDE, IMAGES_PER_OWNER
from app.backend.api.services.facility_service import PHOTO_CONTENT_TYPE, photoForWeb
from app.backend.mapper.facility_microscope_mapper import FacilityMicroscopePostgresqlMapper
from app.backend.mapper.facility_session_mapper import (
    DATASET_FIELDS, SESSION_FIELDS, FacilitySessionPostgresqlMapper,
)

SESSION_STATUSES = ("planned", "acquiring", "finished", "archived")
# What the sessions list shows unless asked otherwise: the ones still to come or under way
ACTIVE_STATUSES = ("planned", "acquiring")
TECHNIQUES = ("spa", "tomo")
DATA_NUMBERS = range(1, 13)
SESSION_IMAGE_OWNERS = ("session", "dataset")
# A folder name EPU and every file system take
SESSION_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
SESSION_NAME_LIMIT = 100
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


def _nameWord(text: str) -> str:
    """Text as a part of a folder name: plain letters and digits, words joined by '-'."""
    ascii = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return "-".join(re.findall(r"[A-Za-z0-9]+", ascii))


def sessionName(day: datetime.date, person: str, sessionId: int) -> str:
    """The facility's name for a session: YYYY_MM_DD_<Name-Surname>_<6-digit id>."""
    return "%s_%s_%06d" % (day.strftime("%Y_%m_%d"), _nameWord(person) or "Facility", sessionId)


def datasetFolder(sessionName: str, dataset: Dict[str, Any]) -> str:
    """The folder the microscope writes a dataset to."""
    if dataset["kind"] == "atlas":
        return "%s_ATLAS" % sessionName
    return "%s_DATA_%02d" % (sessionName, int(dataset["number"]))


class FacilitySessionService:
    def __init__(self, db):
        self.mapper = FacilitySessionPostgresqlMapper(db)
        self.microscopes = FacilityMicroscopePostgresqlMapper(db)

    def _withFolders(self, session: Dict[str, Any]) -> Dict[str, Any]:
        for dataset in session.get("datasets") or []:
            dataset["folder"] = datasetFolder(session["name"], dataset)
        return session

    def listSessions(self, statuses: Optional[List[str]] = None, text: str = "") -> List[Dict[str, Any]]:
        unknown = [value for value in statuses or [] if value not in SESSION_STATUSES]
        if unknown:
            raise _badRequest("Unknown session status: %s" % ", ".join(unknown))
        return [self._withFolders(session)
                for session in self.mapper.listSessions(statuses, str(text or "").strip()[:100])]

    def getSession(self, sessionId: int) -> Dict[str, Any]:
        session = self.mapper.getSession(sessionId)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        return self._withFolders(session)

    def _person(self, userId: Optional[int], groupId: Optional[int]) -> str:
        """Who a session is named after: its user (name and surname, else the address), else its group."""
        user = self.mapper.getUser(userId) if userId is not None else None
        if user:
            full = "%s %s" % (user.get("firstName") or "", user.get("lastName") or "")
            return full.strip() or str(user.get("email") or "").split("@")[0]
        return (self.mapper.getGroupName(groupId) if groupId is not None else None) or ""

    def _name(self, payload: Dict[str, Any], existing: Optional[Dict[str, Any]], sessionId: int,
              userId: Optional[int], groupId: Optional[int], scheduledOn: Optional[datetime.date]) -> str:
        name = _text(payload, "name", SESSION_NAME_LIMIT)
        if not name:
            if existing:
                return existing["name"]
            return sessionName(scheduledOn or datetime.date.today(), self._person(userId, groupId), sessionId)
        if not SESSION_NAME_PATTERN.match(name):
            raise _badRequest("A session's name makes folder names: letters, digits, '_', '-' and '.' only")
        if existing and name != existing["name"] and existing["status"] != "planned":
            raise _badRequest("The name stays once the acquisition started: the microscope writes its folders")
        sameName = self.mapper.findSessionIdByName(name)
        if sameName is not None and sameName != sessionId:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A session named %s exists" % name)
        return name

    def _datasets(self, rows: List[Dict[str, Any]], existing: Optional[Dict[str, Any]],
                  detectorIds: set) -> List[Dict[str, Any]]:
        """The datasets of a save: one ATLAS always (its id kept), and DATA_01..12 each with its grid."""
        known = {int(dataset["id"]): dataset for dataset in (existing or {}).get("datasets") or []}
        atlas = next((dataset for dataset in known.values() if dataset["kind"] == "atlas"), None)
        datasets = [{"id": atlas["id"] if atlas else None, "kind": "atlas", "number": 0, "gridId": None,
                     "detectorId": None, "notes": atlas["notes"] if atlas else ""}]
        numbers, ids = set(), set()
        for row in rows or []:
            datasetId = _optionalId(row, "id")
            if datasetId is not None:
                if datasetId not in known:
                    raise _badRequest("Dataset %d is not one of this session's" % datasetId)
                if datasetId in ids:
                    raise _badRequest("Dataset %d is given twice" % datasetId)
                ids.add(datasetId)
            if str(row.get("kind") or "data") == "atlas":
                if datasetId is not None and known[datasetId]["kind"] != "atlas":
                    raise _badRequest("Dataset %d is not the session's ATLAS" % datasetId)
                datasets[0]["notes"] = _text(row, "notes")
                continue
            if datasetId is not None and known[datasetId]["kind"] == "atlas":
                raise _badRequest("Dataset %d is the session's ATLAS" % datasetId)
            number = _optionalId(row, "number")
            if number not in DATA_NUMBERS:
                raise _badRequest("A session has DATA_01 to DATA_12")
            if number in numbers:
                raise _badRequest("DATA_%02d is given twice" % number)
            numbers.add(number)
            gridId = _optionalId(row, "gridId")
            if gridId is not None and not self.mapper.gridExists(gridId):
                raise _badRequest("Unknown grid: %s" % gridId)
            detectorId = _optionalId(row, "detectorId")
            if detectorId is not None and detectorId not in detectorIds:
                raise _badRequest("Detector %d is not one of this session's microscope" % detectorId)
            values = {"kind": "data", "number": number, "gridId": gridId, "detectorId": detectorId,
                      "notes": _text(row, "notes")}
            assert set(values) == set(DATASET_FIELDS)
            datasets.append(dict(values, id=datasetId))
        return datasets

    def saveSession(self, payload: Dict[str, Any], sessionId: Optional[int] = None,
                    userId: Optional[int] = None) -> Dict[str, Any]:
        """Create or edit a session with its datasets; userId is who creates it."""
        existing = self.getSession(sessionId) if sessionId is not None else None
        microscopeId = _optionalId(payload, "microscopeId")
        microscope = self.microscopes.getMicroscope(microscopeId) if microscopeId is not None else None
        if microscope is None:
            raise _badRequest("A session needs a microscope that exists")
        if existing is None and not microscope["sessionsEnabled"]:
            raise _badRequest("%s does not run sessions: turn them on in its settings" % microscope["name"])
        technique = str(payload.get("technique") or "spa")
        if technique not in TECHNIQUES:
            raise _badRequest("Unknown technique: %s" % technique)
        statusValue = str(payload.get("status") or "planned")
        if statusValue not in SESSION_STATUSES:
            raise _badRequest("Unknown session status: %s" % statusValue)
        groupId = _optionalId(payload, "groupId")
        if groupId is not None and not self.mapper.groupExists(groupId):
            raise _badRequest("Unknown group: %s" % groupId)
        sessionUserId = _optionalId(payload, "userId")
        if sessionUserId is not None and self.mapper.getUser(sessionUserId) is None:
            raise _badRequest("Unknown user: %s" % sessionUserId)
        scheduledOn = _date(payload.get("scheduledOn"))

        isNew = existing is None
        if isNew:
            sessionId = self.mapper.nextSessionId()
        now = datetime.datetime.now(datetime.timezone.utc)
        startedAt = (existing or {}).get("startedAt")
        finishedAt = (existing or {}).get("finishedAt")
        if statusValue != "planned" and startedAt is None:
            startedAt = now
        if statusValue in ("finished", "archived") and finishedAt is None:
            finishedAt = now
        values = {
            "name": self._name(payload, existing, sessionId, sessionUserId, groupId, scheduledOn),
            "microscopeId": microscopeId, "technique": technique, "status": statusValue, "groupId": groupId,
            "userId": sessionUserId, "bookingRef": _text(payload, "bookingRef", 100), "scheduledOn": scheduledOn,
            "startedAt": startedAt, "finishedAt": finishedAt, "notes": _text(payload, "notes"),
        }
        assert set(values) == set(SESSION_FIELDS)
        detectorIds = {int(detector["id"]) for detector in microscope.get("detectors") or []}
        datasets = self._datasets(payload.get("datasets") or [], existing, detectorIds)
        return self.getSession(self.mapper.saveSession(sessionId, isNew, values, datasets, createdBy=userId))

    def deleteSession(self, sessionId: int) -> Dict[str, Any]:
        """Only a session still planned goes; one that acquired is history, to archive."""
        session = self.getSession(sessionId)
        if session["status"] != "planned":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Only a planned session can be deleted; archive this one instead")
        self.mapper.deleteSession(sessionId)
        return session

    # Images ----------------------------------------------------------------------------------------
    def addImage(self, ownerKind: str, ownerId: int, data: bytes, caption: str = "",
                 userId: Optional[int] = None) -> Dict[str, Any]:
        """Keep an image of a session or dataset; answers it and the session it went to."""
        if ownerKind not in SESSION_IMAGE_OWNERS:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown kind: %s" % ownerKind)
        sessionId = self.mapper.sessionIdOf(ownerKind, ownerId)
        if sessionId is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such %s" % ownerKind)
        if self.mapper.countImages(ownerKind, ownerId) >= IMAGES_PER_OWNER:
            raise _badRequest("A %s keeps up to %d images" % (ownerKind, IMAGES_PER_OWNER))
        caption = str(caption or "").strip()[:200]
        image = self.mapper.insertImage(ownerKind, ownerId, caption, PHOTO_CONTENT_TYPE,
                                        photoForWeb(data, IMAGE_MAX_SIDE), userId)
        return {"image": image, "session": self.getSession(sessionId)}

    def deleteImage(self, imageId: int) -> Dict[str, Any]:
        """Remove an image of a session or dataset; answers the session it was in."""
        image = self.mapper.getImage(imageId)
        if image is None or image.get("sessionId") is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
        self.mapper.deleteImage(imageId)
        return self.getSession(int(image["sessionId"]))
