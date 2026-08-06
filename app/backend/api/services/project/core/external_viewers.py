"""Discovering, matching, and launching external (Tkinter-domain) Scipion
viewers for a protocol output, and resolving which item inside a Set-like
output a request is targeting.

currentProject and tomoList (ProjectService's cache of resolved tomograms,
keyed by public object id) are always passed in explicitly rather than
read from an instance - callers snapshot them at the point they call in.
For the launch flow this snapshot happens when the background viewer
thread is created (see ProjectService.launchExternalViewer), not lazily
while the thread runs; that's equivalent in practice because each
ProjectService instance is used by exactly one in-flight request/thread
pair (a fresh instance is created per HTTP request).
"""
import logging
import re
import threading
from typing import Any, Dict, List, Optional, Set as TypingSet, Tuple, Union

from fastapi import HTTPException, status
from pyworkflow.config import Config

try:
    from pyworkflow.viewer import DESKTOP_TKINTER
except Exception:
    DESKTOP_TKINTER = None

from app.backend.api.services.project.core import protocol_resolution as _protocolResolution

logger = logging.getLogger(__name__)


def getExternalViewerObjectIds(obj: Any) -> TypingSet[str]:
    values: TypingSet[str] = set()

    def addValue(value: Any):
        if value is None:
            return

        getter = getattr(value, "get", None)
        if callable(getter):
            try:
                value = getter()
            except Exception:
                pass

        if value is None:
            return

        text = str(value).strip()
        if text:
            values.add(text)

    for methodName in (
        "getTsId",
        "getObjId",
        "getId",
        "getName",
        "getFileName",
    ):
        method = getattr(obj, methodName, None)
        if callable(method):
            try:
                addValue(method())
            except Exception:
                pass

    for attrName in (
        "tsId",
        "id",
        "objId",
        "_objId",
        "name",
        "label",
        "filename",
        "fileName",
    ):
        if hasattr(obj, attrName):
            try:
                addValue(getattr(obj, attrName))
            except Exception:
                pass

    return values


def isSingleExternalViewerObject(outputObj: Any) -> bool:
    if outputObj is None:
        return False

    getItem = getattr(outputObj, "getItem", None)
    if callable(getItem):
        return False

    iterItems = getattr(outputObj, "__iter__", None)
    if callable(iterItems):
        return False

    getFileName = getattr(outputObj, "getFileName", None)
    if callable(getFileName):
        return True

    return False


def findExternalViewerClasses(targetObj: Any) -> List[Any]:
    try:
        viewers = Config.getDomain().findViewers(targetObj, DESKTOP_TKINTER) or []
        return list(viewers)
    except BaseException as e:
        logger.exception(
            "Failed to find external viewers for object type %s: %s",
            type(targetObj).__name__,
            e,
        )
        return []


def normalizeExternalViewerId(viewerClass: Any) -> str:
    className = getattr(viewerClass, "__name__", "") or str(viewerClass)
    viewerId = className.strip()

    if viewerId.lower().endswith("viewer"):
        viewerId = viewerId[:-6]

    viewerId = re.sub(r"[^A-Za-z0-9]+", "-", viewerId).strip("-").lower()
    return viewerId or "viewer"


def buildExternalViewerDescriptor(viewerClass: Any) -> Dict[str, Any]:
    className = getattr(viewerClass, "__name__", "") or str(viewerClass)
    moduleName = getattr(viewerClass, "__module__", None)

    label = (
        getattr(viewerClass, "_label", None)
        or getattr(viewerClass, "label", None)
        or className
    )

    label = str(label).replace("Viewer", "").strip() or className

    return {
        "id": normalizeExternalViewerId(viewerClass),
        "label": label,
        "className": className,
        "moduleName": moduleName,
        "available": True,
        "reason": None,
    }


def unwrapScipionObject(obj: Any) -> Any:
    if obj is None:
        return None

    getter = getattr(obj, "get", None)
    if callable(getter):
        try:
            value = getter()
            if value is not None:
                return value
        except Exception:
            pass

    return obj


def getProtocolOutputObject(
        currentProject,
        protocolId: int,
        outputName: str,
        mapper=None,
        projectId: Optional[int] = None,
) -> Tuple[Any, Any]:
    protocol = _protocolResolution.getScipionProtocolForRuntime(
        currentProject,
        mapper=mapper,
        projectId=projectId,
        protocolId=protocolId,
    )

    outputObj = None

    if hasattr(protocol, outputName):
        outputObj = getattr(protocol, outputName)

    if outputObj is None:
        iterator = getattr(protocol, "iterOutputAttributes", None)
        if callable(iterator):
            try:
                for attrName, attrObj in iterator():
                    if str(attrName) == str(outputName):
                        outputObj = attrObj
                        break
            except Exception:
                pass

    outputObj = unwrapScipionObject(outputObj)

    if outputObj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output not found: {outputName}",
        )

    return protocol, outputObj


