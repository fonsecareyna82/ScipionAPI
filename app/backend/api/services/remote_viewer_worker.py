"""Runs a desktop viewer of an output on the display Xpra made for it (see remote_display_service.py).

    python -m app.backend.api.services.remote_viewer_worker '<json request>'

The request names the project, the output and the viewer, as the external viewers bar asks for them. The viewer
runs as it does on the desktop (it often starts its program and returns), so this process then waits for every
program it started: Xpra closes the display when this process ends.
"""
import ctypes
import json
import logging
import os
import sys
import time

logger = logging.getLogger("remote_viewer_worker")
_PR_SET_CHILD_SUBREAPER = 36


def _adoptOrphans() -> None:
    """Programs started by the viewer and left behind become this process's children, so it can wait for them."""
    try:
        ctypes.CDLL(None, use_errno=True).prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0)
    except Exception:
        logger.warning("Programs the viewer leaves behind will not keep the window open")


def _waitForPrograms() -> None:
    while True:
        try:
            os.wait()
        except ChildProcessError:
            return
        except InterruptedError:
            continue


def runViewer(request: dict) -> None:
    from app.backend.api.services.project_service import ProjectService
    from app.backend.database import getMapper

    mapper = getMapper()
    service = ProjectService()
    try:
        projectId = int(request["projectId"])
        service._loadPostgresqlRuntimeProject(mapper=mapper, projectId=projectId, projectPath=request["projectPath"])
        protocol, outputObj = service._getProtocolOutputObject(
            protocolId=int(request["protocolId"]), outputName=request["outputName"], mapper=mapper,
            projectId=projectId, protocolIdIsScipionId=True)
        targetObj = service._resolveExternalViewerTargetObject(
            outputObj=outputObj, objectId=request.get("objectId"), objectKind=request.get("objectKind"))
        viewerClass, _descriptor = service._matchExternalViewerClass(
            viewerClasses=service._findExternalViewerClasses(targetObj), viewerId=request["viewerId"])
        service._runExternalViewer(viewerClass=viewerClass, protocol=protocol, targetObj=targetObj)
    finally:
        try:
            if service.currentProject is not None:
                service.currentProject.closeMapper()
        except Exception:
            pass
        try:
            mapper.db.close()
        except Exception:
            pass


def main(argv) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    _adoptOrphans()
    started = time.monotonic()
    try:
        runViewer(json.loads(argv[1]))
    except Exception:
        logger.exception("The viewer could not be opened")
        # Long enough for the page to connect and show nothing rather than a closed window
        time.sleep(max(0.0, 5.0 - (time.monotonic() - started)))
        return 1
    _waitForPrograms()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
