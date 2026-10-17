"""Web session of Xmipp's supervised particle picker for one protocol.

The session lives in the protocol's ``extra`` folder in the desktop picker's
own files (see xmipp_picking_files), so the web and the desktop picker can
continue each other's work. Micrographs come from the protocol's stored
``inputMicrographs``; coordinates are registered as the desktop picker does,
reading the session files with Xmipp's readSetOfCoordinates.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Response, status

from app.backend.api.services import xmipp_picking_files as files
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper
from app.backend.runtime.project_runtime_repository import ProjectRuntimeRepository

logger = logging.getLogger(__name__)

# Protocols whose interactive step is Xmipp's supervised picker.
SUPERVISED_PICKING_PROTOCOLS = frozenset({"XmippProtParticlePicking"})
MICROGRAPHS_INPUT = "inputMicrographs"
OUTPUT_PREFIX = "outputCoordinates"
MAX_PARTICLES_PER_MICROGRAPH = 100000

# One writer at a time per session folder (the web may save while picking).
_folderLocks: Dict[str, threading.Lock] = {}
_folderLocksGuard = threading.Lock()


def _folderLock(folder: str) -> threading.Lock:
    with _folderLocksGuard:
        return _folderLocks.setdefault(folder, threading.Lock())


class PickingSession:
    """Where a picking protocol's session is and which micrographs it picks."""

    def __init__(self, projectId: int, protocolId: int, protocolDbId: int,
                 className: str, projectPath: str, inputRef: Dict[str, Any]):
        self.projectId = projectId
        self.protocolId = protocolId
        self.protocolDbId = protocolDbId
        self.className = className
        self.projectPath = projectPath
        self.inputRef = inputRef
        self.folder = os.path.join(projectPath, "Runs", "%06d_%s" % (protocolId, className), "extra")
        self._micrographs: Optional[List[Dict[str, Any]]] = None

    @property
    def configPath(self) -> str:
        return os.path.join(self.folder, files.CONFIG_FILE)

    def posPath(self, micrograph: Dict[str, Any]) -> str:
        return os.path.join(self.folder, files.posFileName(micrograph["fileName"]))

    def micrographs(self, mapper) -> List[Dict[str, Any]]:
        if self._micrographs is None:
            stored = ScipionSetPostgresqlMapper(mapper.db).getStoredSet(
                self.projectId, int(self.inputRef["parentProtocolDbId"]),
                str(self.inputRef["parentOutputName"]))
            if stored is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                    detail="The input micrographs are not available")
            micrographs = []
            for index, item in enumerate(stored.get("items") or [], start=1):
                values = item.get("values") or {}
                fileName = values.get("_filename")
                if not fileName:
                    continue
                micrographs.append({
                    "id": str(item["scipionItemId"]),
                    "index": index,
                    "fileName": str(fileName),
                    "label": str(values.get("_micName") or os.path.basename(str(fileName))),
                    "locationIndex": values.get("_index") or None,
                    "enabled": item.get("enabled") is not False,
                })
            self._micrographs = micrographs
        return self._micrographs

    def micrograph(self, mapper, micId) -> Dict[str, Any]:
        for micrograph in self.micrographs(mapper):
            if micrograph["id"] == str(micId):
                return micrograph
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Micrograph '%s' is not in this picking session" % micId)


class _SessionImageSource:
    """Adapter for Coords2dService image rendering (getMicrographImageInfo)."""

    def __init__(self, session: PickingSession, mapper):
        self.session = session
        self.mapper = mapper
        self.lastSkipReason = None

    def getMicrographImageInfo(self, micId):
        micrograph = self.session.micrograph(self.mapper, micId)
        return {"id": micrograph["id"], "fileName": micrograph["fileName"],
                "locationIndex": micrograph["locationIndex"], "label": micrograph["label"]}


