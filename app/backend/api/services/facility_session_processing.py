"""Processing a session's DATA, as EMhub does: a project per DATA from the session's template, launched in streaming.

When the watcher has read a DATA's first movie (``facility_session_watcher``) and its session processes by itself
(``autoProcess``) with a template, the DATA gets the project ``<session>_DATA_NN``:

1. the template is made into its workflow (``ProjectService.materializeWorkflowTemplate``), its ``~...|alias~``
   fields filled with what the movie says when their alias is a known one (``TEMPLATE_ALIASES``);
2. its Import Movies (any template, whatever aliases it uses) reads the DATA folder in streaming, with the
   pattern of the movies EPU writes there, the detector's calibrated pixel, the voltage and magnification of the
   movie, the microscope's Cs, the dose per frame and the gain reference;
2b. its movie alignment turns that gain as the detector says (its gain flip and rotation): the detector's
   orientation tells how its gain reference lies against its movies;
3. by the facility's policy (projectOwner, projectShareLevel; the CNB's by default) the project belongs to who
   made the session (the staff), and its user and group see it read only: the facility's processing is not
   changed by those it is for; or it belongs to the session's user, and the staff who made it manage it. It
   runs from its Import Movies like "Restart all" in the web.

What happened is the dataset's ``processing`` (state queued, running, launched or error, and why); a DATA keeps
its project once made, so a failure after it leaves the project for the staff to look at.
"""
from __future__ import annotations

import datetime
import glob
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.backend.api.audit import recordAudit
from app.backend.api.permissions import hasPermission, withPermissions

logger = logging.getLogger(__name__)

IMPORT_MOVIES_CLASSES = ("ProtImportMovies",)
# Where a session's CTF limits go: the CTF consensus that drops micrographs out of them
CTF_CONSENSUS_CLASSES = ("XmippProtCTFConsensus",)
# The movie alignments that rotate (in steps of 90 degrees, counter-clockwise as MotionCor2's -RotGain) and flip
# (after rotating: 1 upside down, 2 left to right, as its -FlipGain) the gain reference
MOVIE_ALIGNMENT_CLASSES = ("ProtMotionCorr", "ProtMotionCorrTasks", "ProtMotionCorrNewStreaming", "ProtTsMotionCorr",
                           "ProtRelionMotioncor", "ProtRelionTomoMotionCorr", "XmippProtFlexAlign")
# Warp's flip the gain, without rotating it: 1 flips X (left to right), 2 flips Y (upside down)
WARP_ALIGNMENT_CLASSES = ("ProtWarpMotionCorr", "ProtWarpTSMotionCorr")
GAIN_FLIP_VALUES = {"none": 0, "vertical": 1, "horizontal": 2}
WARP_GAIN_FLIP_VALUES = {"none": 0, "horizontal": 1, "vertical": 2}
# Tomography in streaming: the tilt movies are imported as movies, and this composes the tilt series from the mdocs
COMPOSE_TILT_SERIES_CLASSES = ("ProtComposeTS",)
# The aliases of a template's ~Title|value|type|alias~ fields that take what the first movie says (whatever their
# case): EMhub's (moviesPath, filesPattern, voltage, spherical, magnification, sampling, dosePerFrame, the ones the
# CNB's templates use with `scipion template`), Scipion's demo ones (sr, volt, sa, dose) and the parameters' names
TEMPLATE_ALIASES = {
    "moviespath": "filesPath", "filespath": "filesPath", "pattern": "filesPattern", "filespattern": "filesPattern",
    "sampling": "samplingRate", "sr": "samplingRate", "samplingrate": "samplingRate",
    "voltage": "voltage", "volt": "voltage",
    "spherical": "sphericalAberration", "sa": "sphericalAberration", "cs": "sphericalAberration",
    "sphericalaberration": "sphericalAberration",
    "doseperframe": "dosePerFrame", "dose": "dosePerFrame",
    "gain": "gainFile", "gainfile": "gainFile", "mag": "magnification", "magnification": "magnification",
    "mindefocus": "ctfMinDefocus", "maxdefocus": "ctfMaxDefocus", "resolution": "ctfMaxResolution",
    "ctfresolution": "ctfMaxResolution",
}


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# Folder names that are the same for every grid square or tilt series: the pattern keeps them
FIXED_FOLDERS = ("data", "frames")