def resolveCoords3dTomogram(
        outputObj: Any,
        objectId: Union[str, int],
        tomoList: Optional[Dict[str, Any]],
) -> Tuple[Any, Dict[str, Any]]:
    if tomoList is None:
        tomoList = {}

    targetId = str(objectId).strip()
    if not targetId:
        return None, tomoList

    cached = tomoList.get(targetId)
    if cached is not None:
        return cached, tomoList

    getTomogram = getattr(outputObj, "_getTomogram", None)
    if callable(getTomogram):
        try:
            tomo = getTomogram(targetId)
            if tomo is not None:
                return tomo, tomoList
        except Exception:
            pass

    iterTomograms = getattr(outputObj, "iterTomograms", None)
    if callable(iterTomograms):
        try:
            for tomo in iterTomograms():
                tomoIds = getExternalViewerObjectIds(tomo)

                getTsId = getattr(tomo, "getTsId", None)
                if callable(getTsId):
                    try:
                        tomoIds.add(str(getTsId()))
                    except Exception:
                        pass

                getObjLabel = getattr(tomo, "getObjLabel", None)
                if callable(getObjLabel):
                    try:
                        tomoIds.add(str(getObjLabel()))
                    except Exception:
                        pass

                if targetId in tomoIds:
                    tomoList[targetId] = tomo
                    return tomo, tomoList
        except Exception:
            pass

    return None, tomoList


def resolveCTFTomoSeries(outputObj: Any, objectId: Union[str, int]) -> Any:
    targetId = str(objectId).strip()
    if not targetId:
        return None

    try:
        for item in outputObj:
            itemIds = getExternalViewerObjectIds(item)

            for methodName in (
                    "getTsId",
                    "getTomoId",
                    "getCTFTomoSeriesId",
                    "getObjId",
                    "getObjLabel",
                    "getName",
            ):
                method = getattr(item, methodName, None)
                if callable(method):
                    try:
                        value = method()
                        if value is not None:
                            itemIds.add(str(value))
                    except Exception:
                        pass

            if targetId in itemIds:
                return item
    except Exception:
        pass

    return None


def resolveSetItemByPublicId(outputObj: Any, objectId: Union[str, int]) -> Any:
    try:
        publicId = int(objectId)
    except Exception:
        return None

    getItem = getattr(outputObj, "getItem", None)
    if callable(getItem):
        for key, value in (
                ("_objId", publicId + 1),
                ("_objId", publicId),
                ("id", publicId),
                ("index", publicId),
        ):
            try:
                item = getItem(key, value)
                if item is not None:
                    return item
            except Exception:
                pass

    try:
        for index, item in enumerate(outputObj):
            if index == publicId:
                return item

            itemIds = getExternalViewerObjectIds(item)
            if str(publicId) in itemIds or str(publicId + 1) in itemIds:
                return item
    except Exception:
        pass

    return None


def resolveExternalViewerTargetObject(
        outputObj: Any,
        tomoList: Optional[Dict[str, Any]],
        objectId: Optional[Union[str, int]] = None,
        objectKind: Optional[str] = None,
) -> Tuple[Any, Dict[str, Any]]:
    if tomoList is None:
        tomoList = {}

    if objectId is None or str(objectId).strip() == "":
        return outputObj, tomoList

    targetId = str(objectId).strip()
    objectKindText = str(objectKind or "").strip().lower()

    if objectKindText in {"volume", "tomogram"} and isSingleExternalViewerObject(outputObj):
        if targetId in {"0", "1"}:
            return outputObj, tomoList

    if objectKindText in {"coords3dtomogram", "coords3d-tomogram", "coordinates3dtomogram"}:
        resolved, tomoList = resolveCoords3dTomogram(
            outputObj=outputObj,
            objectId=objectId,
            tomoList=tomoList,
        )
        if resolved is not None:
            return resolved, tomoList

    if objectKindText in {"ctftomoseries", "ctf-tomo-series", "ctfseries"}:
        resolved = resolveCTFTomoSeries(outputObj=outputObj, objectId=objectId)
        if resolved is not None:
            return resolved, tomoList

    if objectKindText in {"volume", "tomogram"}:
        resolved = resolveSetItemByPublicId(outputObj=outputObj, objectId=objectId)
        if resolved is not None:
            return resolved, tomoList

    try:
        for item in outputObj:
            itemIds = getExternalViewerObjectIds(item)
            if targetId in itemIds:
                return item, tomoList
    except Exception:
        pass

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=(
            f"Object '{targetId}' not found inside output. "
            f"objectKind={objectKind or 'unknown'}"
        ),
    )


def matchExternalViewerClass(
        viewerClasses: List[Any],
        viewerId: str,
) -> Tuple[Any, Dict[str, Any]]:
    requested = str(viewerId or "").strip().lower()

    for viewerClass in viewerClasses:
        descriptor = buildExternalViewerDescriptor(viewerClass)

        tokens = {
            str(descriptor.get("id") or "").lower(),
            str(descriptor.get("label") or "").lower(),
            str(descriptor.get("className") or "").lower(),
            str(descriptor.get("moduleName") or "").lower(),
        }

        className = str(descriptor.get("className") or "")
        if className.lower().endswith("viewer"):
            tokens.add(className[:-6].lower())

        if requested in tokens:
            return viewerClass, descriptor

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"External viewer not found or not compatible: {viewerId}",
    )


