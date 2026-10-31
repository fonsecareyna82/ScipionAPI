"""Processing a session's DATA, as EMhub does: a project per DATA from the session's template, launched in streaming.

When the watcher has read a DATA's first movie (``facility_session_watcher``) and its session processes by itself
(``autoProcess``) with a template, the DATA gets the project ``<session>_DATA_NN``:

1. the template is made into its workflow (``ProjectService.materializeWorkflowTemplate``), its ``~...|alias~``
   fields filled with what the movie says when their alias is a known one (``TEMPLATE_ALIASES``);
2. its Import Movies (any template, whatever aliases it uses) reads the DATA folder in streaming, with the
   pattern of the movies EPU writes there, the detector's calibrated pixel, the voltage and magnification of the
   movie, the microscope's Cs, the dose per frame and the gain reference;
3. the project belongs to the session's user (else to who made the session), is shared with the session's group
   (work) and with who made it (manage), and runs from its Import Movies like "Restart all" in the web.

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
# The aliases of a template's ~Title|value|type|alias~ fields that take what the first movie says
TEMPLATE_ALIASES = {
    "moviespath": "filesPath", "filespath": "filesPath", "pattern": "filesPattern", "filespattern": "filesPattern",
    "sr": "samplingRate", "samplingrate": "samplingRate", "volt": "voltage", "voltage": "voltage",
    "sa": "sphericalAberration", "cs": "sphericalAberration", "dose": "dosePerFrame", "doseperframe": "dosePerFrame",
    "gain": "gainFile", "gainfile": "gainFile", "mag": "magnification", "magnification": "magnification",
}


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def moviesPattern(firstMovie: str) -> str:
    """The pattern of a DATA's movies from its first one (relative to the folder): EPU's grid squares and the
    movies' own ending, e.g. Images-Disc*/GridSquare_*/Data/*_Fractions.mrc."""
    parts = Path(firstMovie).parts
    folders = ["Images-Disc*" if part.startswith("Images-Disc") else "GridSquare_*" if part.startswith("GridSquare_")
               else part for part in parts[:-1]]
    name = parts[-1]
    for mark in ("_Fractions.", "_EER."):
        if mark in name:
            return "/".join(folders + ["*" + name[name.index(mark):]])
    return "/".join(folders + ["*" + Path(name).suffix])


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

    def _owner(self, row: Dict[str, Any]) -> Dict[str, Any]:
        for userId in (row.get("userId"), row.get("createdBy")):
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
        for row in rows:
            self.processDataset(row)
        return len(rows)

    def processDataset(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Make, fill and launch a DATA's project; keeps and answers how it went."""
        projectName = "%s_DATA_%02d" % (row["sessionName"], int(row["number"]))
        processing: Dict[str, Any] = {"state": "running", "at": _now(), "templateId": row["templateId"],
                                      "projectName": projectName}
        self.sessions.saveProcessing(row["id"], processing)
        projectId = None
        try:
            acquisition = row["acquisition"] or {}
            microscope = self.microscopes.getMicroscope(int(row["microscopeId"])) or {}
            detectorId = row.get("detectorId") or acquisition.get("detectorId")
            detector = next((item for item in microscope.get("detectors") or []
                             if detectorId is not None and int(item["id"]) == int(detectorId)), None)
            folder = str(Path(row["offloadPath"]) / projectName)
            values = importValues(folder, acquisition, microscope.get("csMm"), detector)
            processing["importValues"] = values
            if "dosePerFrame" not in values:
                processing["note"] = "The movies' metadata gives no dose per frame: the template's is used."

            owner = self._owner(row)
            service = self._projectService()
            aliasValues = {alias: values.get(param) for alias, param in TEMPLATE_ALIASES.items()}
            workflow = service.materializeWorkflowTemplate(row["templateId"], aliasValues)
            workflow = workflow if isinstance(workflow, list) else [workflow]
            if not fillImportMovies(workflow, values):
                raise RuntimeError("The template has no Import Movies to read the DATA")

            from app.backend.api.schemas.project_schema import ProjectCreate
            from app.backend.api.schemas.protocols_schema import WorkflowImportRequest

            project = service.createProject(self.mapper, ProjectCreate(name=projectName, description=_description(row)),
                                            owner)
            projectId = int(project["id"])
            self.sessions.saveProcessing(row["id"], processing, projectId=projectId)
            recordAudit(self.mapper, owner, "projects.created", "project", projectId, projectName,
                        {"facilitySession": row["sessionName"], "template": row["templateId"]})
            if row.get("groupId") is not None:
                self.mapper.shareProjectWithGroup(projectId, int(row["groupId"]), "work")
            if row.get("createdBy") is not None and int(row["createdBy"]) != int(owner["id"]):
                self.mapper.shareProjectWithUser(projectId, int(row["createdBy"]), "manage")

            if not service.loadPostgresqlRuntimeProjectForMutation(mapper=self.mapper, projectId=projectId,
                                                                   currentUser=owner):
                raise RuntimeError("The new project could not be opened")
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
        self.sessions.saveProcessing(row["id"], processing, projectId=projectId)
        return processing