class XmippPickingSessionService:
    def __init__(self, projectService=None):
        if projectService is None:
            from app.backend.api.services.project_service import ProjectService
            projectService = ProjectService()
        self.projectService = projectService

    # -- session -------------------------------------------------------------

    def openSession(self, mapper, projectId: int, protocolId: int, currentUser) -> PickingSession:
        if not self.projectService.getProjectDbRow(mapper, projectId, currentUser):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        row = mapper.getProjectProtocolByProtocolId(projectId=projectId, protocolId=protocolId)
        if not isinstance(row, dict):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Protocol not found")
        className = str(row.get("protocolClassName") or "")
        if className not in SUPERVISED_PICKING_PROTOCOLS:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="This protocol does not use Xmipp's particle picker")
        inputRef = mapper.db.fetchOne(
            """
            SELECT "parentProtocolDbId", "parentProtocolId", "parentOutputName"
              FROM protocol_input_refs
             WHERE "projectId" = %s AND "protocolDbId" = %s AND "inputName" = %s
             ORDER BY "itemIndex" LIMIT 1
            """,
            (projectId, int(row["id"]), MICROGRAPHS_INPUT),
        )
        if not inputRef or inputRef.get("parentProtocolDbId") is None or not inputRef.get("parentOutputName"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Select the input micrographs and save the protocol first")
        projectPath = ProjectRuntimeRepository().getProjectNameById(mapper, projectId)
        if not projectPath:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project folder not found")
        return PickingSession(projectId, protocolId, int(row["id"]), className,
                              os.path.realpath(projectPath), dict(inputRef))

    def _config(self, session: PickingSession) -> files.PickerConfig:
        return files.readConfig(session.configPath) or files.PickerConfig()

    def describeSession(self, mapper, projectId, protocolId, currentUser) -> Dict[str, Any]:
        session = self.openSession(mapper, projectId, protocolId, currentUser)
        config = self._config(session)
        micrographs = []
        totalPicks = 0
        for micrograph in session.micrographs(mapper):
            picks = files.readPos(session.posPath(micrograph))
            automatic = len(picks.activeAutomatic())
            count = len(picks.manual) + automatic
            totalPicks += count
            micrographs.append({
                "id": micrograph["id"], "index": micrograph["index"],
                "fileName": micrograph["fileName"], "label": micrograph["label"],
                "particles": count, "manualParticles": len(picks.manual),
                "automaticParticles": automatic, "state": picks.state,
                "updated": False, "width": None, "height": None,
                "locationIndex": micrograph["locationIndex"], "thumbnailUrl": None,
            })
        return {
            "protocolClassName": session.className,
            "micrographs": micrographs,
            "totalMicrographs": len(micrographs),
            "totalPicks": totalPicks,
            "boxSize": config.particleSize,
            "mode": config.mode,
            "autopickPercent": config.autopickPercent,
        }

    # -- particles -----------------------------------------------------------

    def listParticles(self, mapper, projectId, protocolId, currentUser, micId) -> Dict[str, Any]:
        session = self.openSession(mapper, projectId, protocolId, currentUser)
        micrograph = session.micrograph(mapper, micId)
        picks = files.readPos(session.posPath(micrograph))
        coordinates = [{"id": "m%d" % index, "micId": micrograph["id"], "x": x, "y": y}
                       for index, (x, y) in enumerate(picks.manual)]
        automatic = [{"id": "a%d" % index, "micId": micrograph["id"], "x": x, "y": y,
                      "score": cost, "enabled": enabled != -1 and cost >= picks.threshold}
                     for index, (x, y, cost, enabled) in enumerate(picks.automatic)]
        return {"coordinates": coordinates, "automatic": automatic, "state": picks.state,
                "threshold": picks.threshold}

    def saveParticles(self, mapper, projectId, protocolId, currentUser, micId,
                      coordinates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Replace a micrograph's manual particles; automatic ones are kept."""
        session = self.openSession(mapper, projectId, protocolId, currentUser)
        micrograph = session.micrograph(mapper, micId)
        if len(coordinates) > MAX_PARTICLES_PER_MICROGRAPH:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="Too many particles for one micrograph")
        manual = []
        for point in coordinates:
            try:
                x, y = int(round(float(point["x"]))), int(round(float(point["y"])))
            except (KeyError, TypeError, ValueError):
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    detail="Invalid particle coordinates")
            manual.append((x, y))
        path = session.posPath(micrograph)
        with _folderLock(session.folder):
            picks = files.readPos(path)
            picks.manual = manual
            if picks.state == "Available" and manual:
                picks.state = "Manual"
            elif not picks.hasData():
                picks.state = "Available"
            files.writePos(path, picks)
            self._updateConfigCounts(session, mapper, micrograph)
        return {"saved": len(manual), "state": picks.state}

    def saveSettings(self, mapper, projectId, protocolId, currentUser,
                     particleSize: Optional[int] = None) -> Dict[str, Any]:
        session = self.openSession(mapper, projectId, protocolId, currentUser)
        with _folderLock(session.folder):
            config = self._config(session)
            if particleSize is not None:
                if not 2 <= int(particleSize) <= 4096:
                    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                        detail="Invalid particle size")
                config.particleSize = int(particleSize)
            if not config.micrograph:
                first = next(iter(session.micrographs(mapper)), None)
                if first is None:
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                        detail="The input micrographs are empty")
                config.micrograph = os.path.splitext(files.posFileName(first["fileName"]))[0]
            files.writeConfig(session.configPath, config)
        return {"boxSize": config.particleSize, "mode": config.mode}

    def _updateConfigCounts(self, session, mapper, micrograph) -> None:
        """Keep config.xmd present and current, as the desktop picker does."""
        config = self._config(session)
        manual = automatic = 0
        for item in session.micrographs(mapper):
            picks = files.readPos(session.posPath(item))
            manual += len(picks.manual)
            automatic += len(picks.activeAutomatic())
        config.manualParticlesNum, config.autoParticlesNum = manual, automatic
        config.micrograph = os.path.splitext(files.posFileName(micrograph["fileName"]))[0]
        files.writeConfig(session.configPath, config)

    # -- images --------------------------------------------------------------

    def renderMicrographImage(self, mapper, projectId, protocolId, currentUser, micId,
                              size: int = 2200, fmt: str = "png",
                              ifNoneMatch: Optional[str] = None) -> Response:
        from app.backend.api.services.coords2d_service import Coords2dService

        session = self.openSession(mapper, projectId, protocolId, currentUser)
        result = Coords2dService()._resolveMicrographImageContent(
            pgReader=_SessionImageSource(session, mapper), mapper=mapper, projectId=projectId,
            micId=str(micId), size=size, fmt=fmt, ifNoneMatch=ifNoneMatch)
        if result["notModified"]:
            return Response(status_code=status.HTTP_304_NOT_MODIFIED,
                            headers={"ETag": result["etag"], "Cache-Control": result["cacheControl"]})
        return Response(content=result["content"], media_type=result["mediaType"],
                        headers=result["headers"])

    # -- coordinates output --------------------------------------------------

    def createCoordinates(self, mapper, projectId, protocolId, currentUser) -> Dict[str, Any]:
        """Register the session particles as a SetOfCoordinates output.

        Same as the desktop picker's coordinates button, which makes the
        protocol call registerCoords on its extra folder.
        """
        from pwem.objects import SetOfCoordinates
        from xmipp3.convert import readSetOfCoordinates

        session = self.openSession(mapper, projectId, protocolId, currentUser)
        if not os.path.isfile(session.configPath):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="There are no picked particles yet")
        project = self.projectService.loadPostgresqlRuntimeProjectForMutation(
            mapper=mapper, projectId=projectId, currentUser=currentUser)
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        protocol = self.projectService._getScipionProtocolByScipionId(protocolId)
        _, micrographs = self.projectService._getProtocolOutputObject(
            protocolId=int(session.inputRef["parentProtocolId"]),
            outputName=str(session.inputRef["parentOutputName"]),
            mapper=mapper, projectId=projectId, protocolIdIsScipionId=True)
        config = self._config(session)

        outputName = OUTPUT_PREFIX
        if getattr(protocol, outputName, None) is not None:
            outputName = protocol.getNextOutputName(OUTPUT_PREFIX + "_")
        seed = SetOfCoordinates()
        seed.setMicrographs(micrographs)
        seed.setBoxSize(config.particleSize)
        context = self.projectService._createWritableGeneratedPostgresqlSet(
            mapper=mapper, projectId=projectId, protocolId=protocolId, protocol=protocol,
            outputName=outputName, sourceSet=seed, protocolIdIsScipionId=True)
        coordinates = context["outputSet"]
        try:
            coordinates.setMicrographs(micrographs)
            coordinates.setBoxSize(config.particleSize)
            readSetOfCoordinates(session.folder, micrographs, coordinates)
            total = coordinates.getSize()
            if not total:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                    detail="There are no picked particles yet")
            protocol._defineOutputs(**{outputName: coordinates})
            protocol._store()
            sync = self.projectService._finalizeGeneratedPostgresqlSet(
                context=context, projectId=projectId, outputName=outputName)
        except Exception:
            self.projectService._discardGeneratedPostgresqlSet(context=context, projectId=projectId)
            raise
        try:
            protocol._defineSourceRelation(micrographs, coordinates)
        except Exception:
            logger.warning("Could not define the picking source relation", exc_info=True)
        return {"success": True, "outputName": outputName, "totalCoordinates": int(total),
                "postgresqlSync": sync,
                "message": "The new set of coordinates has been created: %s" % outputName}