def _folderPattern(parts) -> List[str]:
    return ["Images-Disc*" if part.startswith("Images-Disc") else "GridSquare_*" if part.startswith("GridSquare_")
            else part if part.lower() in FIXED_FOLDERS else "*" for part in parts]


def moviesPattern(firstMovie: str) -> str:
    """The pattern of a DATA's movies from its first one (relative to the folder): EPU's grid squares and the
    movies' own ending, e.g. Images-Disc*/GridSquare_*/Data/*_Fractions.mrc; a folder per tilt series is any
    folder (*/frames/*.eer)."""
    parts = Path(firstMovie).parts
    folders = _folderPattern(parts[:-1])
    name = parts[-1]
    for mark in ("_Fractions.", "_EER."):
        if mark in name:
            return "/".join(folders + ["*" + name[name.index(mark):]])
    return "/".join(folders + ["*" + Path(name).suffix])


def mdocPattern(metadataPath: Optional[str]) -> Optional[str]:
    """The pattern of a DATA's tilt-series mdocs from the one read (relative to the folder): *.mdoc, */frames/*.mdoc."""
    if not metadataPath or not str(metadataPath).lower().endswith(".mdoc"):
        return None
    return "/".join(_folderPattern(Path(metadataPath).parts[:-1]) + ["*.mdoc"])


def gainReference(acquisition: Dict[str, Any], detector: Optional[Dict[str, Any]]) -> Optional[str]:
    """The gain reference: the one EPU left in the DATA folder, else the detector's (the newest file of its
    pattern, e.g. /data/gains/*Talos*gain*.mrc)."""
    if acquisition.get("gainFile"):
        return acquisition["gainFile"]
    pattern = str((detector or {}).get("gainPath") or "").strip()
    if not pattern:
        return None
    matches = [path for path in glob.glob(pattern) if os.path.isfile(path)] if glob.has_magic(pattern) else (
        [pattern] if os.path.isfile(pattern) else [])
    return max(matches, key=os.path.getmtime) if matches else None