def listExternalViewersData(
        currentProject,
        tomoList: Optional[Dict[str, Any]],
        protocolId: int,
        outputName: str,
        objectId: Optional[Union[str, int]] = None,
        objectKind: Optional[str] = None,
        mapper=None,
        projectId: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    protocol, outputObj = getProtocolOutputObject(
        currentProject=currentProject,
        protocolId=protocolId,
        outputName=outputName,
        mapper=mapper,
        projectId=projectId,
    )

    targetObj, tomoList = resolveExternalViewerTargetObject(
        outputObj=outputObj,
        tomoList=tomoList,
        objectId=objectId,
        objectKind=objectKind,
    )

    viewerClasses = findExternalViewerClasses(targetObj)

    descriptors = []
    seenIds: TypingSet[str] = set()
    excludedViewer = ['TomoDataViewer', 'MDViewer', 'DataViewer', 'CtfEstimationTomoViewer']
    for viewerClass in viewerClasses:
        descriptor = buildExternalViewerDescriptor(viewerClass)
        viewerId = descriptor["id"]
        if descriptor['className'] in excludedViewer:
            continue

        if viewerId in seenIds:
            className = descriptor.get("className") or viewerId
            viewerId = f"{viewerId}-{len(seenIds) + 1}"
            descriptor["id"] = viewerId
            descriptor["className"] = className

        seenIds.add(viewerId)
        descriptors.append(descriptor)

    return descriptors, tomoList


def createExternalViewerInstance(viewerClass: Any, protocol: Any, currentProject: Any) -> Any:
    attempts = [
        {"project": currentProject, "protocol": protocol},
        {"protocol": protocol},
        {"project": currentProject},
        {},
    ]

    lastError = None

    for kwargs in attempts:
        try:
            viewer = viewerClass(**kwargs)
            return viewer
        except TypeError as e:
            lastError = e
        except Exception as e:
            lastError = e
            break

    raise RuntimeError(f"Could not create viewer instance: {lastError}")


def showExternalView(view: Any):
    if view is None:
        return

    for methodName in ("show", "execute", "launch", "run"):
        method = getattr(view, methodName, None)
        if callable(method):
            method()
            return

    if callable(view):
        view()


def runExternalViewer(viewerClass: Any, protocol: Any, targetObj: Any, currentProject: Any):
    viewer = createExternalViewerInstance(viewerClass, protocol, currentProject)

    for methodName in ("setProject",):
        method = getattr(viewer, methodName, None)
        if callable(method):
            try:
                method(currentProject)
            except Exception:
                pass

    for methodName in ("setProtocol",):
        method = getattr(viewer, methodName, None)
        if callable(method):
            try:
                method(protocol)
            except Exception:
                pass

    visualize = getattr(viewer, "visualize", None)
    if not callable(visualize):
        visualize = getattr(viewer, "_visualize", None)

    if not callable(visualize):
        raise RuntimeError("Viewer does not expose a visualize method")

    views = visualize(targetObj)

    if views is None:
        return

    if not isinstance(views, (list, tuple)):
        views = [views]

    for view in views:
        showExternalView(view)


def safeRunExternalViewer(
        viewerClass: Any,
        protocol: Any,
        targetObj: Any,
        descriptor: Dict[str, Any],
        currentProject: Any,
):
    try:
        runExternalViewer(
            viewerClass=viewerClass,
            protocol=protocol,
            targetObj=targetObj,
            currentProject=currentProject,
        )
    except Exception as e:
        logger.exception(
            "External viewer failed. viewerId=%s className=%s error=%s",
            descriptor.get("id"),
            descriptor.get("className"),
            e,
        )


def launchExternalViewerData(
        currentProject,
        tomoList: Optional[Dict[str, Any]],
        protocolId: int,
        outputName: str,
        viewerId: str,
        objectId: Optional[Union[str, int]] = None,
        objectKind: Optional[str] = None,
        mapper=None,
        projectId: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    protocol, outputObj = getProtocolOutputObject(
        currentProject=currentProject,
        protocolId=protocolId,
        outputName=outputName,
        mapper=mapper,
        projectId=projectId,
    )

    targetObj, tomoList = resolveExternalViewerTargetObject(
        outputObj=outputObj,
        tomoList=tomoList,
        objectId=objectId,
        objectKind=objectKind,
    )

    viewerClasses = findExternalViewerClasses(targetObj)

    viewerClass, descriptor = matchExternalViewerClass(
        viewerClasses=viewerClasses,
        viewerId=viewerId,
    )

    thread = threading.Thread(
        target=safeRunExternalViewer,
        args=(viewerClass, protocol, targetObj, descriptor, currentProject),
        daemon=True,
    )
    thread.start()

    result = {
        "success": True,
        "viewerId": descriptor["id"],
        "message": f"{descriptor['label']} launch requested.",
        "pid": None,
        "data": {
            "objectId": objectId,
            "objectKind": objectKind,
        },
    }

    return result, tomoList
