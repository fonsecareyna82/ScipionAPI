"""A facility's acquisition sessions: who a stay on a microscope is for, and the folders it writes.

A session's name makes its folders (by its microscope's patterns, e.g. ``<name>_ATLAS`` and ``<name>_DATA_NN``),
the names the operator types into EPU; it follows the facility's pattern (``facility_conventions``) unless one
is given, and holds still once the acquisition starts. Each dataset keeps the folder it was given. Each DATA is a grid of a sample (multigrid: up to twelve), so a dataset
says what was acquired; the session keeps its ATLAS always. A session saved with its datasets keeps their ids:
the watcher will record on them the detector that took them and the project that processes them.
"""
import datetime
import re
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.backend.api.services import facility_conventions as conventions
from app.backend.api.services.facility_sample_service import IMAGE_MAX_SIDE, IMAGES_PER_OWNER
from app.backend.api.services.facility_settings_service import FacilitySettingsService
from app.backend.api.services.facility_service import PHOTO_CONTENT_TYPE, photoForWeb
from app.backend.mapper.facility_microscope_mapper import FacilityMicroscopePostgresqlMapper
from app.backend.mapper.facility_session_mapper import (
    DATASET_FIELDS, SESSION_FIELDS, FacilitySessionPostgresqlMapper,
)

SESSION_STATUSES = ("planned", "acquiring", "finished", "archived")
# What the sessions list shows unless asked otherwise: the ones still to come or under way
ACTIVE_STATUSES = ("planned", "acquiring")
TECHNIQUES = ("spa", "tomo")
CTF_LIMIT_FIELDS = ("ctfMinDefocus", "ctfMaxDefocus", "ctfMaxResolution")
SESSION_IMAGE_OWNERS = ("session", "dataset")
# What a session's user (and the group's PI) see of it: none of what is the staff's
USER_SESSION_FIELDS = ("id", "name", "microscopeName", "technique", "status", "groupName", "userName", "userEmail",
                       "bookingRef", "scheduledOn", "startedAt", "finishedAt", "userNotes", "images", "retention")
USER_DATASET_FIELDS = ("id", "kind", "number", "folder", "grid", "detectorName", "watch", "movieCount", "movieBytes",
                       "firstMovieAt", "lastMovieAt", "acquisition", "projectId", "images", "navigation", "atlas")
USER_SAMPLE_FIELDS = ("id", "code", "description", "groupName", "ownerName", "ownerEmail", "boxes", "images",
                      "createdAt")
# A folder name EPU and every file system take
SESSION_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
SESSION_NAME_LIMIT = 100
# A DATA acquiring that got no movie for this long is shown stalled
STALL_MINUTES = 20
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


def watchState(session: Dict[str, Any], dataset: Dict[str, Any], stallMinutes: float = STALL_MINUTES) -> Optional[str]:
    """Where a DATA is in its acquisition, as the watcher of the folders saw it.

    receiving / stalled (no movie for stallMinutes, the facility's) once movies arrived, and acquired once the session no
    longer acquires; while none did: idle (the session does not acquire), noOffload (its microscope has no
    offload folder), pending (not looked at yet), noFolder (the microscope has not made it) or waiting.
    The ATLAS: atlasFound once it has files, else as a DATA without movies (None once not acquiring).
    """
    acquiring = session["status"] == "acquiring"
    if dataset["kind"] == "atlas":
        # Its files, not movies: whether the microscope made it and wrote in it
        if (dataset.get("atlas") or {}).get("files"):
            return "atlasFound"
        if not acquiring:
            return None
        if not session.get("offloadPath"):
            return "noOffload"
        if dataset.get("scannedAt") is None:
            return "pending"
        return "noFolder" if dataset.get("folderFound") is False else "waiting"
    if dataset["kind"] != "data":
        return None
    if dataset.get("movieCount"):
        if not acquiring:
            return "acquired"
        minutes = dataset.get("minutesSinceLastMovie")
        return "stalled" if minutes is not None and minutes > stallMinutes else "receiving"
    if not acquiring:
        return "idle"
    if not session.get("offloadPath"):
        return "noOffload"
    if dataset.get("scannedAt") is None:
        return "pending"
    return "noFolder" if dataset.get("folderFound") is False else "waiting"


def datasetFolder(sessionName: str, dataset: Dict[str, Any], microscope: Dict[str, Any]) -> str:
    """The folder the microscope writes a dataset to, by its patterns."""
    code = conventions.microscopeCode(microscope)
    if dataset["kind"] == "atlas":
        return conventions.folderName(microscope.get("atlasFolderPattern") or conventions.DEFAULT_ATLAS_FOLDER_PATTERN,
                                      sessionName, 0, code)
    return conventions.folderName(microscope.get("dataFolderPattern") or conventions.DEFAULT_DATA_FOLDER_PATTERN,
                                  sessionName, int(dataset["number"]), code)