def importValues(folder: str, acquisition: Dict[str, Any], csMm: Optional[float],
                 detector: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """What the Import Movies of a DATA's project reads: its folder and what the first movie says."""
    values = {
        "filesPath": folder,
        "filesPattern": moviesPattern(acquisition["firstMovie"]),
        "samplingRate": acquisition.get("pixelSize"),
        "voltage": acquisition.get("voltageKv"),
        "magnification": acquisition.get("magnification"),
        "sphericalAberration": csMm,
        "dosePerFrame": acquisition.get("dosePerFrame"),
        "gainFile": gainReference(acquisition, detector),
    }
    return {key: value for key, value in values.items() if value is not None}


def fillImportMovies(workflow: List[Dict[str, Any]], values: Dict[str, Any]) -> int:
    """Make the workflow's Import Movies read the DATA in streaming; answers how many there were."""
    if "magnification" in values:
        values = dict(values, magnification=int(round(float(values["magnification"]))))
    filled = 0
    for protocol in workflow:
        if protocol.get("object.className") not in IMPORT_MOVIES_CLASSES:
            continue
        protocol.update({"importFrom": 0, "samplingRateMode": 0, "dataStreaming": True})
        protocol.update(values)
        filled += 1
    return filled


def fillGainOrientation(workflow: List[Dict[str, Any]], gainFlip: Optional[str],
                        gainRotation: Optional[int]) -> Dict[str, Any]:
    """Turn the gain reference in the workflow's movie alignments as the detector says. Answers how many were
    filled and those that could not take it (Warp's cannot rotate a gain: they are left as the template has them)."""
    flip = str(gainFlip or "none")
    rotation = int(gainRotation or 0)
    filled, notTurned = 0, []
    for protocol in workflow:
        className = protocol.get("object.className")
        if className in MOVIE_ALIGNMENT_CLASSES:
            protocol["gainRot"] = rotation // 90
            protocol["gainFlip"] = GAIN_FLIP_VALUES.get(flip, 0)
            filled += 1
        elif className in WARP_ALIGNMENT_CLASSES:
            if rotation:
                notTurned.append(str(protocol.get("object.label") or className))
                continue
            protocol["gainFlip"] = WARP_GAIN_FLIP_VALUES.get(flip, 0)
            filled += 1
    return {"filled": filled, "notTurned": notTurned}


def fillComposeTiltSeries(workflow: List[Dict[str, Any]], folder: str, pattern: Optional[str]) -> int:
    """Make the workflow's tilt-series composition read the DATA's mdocs; answers how many there were."""
    filled = 0
    for protocol in workflow:
        if protocol.get("object.className") not in COMPOSE_TILT_SERIES_CLASSES:
            continue
        protocol["filesPath"] = folder
        if pattern:
            protocol["mdocPattern"] = pattern
        filled += 1
    return filled


def fillCtfConsensus(workflow: List[Dict[str, Any]], minDefocus: Optional[float], maxDefocus: Optional[float],
                     resolution: Optional[float]) -> int:
    """Write a session's CTF limits into the workflow's CTF consensus; answers how many there were. A limit not
    given keeps the template's; one given turns its criterion on."""
    filled = 0
    for protocol in workflow:
        if protocol.get("object.className") not in CTF_CONSENSUS_CLASSES:
            continue
        if minDefocus is not None or maxDefocus is not None:
            protocol["useDefocus"] = True
            if minDefocus is not None:
                protocol["minDefocus"] = float(minDefocus)
            if maxDefocus is not None:
                protocol["maxDefocus"] = float(maxDefocus)
        if resolution is not None:
            protocol["useResolution"] = True
            protocol["resolution"] = float(resolution)
        filled += 1
    return filled


def labelBranch(workflow: List[Dict[str, Any]], prefix: str) -> None:
    """Name a DATA's branch in a project shared by several: DATA_02 · <the protocol's label>."""
    for protocol in workflow:
        label = str(protocol.get("object.label") or protocol.get("object.className") or "")
        protocol["object.label"] = "%s · %s" % (prefix, label)


def _description(row: Dict[str, Any]) -> str:
    grid = " · ".join(str(part) for part in (row.get("sampleCode"), row.get("boxLabel") and "box %s" % row["boxLabel"],
                                             row.get("gridNumber") is not None and "grid #%s" % row["gridNumber"])
                      if part)
    return "Facility session %s, DATA_%02d%s" % (row["sessionName"], int(row["number"]), (": " + grid) if grid else "")


class FacilitySessionProcessor:
    """Makes and launches the project of a DATA; mapper is a PostgresqlFlatMapper on this thread's connection."""

    def __init__(self, mapper, projectServiceFactory=None):
        from app.backend.mapper.facility_microscope_mapper import FacilityMicroscopePostgresqlMapper
        from app.backend.mapper.facility_session_mapper import FacilitySessionPostgresqlMapper

        self.mapper = mapper
        self.sessions = FacilitySessionPostgresqlMapper(mapper.db)
        self.microscopes = FacilityMicroscopePostgresqlMapper(mapper.db)
        self.projectServiceFactory = projectServiceFactory

    def _projectService(self):
        if self.projectServiceFactory is not None:
            return self.projectServiceFactory()
        from pyworkflow import Config

        from app.backend.api.services.project_service import ProjectService

        # The templates come from the plugins of Scipion's domain, which this thread may be the first to need
        if Config.getDomain() is None:
            Config.setDomain("pwem")

        return ProjectService()

    def _policy(self) -> Dict[str, Any]:
        from app.backend.api.services.facility_settings_service import FacilitySettingsService

        return FacilitySettingsService(self.mapper.db).values()

    def _owner(self, row: Dict[str, Any], ownedByUser: bool = False) -> Dict[str, Any]:
        order = (row.get("userId"), row.get("createdBy")) if ownedByUser else (row.get("createdBy"), row.get("userId"))
        for userId in order:
            record = self.mapper.getUserById(int(userId)) if userId is not None else None
            if record and record.get("isActive", True):
                user = withPermissions(self.mapper, record)
                if not hasPermission(user, "projects.create"):
                    raise RuntimeError("%s may not create projects" % user.get("email"))
                return user
        raise RuntimeError("The session has no user nor creator with an account to own its projects")

    def processPending(self) -> int:
        """Process every DATA waiting for its project; answers how many were tried."""
        rows = self.sessions.listDatasetsToProcess()
        # A session with one project: the DATA after the first of this turn go to the project it made
        made: Dict[int, int] = {}
        for row in rows:
            if row.get("oneProject") and row.get("sessionProjectId") is None and row["sessionId"] in made:
                row = dict(row, sessionProjectId=made[row["sessionId"]])
            processing = self.processDataset(row)
            if row.get("oneProject") and processing.get("projectId"):
                made.setdefault(row["sessionId"], processing["projectId"])
        return len(rows)

    def processDataset(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Make, fill and launch a DATA's project (or its branch in the session's); keeps and answers how it went."""
        # The DATA's folder (named by its microscope's pattern) names its project too
        dataName = row.get("folder") or "%s_DATA_%02d" % (row["sessionName"], int(row["number"]))
        oneProject = bool(row.get("oneProject"))
        projectName = row["sessionName"] if oneProject else dataName
        processing: Dict[str, Any] = {"state": "running", "at": _now(), "templateId": row["templateId"],
                                      "projectName": projectName}
        self.sessions.saveProcessing(row["id"], processing)
        projectId = None
        # A branch in the session's project: the DATA keeps the project only once its branch runs, so it can be tried again
        joined = False
        try:
            acquisition = row["acquisition"] or {}
            microscope = self.microscopes.getMicroscope(int(row["microscopeId"])) or {}
            detectorId = row.get("detectorId") or acquisition.get("detectorId")
            detector = next((item for item in microscope.get("detectors") or []
                             if detectorId is not None and int(item["id"]) == int(detectorId)), None)
            folder = str(Path(row["offloadPath"]) / dataName)
            values = importValues(folder, acquisition, microscope.get("csMm"), detector)
            processing["importValues"] = values
            if "dosePerFrame" not in values:
                processing["note"] = "The movies' metadata gives no dose per frame: the template's is used."

            policy = self._policy()
            owner = self._owner(row, ownedByUser=policy["projectOwner"] == "user")
            service = self._projectService()
            sessionValues = dict(values, ctfMinDefocus=row.get("ctfMinDefocus"), ctfMaxDefocus=row.get("ctfMaxDefocus"),
                                 ctfMaxResolution=row.get("ctfMaxResolution"))
            aliasValues = {alias: sessionValues.get(param) for alias, param in TEMPLATE_ALIASES.items()}
            workflow = service.materializeWorkflowTemplate(row["templateId"], aliasValues)
            workflow = workflow if isinstance(workflow, list) else [workflow]
            if not fillImportMovies(workflow, values):
                raise RuntimeError("The template has no Import Movies to read the DATA")
            if values.get("gainFile") and detector is not None:
                turned = fillGainOrientation(workflow, detector.get("gainFlip"), detector.get("gainRotation"))
                if turned["filled"]:
                    processing["gainOrientation"] = {"flip": detector.get("gainFlip") or "none",
                                                     "rotation": int(detector.get("gainRotation") or 0)}
                if turned["notTurned"]:
                    processing["note"] = ((processing.get("note") or "") + " %s cannot rotate the gain: it keeps the "
                                          "template's orientation." % ", ".join(turned["notTurned"])).strip()
            if fillComposeTiltSeries(workflow, folder, mdocPattern(acquisition.get("metadataPath"))):
                processing["composesTiltSeries"] = True
            limits = (row.get("ctfMinDefocus"), row.get("ctfMaxDefocus"), row.get("ctfMaxResolution"))
            if (row.get("technique") or "spa") == "spa" and any(limit is not None for limit in limits):
                if fillCtfConsensus(workflow, *limits):
                    processing["ctfLimits"] = {"minDefocus": limits[0], "maxDefocus": limits[1], "resolution": limits[2]}
                else:
                    processing["note"] = ((processing.get("note") or "") + " The template has no CTF consensus: the "
                                          "session's CTF limits were not applied.").strip()
            if oneProject:
                labelBranch(workflow, "DATA_%02d" % int(row["number"]))

            from app.backend.api.schemas.project_schema import ProjectCreate
            from app.backend.api.schemas.protocols_schema import WorkflowImportRequest

            if oneProject and row.get("sessionProjectId") is not None:
                # The session's project, made by an earlier DATA: this one is a new branch in it
                projectId = int(row["sessionProjectId"])
                joined = True
            else:
                description = ("Facility session %s" % row["sessionName"]) if oneProject else _description(row)
                project = service.createProject(self.mapper, ProjectCreate(name=projectName, description=description),
                                                owner)
                projectId = int(project["id"])
                self.sessions.saveProcessing(row["id"], processing, projectId=projectId)
                recordAudit(self.mapper, owner, "projects.created", "project", projectId, projectName,
                            {"facilitySession": row["sessionName"], "template": row["templateId"]})
                level = policy["projectShareLevel"]
                if row.get("groupId") is not None:
                    self.mapper.shareProjectWithGroup(projectId, int(row["groupId"]), level)
                for other, permission in ((row.get("userId"), level), (row.get("createdBy"), "manage")):
                    if other is not None and int(other) != int(owner["id"]):
                        self.mapper.shareProjectWithUser(projectId, int(other), permission)
            processing["projectId"] = projectId

            if not service.loadPostgresqlRuntimeProjectForMutation(mapper=self.mapper, projectId=projectId,
                                                                   currentUser=owner):
                raise RuntimeError("The project could not be opened")
            imported = service.importWorkflowProtocolsService(mapper=self.mapper, projectId=projectId,
                                                              currentUser=owner,
                                                              payload=WorkflowImportRequest(workflow=workflow))
            if imported.get("errors"):
                raise RuntimeError("The template's workflow did not load: %s" % imported["errors"])
            roots = [protocol for protocol in workflow if protocol.get("object.className") in IMPORT_MOVIES_CLASSES]
            rootIds = {str(protocol.get("object.id")) for protocol in roots}
            rootId = next((item["newId"] for item in imported.get("created") or [] if str(item["sourceId"]) in rootIds),
                          None)
            if rootId is None:
                raise RuntimeError("The Import Movies of the template was not created in the project")
            launched = service.restartProtocolAll(mapper=self.mapper, projectId=projectId, protocolId=rootId,
                                                  currentUserId=owner["id"])
            if (launched or {}).get("errors"):
                raise RuntimeError("The workflow did not launch: %s" % launched["errors"])
            processing.update(state="launched", at=_now(), rootProtocolId=str(rootId))
        except Exception as error:
            detail = getattr(error, "detail", None) or str(error)
            logger.warning("Could not process %s", projectName, exc_info=True)
            processing.update(state="error", at=_now(), message=str(detail))
        kept = projectId if not joined or processing["state"] == "launched" else None
        self.sessions.saveProcessing(row["id"], processing, projectId=kept)
        if processing["state"] == "launched":
            from app.backend.api.services import notify_events

            notify_events.processingLaunched(self.mapper.db, row, kept)
        return processing
