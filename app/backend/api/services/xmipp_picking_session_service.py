"""Web session of Xmipp's supervised particle picker for one protocol.

The session lives in the protocol's ``extra`` folder in the desktop picker's
own files (see xmipp_picking_files), so the web and the desktop picker can
continue each other's work. Micrographs come from the protocol's stored
``inputMicrographs``; coordinates are registered as the desktop picker does,
reading the session files with Xmipp's readSetOfCoordinates.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Response, status

from app.backend.api.services import xmipp_picking_files as files
from app.backend.runtime import web_interactive_picker as interactive
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper
from app.backend.runtime.project_runtime_repository import ProjectRuntimeRepository

logger = logging.getLogger(__name__)

# Protocols whose interactive step is Xmipp's supervised picker.
SUPERVISED_PICKING_PROTOCOLS = frozenset({"XmippProtParticlePicking"})
MICROGRAPHS_INPUT = "inputMicrographs"
OUTPUT_PREFIX = "outputCoordinates"
MAX_PARTICLES_PER_MICROGRAPH = 100000
# Manual particles needed to train, as PickingClassifier.getTrainingParticlesMinimum.
TRAINING_PARTICLES_MINIMUM = 15
TEMPLATES_FILE = "templates.stk"
TEMPLATE_PARTICLES_MAXIMUM = 2000

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
            # Open while the protocol's interactive step waits for the web.
            "webSession": {"open": interactive.readSession(session.folder) is not None},
        }

    def listOpenSessions(self, mapper, projectId: int, currentUser) -> Dict[str, Any]:
        """Picking protocols of the project whose interactive step waits for the web."""
        if not self.projectService.getProjectDbRow(mapper, projectId, currentUser):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        rows = mapper.db.fetchAll(
            """
            SELECT "protocolId", "protocolClassName", params
              FROM protocols
             WHERE "projectId" = %s AND "protocolClassName" = ANY(%s)
               AND status IN ('running', 'launched')
            """,
            (projectId, sorted(SUPERVISED_PICKING_PROTOCOLS)),
        ) or []
        projectPath = ProjectRuntimeRepository().getProjectNameById(mapper, projectId)
        sessions = []
        for row in rows:
            protocolId = int(row["protocolId"])
            folder = os.path.join(os.path.realpath(projectPath or ""), "Runs",
                                  "%06d_%s" % (protocolId, row["protocolClassName"]), "extra")
            webSession = interactive.readSession(folder)
            if webSession is not None:
                params = row.get("params") or {}
                if isinstance(params, str):
                    try:
                        params = json.loads(params)
                    except ValueError:
                        params = {}
                label = params.get("runName") if isinstance(params, dict) else None
                sessions.append({"protocolId": protocolId, "kind": "xmipp-picking",
                                 "sessionId": str(webSession.get("sessionId") or protocolId),
                                 "label": label if isinstance(label, str) else row["protocolClassName"]})
        return {"sessions": sessions}

    def closeWebSession(self, mapper, projectId, protocolId, currentUser) -> Dict[str, Any]:
        """The web closed the picker: the protocol's interactive step finishes."""
        session = self.openSession(mapper, projectId, protocolId, currentUser)
        self._ensureTemplates(session, mapper)
        return {"closed": interactive.requestClose(session.folder)}

    def _ensureTemplates(self, session: PickingSession, mapper) -> None:
        """A trained session without templates.stk gets it (sessions trained before it was written)."""
        if (os.path.exists(os.path.join(session.folder, TEMPLATES_FILE))
                or not os.path.exists(os.path.join(session.folder, "model_svm.txt"))):
            return
        try:
            with _folderLock(session.folder):
                self.writeTemplates(session, mapper, self._config(session))
        except Exception:
            logger.exception("Could not write the picking templates of %s", session.folder)

    # -- particles -----------------------------------------------------------

    def listParticles(self, mapper, projectId, protocolId, currentUser, micId) -> Dict[str, Any]:
        """Manual particles, plus the automatic ones that are not rejected.

        Automatic particles carry their score and an ``a<index>`` id that
        saveParticles uses to tell which ones the user removed.
        """
        session = self.openSession(mapper, projectId, protocolId, currentUser)
        micrograph = session.micrograph(mapper, micId)
        picks = files.readPos(session.posPath(micrograph))
        coordinates = [{"id": "m%d" % index, "micId": micrograph["id"], "x": x, "y": y}
                       for index, (x, y) in enumerate(picks.manual)]
        coordinates.extend(
            {"id": "a%d" % index, "micId": micrograph["id"], "x": x, "y": y,
             "score": cost, "kind": "automatic"}
            for index, (x, y, cost, enabled) in enumerate(picks.automatic) if enabled != -1)
        return {"coordinates": coordinates, "state": picks.state, "threshold": picks.threshold,
                "automaticTotal": len(picks.automatic)}

    def saveParticles(self, mapper, projectId, protocolId, currentUser, micId,
                      coordinates: List[Dict[str, Any]],
                      threshold: Optional[float] = None) -> Dict[str, Any]:
        """Save a micrograph's particles as the desktop picker does.

        Points without an ``a<index>`` id are manual. Automatic particles keep
        their place in the file; the ones no longer sent were removed by the
        user and are written as rejected (enabled -1), like in Java. A moved
        automatic particle becomes a manual one.
        """
        session = self.openSession(mapper, projectId, protocolId, currentUser)
        micrograph = session.micrograph(mapper, micId)
        if len(coordinates) > MAX_PARTICLES_PER_MICROGRAPH:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="Too many particles for one micrograph")
        if threshold is not None and not 0.0 <= float(threshold) <= 1.0:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="The threshold must be between 0 and 1")
        manual = []
        keptAutomatic: Dict[int, tuple] = {}
        for point in coordinates:
            try:
                x, y = int(round(float(point["x"]))), int(round(float(point["y"])))
            except (KeyError, TypeError, ValueError):
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    detail="Invalid particle coordinates")
            pointId = str(point.get("id") or "")
            if pointId.startswith("a") and pointId[1:].isdigit():
                keptAutomatic[int(pointId[1:])] = (x, y)
            else:
                manual.append((x, y))
        path = session.posPath(micrograph)
        with _folderLock(session.folder):
            picks = files.readPos(path)
            automatic = []
            for index, (x, y, cost, enabled) in enumerate(picks.automatic):
                kept = keptAutomatic.get(index)
                if kept is not None and kept != (x, y):
                    manual.append(kept)  # Moved by the user: now a manual particle.
                    automatic.append((x, y, cost, -1))
                elif kept is not None:
                    automatic.append((x, y, cost, 1 if enabled != -1 else -1))
                else:
                    automatic.append((x, y, cost, -1))
            picks.manual = manual
            picks.automatic = automatic
            if threshold is not None:
                picks.threshold = float(threshold)
            if picks.state == "Available" and manual:
                picks.state = "Manual"
            elif not picks.hasData():
                picks.state = "Available"
            files.writePos(path, picks)
            self._updateConfigCounts(session, mapper, micrograph)
        return {"saved": len(manual) + sum(1 for *_, e in automatic if e != -1), "state": picks.state}

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

    def _updateConfigCounts(self, session, mapper, micrograph, config=None) -> None:
        """Keep config.xmd present and current, as the desktop picker does."""
        config = config or self._config(session)
        manual = automatic = 0
        for item in session.micrographs(mapper):
            picks = files.readPos(session.posPath(item))
            manual += len(picks.manual)
            automatic += len(picks.activeAutomatic())
        config.manualParticlesNum, config.autoParticlesNum = manual, automatic
        config.micrograph = os.path.splitext(files.posFileName(micrograph["fileName"]))[0]
        files.writeConfig(session.configPath, config)

    # -- supervised picking --------------------------------------------------

    def _classifier(self, session: PickingSession, mapper, config: files.PickerConfig):
        from app.backend.runtime.xmipp_classifier_session import classifierSession
        micrographs = [self._micrographPath(session, m) for m in session.micrographs(mapper)]
        return classifierSession(session.folder, config.particleSize, micrographs, session.projectPath)

    @staticmethod
    def _micrographPath(session: PickingSession, micrograph: Dict[str, Any]) -> str:
        fileName = micrograph["fileName"]
        return fileName if os.path.isabs(fileName) else os.path.join(session.projectPath, fileName)

    def _trainingRectangle(self, session, micrograph, manual, particleSize):
        """As SupervisedPickerMicrograph.initParticlesRectangle: the picked area."""
        from pwem.emlib.image import ImageHandler
        width, height, _, _ = ImageHandler().getDimensions(self._micrographPath(session, micrograph))
        xs, ys = [x for x, _ in manual], [y for _, y in manual]
        radius = particleSize // 2
        radius = radius + radius // 5
        x, y = max(0, min(xs) - radius), max(0, min(ys) - radius)
        return (x, y, min(max(xs) - x + radius, width - 1), min(max(ys) - y + radius, height - 1))

    def writeTemplates(self, session: PickingSession, mapper, config: files.PickerConfig,
                       allPicks: Optional[Dict[str, files.MicrographPicks]] = None) -> Optional[str]:
        """Write templates.stk, as the desktop picker keeps it.

        Xmipp's automatic picking requires it next to the trained model. Each
        template is the average of the manual particles boxed from their
        micrographs (the Java picker also aligns them while averaging).
        """
        import numpy as np
        from pwem import emlib
        from pwem.emlib.image import ImageHandler

        size = int(config.particleSize)
        half = size // 2
        total = np.zeros((size, size), dtype=np.float64)
        count = 0
        for micrograph in session.micrographs(mapper):
            picks = (allPicks or {}).get(micrograph["id"]) or files.readPos(session.posPath(micrograph))
            if not picks.manual or count >= TEMPLATE_PARTICLES_MAXIMUM:
                continue
            data = ImageHandler().read(self._micrographPath(session, micrograph)).getData()
            height, width = data.shape[-2:]
            for x, y in picks.manual:
                x0, y0 = int(x) - half, int(y) - half
                if x0 < 0 or y0 < 0 or x0 + size > width or y0 + size > height:
                    continue
                box = data[y0:y0 + size, x0:x0 + size].astype(np.float64)
                std = box.std()
                total += (box - box.mean()) / std if std > 0 else box - box.mean()
                count += 1
                if count >= TEMPLATE_PARTICLES_MAXIMUM:
                    break
        if not count:
            return None
        average = (total / count).astype(np.float32)
        path = os.path.join(session.folder, TEMPLATES_FILE)
        image = emlib.Image()
        image.setData(average)
        for index in range(1, max(1, int(config.templatesNum)) + 1):
            image.write("%d@%s" % (index, path))
        return path

    @staticmethod
    def _insideRectangle(rectangle, x, y) -> bool:
        rx, ry, rw, rh = rectangle
        return rx <= x < rx + rw and ry <= y < ry + rh

    def trainAndAutopick(self, mapper, projectId, protocolId, currentUser, micId) -> Dict[str, Any]:
        """Train with every manual particle and autopick this micrograph (Java's Train)."""
        from app.backend.runtime.xmipp_classifier_session import ClassifierError

        session = self.openSession(mapper, projectId, protocolId, currentUser)
        micrograph = session.micrograph(mapper, micId)
        with _folderLock(session.folder):
            config = self._config(session)
            allPicks = {m["id"]: files.readPos(session.posPath(m)) for m in session.micrographs(mapper)}
            total = sum(len(p.manual) for p in allPicks.values())
            if total < TRAINING_PARTICLES_MINIMUM:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=(
                    "Pick at least %d particles by hand to train the picker (now %d)"
                    % (TRAINING_PARTICLES_MINIMUM, total)))
            picks = allPicks[micrograph["id"]]
            if not picks.manual:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                    detail="Pick some particles in this micrograph to train on it")
            picks.state = "Supervised"
            files.writePos(session.posPath(micrograph), picks)
            # All micrographs with manual particles; the training one goes last.
            rows = [(self._micrographPath(session, m), session.posPath(m))
                    for m in session.micrographs(mapper)
                    if allPicks[m["id"]].manual and m["id"] != micrograph["id"]]
            rows.append((self._micrographPath(session, micrograph), session.posPath(micrograph)))
            rectangle = self._trainingRectangle(session, micrograph, picks.manual, config.particleSize)
            try:
                classifier = self._classifier(session, mapper, config)
                classifier.train(rows, rectangle)
                classifier.trainedOn = (micrograph["id"], rectangle)
                found = classifier.autopick(rows[-1][0], config.autopickPercent)
            except ClassifierError as error:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error))
            # Candidates inside the trained area are already picked by hand.
            picks.automatic = [(x, y, -1.0, -1) if self._insideRectangle(rectangle, x, y) else (x, y, cost, 1)
                               for x, y, cost in found]
            picks.autopickPercent = config.autopickPercent
            files.writePos(session.posPath(micrograph), picks)
            config.mode = "Supervised"
            self._updateConfigCounts(session, mapper, micrograph, config)
            # Xmipp's automatic picking needs the templates next to the model.
            self.writeTemplates(session, mapper, config, allPicks)
        return self.listParticles(mapper, projectId, protocolId, currentUser, micId)

    def correctAndAutopick(self, mapper, projectId, protocolId, currentUser, micId,
                           nextMicId: Optional[str]) -> Dict[str, Any]:
        """Learn from this micrograph's corrections and autopick the next one (Java's Next)."""
        from app.backend.runtime.xmipp_classifier_session import ClassifierError

        session = self.openSession(mapper, projectId, protocolId, currentUser)
        current = session.micrograph(mapper, micId)
        nextMicrograph = session.micrograph(mapper, nextMicId) if nextMicId else None
        with _folderLock(session.folder):
            config = self._config(session)
            if config.mode != "Supervised":
                raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                    detail="Train the picker first")
            picks = files.readPos(session.posPath(current))
            try:
                classifier = self._classifier(session, mapper, config)
                currentPath = self._micrographPath(session, current)
                # correct() pairs the corrections with the candidates of the last
                # autopick; only correct when they belong to this micrograph.
                if picks.automatic and classifier.lastAutopicked == currentPath:
                    trained = getattr(classifier, "trainedOn", None)
                    rectangle = trained[1] if trained and trained[0] == current["id"] else None
                    added = [(x, y) for x, y in picks.manual
                             if rectangle is None or not self._insideRectangle(rectangle, x, y)]
                    rows = [(x, y, cost, 1 if enabled != -1 and cost >= picks.threshold else -1)
                            for x, y, cost, enabled in picks.automatic]
                    classifier.correct(added, rows)
                    picks.state = "Corrected"
                    files.writePos(session.posPath(current), picks)
                if nextMicrograph is not None:
                    nextPicks = files.readPos(session.posPath(nextMicrograph))
                    if nextPicks.state == "Available":
                        found = classifier.autopick(self._micrographPath(session, nextMicrograph),
                                                    config.autopickPercent)
                        nextPicks.state = "Supervised"
                        nextPicks.autopickPercent = config.autopickPercent
                        nextPicks.automatic = [(x, y, cost, 1) for x, y, cost in found]
                        files.writePos(session.posPath(nextMicrograph), nextPicks)
            except ClassifierError as error:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error))
            self._updateConfigCounts(session, mapper, nextMicrograph or current, config)
        return {"state": picks.state,
                "next": self.listParticles(mapper, projectId, protocolId, currentUser, nextMicId)
                if nextMicId else None}

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
        if interactive.readSession(session.folder) is not None:
            # The protocol is running its picking step: it registers the
            # coordinates itself, as with the desktop picker's button.
            answer = interactive.requestRegisterCoordinates(session.folder)
            if not answer.get("ok"):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                    detail=answer.get("error") or "The coordinates could not be created")
            outputName = answer.get("outputName") or OUTPUT_PREFIX
            return {"success": True, "outputName": outputName,
                    "totalCoordinates": int(answer.get("totalCoordinates") or 0),
                    "message": "The new set of coordinates has been created: %s" % outputName}
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