class FacilitySessionService:
    def __init__(self, db):
        self.mapper = FacilitySessionPostgresqlMapper(db)
        self.microscopes = FacilityMicroscopePostgresqlMapper(db)

    def _stallMinutes(self) -> float:
        if not hasattr(self, "_stall"):
            self._stall = float(FacilitySettingsService(self.mapper.db).values()["stallMinutes"])
        return self._stall

    def _withFolders(self, session: Dict[str, Any]) -> Dict[str, Any]:
        stall = self._stallMinutes()
        for dataset in session.get("datasets") or []:
            dataset["watch"] = watchState(session, dataset, stall)
            if session.get("technique") == "tomo" and dataset["kind"] == "data":
                # Where its navigation report is (tomo5-mapper), read from the facility's reports folder
                from app.backend.api.services.facility_navigation import navigationOf

                dataset["navigation"] = navigationOf(session, dataset)
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

    @staticmethod
    def _personWord(user: Optional[Dict[str, Any]]) -> str:
        """A person in names: Name-Surname, else the address' name."""
        if not user:
            return ""
        full = "%s %s" % (user.get("firstName") or "", user.get("lastName") or "")
        return conventions.nameWord(full.strip() or str(user.get("email") or "").split("@")[0])

    def _nameValues(self, payload: Dict[str, Any], sessionId: int, userId: Optional[int], groupId: Optional[int],
                    scheduledOn: Optional[datetime.date], microscope: Dict[str, Any], technique: str) -> Dict[str, Any]:
        """The pieces of the facility's session name pattern for this session."""
        user = self.mapper.getUser(userId) if userId is not None else None
        pi = self.mapper.getGroupPi(groupId) if groupId is not None else None
        group = self.mapper.getGroupName(groupId) if groupId is not None else None
        return {"date": scheduledOn or datetime.date.today(), "user": self._personWord(user), "pi": self._personWord(pi),
                "group": conventions.nameWord(group), "microscope": conventions.microscopeCode(microscope),
                "booking": conventions.nameWord(payload.get("bookingRef")), "technique": technique, "id": sessionId}

    def _name(self, payload: Dict[str, Any], existing: Optional[Dict[str, Any]], sessionId: int,
              nameValues: Dict[str, Any]) -> str:
        name = _text(payload, "name", SESSION_NAME_LIMIT)
        if not name:
            if existing:
                return existing["name"]
            pattern = FacilitySettingsService(self.mapper.db).sessionNamePattern()
            try:
                return conventions.sessionName(pattern, nameValues)
            except ValueError as error:
                raise _badRequest("The facility's session name pattern makes no name: %s" % error)
        if not SESSION_NAME_PATTERN.match(name):
            raise _badRequest("A session's name makes folder names: letters, digits, '_', '-' and '.' only")
        if existing and name != existing["name"] and existing["status"] != "planned":
            raise _badRequest("The name stays once the acquisition started: the microscope writes its folders")
        sameName = self.mapper.findSessionIdByName(name)
        if sameName is not None and sameName != sessionId:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A session named %s exists" % name)
        return name

    def _datasets(self, rows: List[Dict[str, Any]], existing: Optional[Dict[str, Any]],
                  microscope: Dict[str, Any], name: str) -> List[Dict[str, Any]]:
        """The datasets of a save: the ATLAS (its id kept; none when the microscope makes no atlas folder), and a
        DATA per position of the autoloader that has a grid. Each keeps its folder, made again only when the
        session (still planned) changes its name."""
        detectorIds = {int(detector["id"]) for detector in microscope.get("detectors") or []}
        slots = int(microscope.get("gridSlots") or 12)
        renamed = existing is not None and existing["name"] != name
        known = {int(dataset["id"]): dataset for dataset in (existing or {}).get("datasets") or []}

        def folder(dataset: Dict[str, Any], known: Optional[Dict[str, Any]]) -> str:
            if known and known.get("folder") and not renamed:
                return known["folder"]
            try:
                return datasetFolder(name, dataset, microscope)
            except ValueError as error:
                raise _badRequest("%s's folder patterns make no folder: %s" % (microscope["name"], error))

        atlas = next((dataset for dataset in known.values() if dataset["kind"] == "atlas"), None)
        datasets = []
        if atlas or str(microscope.get("atlasFolderPattern") or "").strip():
            datasets.append({"id": atlas["id"] if atlas else None, "kind": "atlas", "number": 0, "gridId": None,
                             "detectorId": None, "notes": atlas["notes"] if atlas else ""})
            datasets[0]["folder"] = folder(datasets[0], atlas)
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
                if datasets and datasets[0]["kind"] == "atlas":
                    datasets[0]["notes"] = _text(row, "notes")
                continue
            if datasetId is not None and known[datasetId]["kind"] == "atlas":
                raise _badRequest("Dataset %d is the session's ATLAS" % datasetId)
            number = _optionalId(row, "number")
            if number is None or not 1 <= number <= slots:
                raise _badRequest("%s's autoloader has positions 1 to %d" % (microscope["name"], slots))
            if number in numbers:
                raise _badRequest("Position %d is given twice" % number)
            numbers.add(number)
            gridId = _optionalId(row, "gridId")
            if gridId is not None and not self.mapper.gridExists(gridId):
                raise _badRequest("Unknown grid: %s" % gridId)
            detectorId = _optionalId(row, "detectorId")
            if detectorId is not None and detectorId not in detectorIds:
                raise _badRequest("Detector %d is not one of this session's microscope" % detectorId)
            values = {"kind": "data", "number": number, "gridId": gridId, "detectorId": detectorId,
                      "notes": _text(row, "notes")}
            values["folder"] = folder(values, known.get(datasetId) if datasetId is not None else None)
            assert set(values) == set(DATASET_FIELDS)
            datasets.append(dict(values, id=datasetId))
        folders = [dataset["folder"] for dataset in datasets]
        if len(set(folders)) != len(folders):
            raise _badRequest("Two of the session's folders would have the same name")
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
        elif statusValue in ("planned", "acquiring"):
            # Reopened (finished by mistake): it has not finished
            finishedAt = None
        values = {
            "name": self._name(payload, existing, sessionId,
                               self._nameValues(payload, sessionId, sessionUserId, groupId, scheduledOn, microscope,
                                                technique)),
            "microscopeId": microscopeId, "technique": technique, "status": statusValue, "groupId": groupId,
            "userId": sessionUserId, "bookingRef": _text(payload, "bookingRef", 100), "scheduledOn": scheduledOn,
            "startedAt": startedAt, "finishedAt": finishedAt, "notes": _text(payload, "notes"),
            # The workflow its DATA are processed with (an id of the web's workflow list), and whether by itself
            "templateId": _text(payload, "templateId", 300),
            "autoProcess": bool(payload.get("autoProcess", True)),
            # Every DATA in the session's project (each its own branch), instead of a project per DATA
            "oneProject": bool(payload.get("oneProject", False)),
            # What the technician tells the session's user (and the group's PI); notes stay the staff's
            "userNotes": _text(payload, "userNotes"),
            # The CTF consensus is SPA's: a tomography session has no limits to give
            **(self._ctfLimits(payload) if technique == "spa" else dict.fromkeys(CTF_LIMIT_FIELDS)),
        }
        assert set(values) == set(SESSION_FIELDS)
        datasets = self._datasets(payload.get("datasets") or [], existing, microscope, values["name"])
        saved = self.getSession(self.mapper.saveSession(sessionId, isNew, values, datasets, createdBy=userId))
        if saved["status"] == "acquiring":
            # Its grids are in the microscope now
            if self.mapper.markGrids(sessionId):
                saved = self.getSession(sessionId)
            # Its folders are looked at now, not at the watcher's next turn
            from app.backend.api.services.facility_session_watcher import requestWatch

            requestWatch()
        return saved

    def sessionsOf(self, user: Dict[str, Any]) -> Dict[str, Any]:
        """What a user sees of the facility ("My sessions"): their sessions and samples, and those of the groups they
        are the PI of, read only and without what is the staff's (their notes, the processing's messages)."""
        from app.backend.mapper.facility_sample_mapper import FacilitySamplePostgresqlMapper

        userId = int(user["id"])
        piGroups = self.mapper.piGroupIds(userId)
        settings = FacilitySettingsService(self.mapper.db).values()
        sessions = [self._forUser(self._withFolders(session), userId, settings)
                    for session in self.mapper.listSessionsOf(userId, piGroups)]
        samples = [{key: sample[key] for key in USER_SAMPLE_FIELDS if key in sample}
                   for sample in FacilitySamplePostgresqlMapper(self.mapper.db).listSamplesOf(userId, piGroups)]
        return {"sessions": sessions, "samples": samples, "isPi": bool(piGroups),
                "downloadInstructions": settings["downloadInstructions"],
                "rawRetentionDays": settings["rawRetentionDays"],
                "processedRetentionDays": settings["processedRetentionDays"]}

    @staticmethod
    def _forUser(session: Dict[str, Any], userId: int, settings: Dict[str, Any]) -> Dict[str, Any]:
        seen = {key: session[key] for key in USER_SESSION_FIELDS if key in session}
        seen["asPi"] = session.get("userId") != userId
        seen["datasets"] = []
        for dataset in session.get("datasets") or []:
            shown = {key: dataset[key] for key in USER_DATASET_FIELDS if key in dataset}
            shown["processing"] = {"state": dataset["processing"]["state"]} if dataset.get("processing") else None
            if shown.get("navigation"):
                # Whether its report is there, without the reason of a failure (it names the server's folders)
                shown["navigation"] = {key: shown["navigation"][key] for key in ("state", "finishedAt", "sizeBytes")}
            seen["datasets"].append(shown)
        # Until when its data are kept (its own dates or the facility's days), and whether they were deleted
        from app.backend.api.services import facility_retention as retention

        on = retention.today(settings["timezone"])
        seen["retention"] = {}
        for kind in retention.KINDS:
            state = retention.retentionState(session, kind, settings, on)
            seen["retention"][kind] = {key: state[key] for key in ("state", "until", "daysLeft", "deletedAt")}
        seen["rawKeptUntil"] = seen["retention"]["raw"]["until"]
        seen["processedKeptUntil"] = seen["retention"]["processed"]["until"]
        return seen

    @staticmethod
    def _ctfLimits(payload: Dict[str, Any]) -> Dict[str, Any]:
        """The CTF limits a session sets for its DATA's CTF consensus (None keeps the template's)."""
        limits = {}
        for field, label in (("ctfMinDefocus", "minimum defocus"), ("ctfMaxDefocus", "maximum defocus"),
                             ("ctfMaxResolution", "CTF resolution")):
            value = payload.get(field)
            if value is None or value == "":
                limits[field] = None
                continue
            try:
                limits[field] = float(value)
            except (TypeError, ValueError):
                raise _badRequest("The %s is a number (A)" % label)
            if not 0 < limits[field] < 1e6:
                raise _badRequest("The %s is a positive number of A" % label)
        if limits["ctfMinDefocus"] and limits["ctfMaxDefocus"] and limits["ctfMinDefocus"] >= limits["ctfMaxDefocus"]:
            raise _badRequest("The minimum defocus is below the maximum")
        return limits

    def queueProcessing(self, datasetId: int) -> Dict[str, Any]:
        """Ask for a DATA's project now (again, after a failure); the watcher makes it at its next turn."""
        dataset = self.mapper.getDatasetForProcessing(datasetId)
        if dataset is None or dataset["kind"] != "data":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DATA not found")
        if dataset["projectId"] is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This DATA has its project already")
        if not dataset["templateId"]:
            raise _badRequest("The session has no processing template")
        if dataset["status"] != "acquiring":
            raise _badRequest("Only the DATA of a session acquiring are processed")
        if not dataset["acquisition"] or dataset["acquisition"].get("error"):
            raise _badRequest("The first movie of this DATA has not been read yet")
        self.mapper.saveProcessing(datasetId, {"state": "queued", "at": datetime.datetime.now(
            datetime.timezone.utc).isoformat()})
        from app.backend.api.services.facility_session_watcher import requestWatch

        requestWatch()
        return self.getSession(int(dataset["sessionId"]))

    def rereadAcquisition(self, datasetId: int) -> Dict[str, Any]:
        """Read again what a DATA's first movie says (after fixing a detector's metadata name or calibration);
        answers the session. Its project, if made, keeps what it was made with."""
        from pathlib import Path

        from app.backend.api.services import facility_session_watcher as watcher
        from app.backend.mapper.facility_microscope_mapper import FacilityMicroscopePostgresqlMapper

        dataset = self.mapper.getDatasetToRead(datasetId)
        if dataset is None or dataset["kind"] != "data":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DATA not found")
        if not dataset["offloadPath"]:
            raise _badRequest("Its microscope has no offload folder")
        root = watcher.dataFolder(dataset["offloadPath"], dataset["folder"])
        scan = watcher.scanFolder(root, {}, 0.0, fullScanSeconds=0.0, technique=dataset.get("technique") or "spa")
        if not scan["exists"]:
            raise _badRequest("Its folder is not there: %s" % root)
        if not scan["count"]:
            raise _badRequest("Its folder has no movie yet")
        tolerance = float(FacilitySettingsService(self.mapper.db).values()["calibrationTolerancePercent"]) / 100
        microscope = FacilityMicroscopePostgresqlMapper(self.mapper.db).getMicroscope(int(dataset["microscopeId"]))
        acquisition = watcher.readFirstMovie(Path(scan["first"]), root, (microscope or {}).get("detectors") or [],
                                             dataset["detectorId"], tolerance)
        if acquisition is None:
            raise _badRequest("The metadata of its first movie is not there yet")
        self.mapper.saveAcquisition(datasetId, acquisition)
        return self.getSession(int(dataset["sessionId"]))

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
