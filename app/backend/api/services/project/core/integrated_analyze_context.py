"""Building the "integrated analyze context" (tiltSeries/ctf/tomogram/
coordinates3d links, summaries, and cross-relations for one output) by
walking a live Scipion runtime protocol graph.

This is the legacy/runtime fallback path, used only when no PostgreSQL
mapper is available - the PostgreSQL-native path is handled entirely by
PostgresqlIntegratedContextReader and doesn't go through here.
"""
from typing import Any, Dict, List, Optional
from typing import Set as TypingSet

from fastapi import HTTPException, status

from app.backend.api.services.project.core.scipion_object_helpers import safeScipionValue


def buildIntegratedAnalyzeContextFromRuntime(
        currentProject,
        projectId: int,
        protocolId: int,
        outputName: str,
) -> Dict[str, Any]:
    if currentProject is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No current project loaded",
        )

    try:
        protocol = currentProject.getProtocol(int(protocolId))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Protocol {protocolId} not found: {e}",
        )

    outputObj = getattr(protocol, outputName, None)
    if outputObj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output '{outputName}' not found in protocol {protocolId}",
        )

    def className(obj: Any) -> str:
        try:
            return obj.getClassName()
        except Exception:
            return obj.__class__.__name__ if obj is not None else ""

    def normalizedClassName(obj: Any) -> str:
        return className(obj).replace(" ", "").lower()

    def safeCall(obj: Any, methodName: str, default: Any = None) -> Any:
        try:
            method = getattr(obj, methodName, None)
            if method is None:
                return default
            return method()
        except Exception:
            return default

    def safeList(value: Any) -> List[Any]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return list(value)
        return [value]

    def firstNonEmpty(*values: Any) -> Optional[Any]:
        for value in values:
            if value is None:
                continue
            text = str(value)
            if text:
                return value
        return None

    def getTsIds(obj: Any) -> TypingSet[str]:
        values = safeCall(obj, "getTSIds", [])
        return {str(v) for v in safeList(values) if v is not None and str(v)}

    def getObjId(obj: Any) -> Optional[Any]:
        return safeCall(obj, "getObjId", None)

    def iterItems(obj: Any) -> List[Any]:
        if obj is None:
            return []

        try:
            return list(obj.iterItems())
        except Exception:
            pass

        try:
            return list(obj)
        except Exception:
            return []

    def getItemTsId(item: Any) -> Optional[Any]:
        return firstNonEmpty(
            safeCall(item, "getTsId", None),
            safeCall(item, "getTSId", None),
            safeCall(item, "getTomoId", None),
            safeCall(item, "getTomogramId", None),
        )

    def getItemLabel(item: Any, fallback: Any = None) -> Optional[Any]:
        return firstNonEmpty(
            safeCall(item, "getTsId", None),
            safeCall(item, "getTSId", None),
            safeCall(item, "getObjLabel", None),
            safeCall(item, "getFileName", None),
            fallback,
        )

    def isTiltSeriesSet(obj: Any) -> bool:
        name = normalizedClassName(obj)
        return "setoftiltseries" in name and "setoftiltseriesm" not in name

    def isTomogramSet(obj: Any) -> bool:
        return "setoftomograms" in normalizedClassName(obj)

    def isCoordinates3dSet(obj: Any) -> bool:
        return "setofcoordinates3d" in normalizedClassName(obj)

    def isCtfTomoSeriesSet(obj: Any) -> bool:
        return "setofctftomoseries" in normalizedClassName(obj)

    def getFirstIteratorItem(value: Any) -> Any:
        if value is None:
            return None

        try:
            iterator = value.iterItems() if hasattr(value, "iterItems") else iter(value)
            return next(iterator, None)
        except Exception:
            return None

    def getCoordinates3dTomograms(coordsSet: Any) -> Any:
        for methodName in ("getTomograms", "getVolumes", "getPrecedents"):
            tomograms = safeCall(coordsSet, methodName, None)
            if tomograms is not None and isTomogramSet(tomograms):
                return tomograms

        for methodName in ("iterTomograms", "iterVolumes"):
            tomogramsIter = safeCall(coordsSet, methodName, None)
            firstTomogram = getFirstIteratorItem(tomogramsIter)
            if firstTomogram is None:
                continue

            parent = safeCall(firstTomogram, "getObjParent", None)
            if parent is None:
                parent = getattr(firstTomogram, "_objParent", None)

            if parent is not None and isTomogramSet(parent):
                return parent

        return None

    def buildLink(
            obj: Any,
            source: Optional[Dict[str, Any]] = None,
            statusValue: str = "available",
            label: Optional[str] = None,
    ) -> Dict[str, Any]:
        source = source or {}
        return {
            "protocolId": source.get("protocolId"),
            "outputName": source.get("outputName"),
            "itemId": getObjId(obj),
            "label": label or source.get("label") or className(obj),
            "status": statusValue,
        }

    def buildSummary(obj: Any, tsIds: Optional[TypingSet[str]] = None) -> Dict[str, Any]:
        summary = {
            "objectClass": className(obj),
            "objectId": getObjId(obj),
            "size": safeCall(obj, "getSize", None),
            "tsIds": sorted(tsIds if tsIds is not None else getTsIds(obj)),
            "samplingRate": safeCall(obj, "getSamplingRate", None),
            "dimensions": safeCall(obj, "getDimensions", safeCall(obj, "getDim", None)),
            "fileName": safeCall(obj, "getFileName", None),
        }

        boxSize = safeCall(obj, "getBoxSize", None)
        if boxSize is not None:
            summary["boxSize"] = boxSize

        ctfCorrected = safeCall(obj, "ctfCorrected", None)
        if ctfCorrected is not None:
            summary["ctfCorrected"] = ctfCorrected

        return safeScipionValue(summary)

    def getProtocolInputRefs(protocolObj: Any) -> List[Dict[str, Any]]:
        refs: List[Dict[str, Any]] = []

        for inputName, pointer in protocolObj.iterInputAttributes():
            try:
                inputObj = pointer.get() if pointer else None
            except Exception:
                inputObj = None

            if inputObj is None:
                continue

            try:
                inputProtocolId = pointer.getObjValue().getObjId()
            except Exception:
                inputProtocolId = None

            try:
                inputOutputName = pointer.getExtended()
            except Exception:
                inputOutputName = None

            refs.append({
                "name": inputName,
                "object": inputObj,
                "protocolId": inputProtocolId,
                "outputName": inputOutputName,
                "label": inputName,
            })

        return refs

    def getProtocolInputRefsById(sourceProtocolId: Any) -> List[Dict[str, Any]]:
        if sourceProtocolId is None:
            return []

        try:
            sourceProtocol = currentProject.getProtocol(int(sourceProtocolId))
        except Exception:
            return []

        return getProtocolInputRefs(sourceProtocol)

    def getProtocolOutputRefs(protocolObj: Any) -> List[Dict[str, Any]]:
        refs: List[Dict[str, Any]] = []

        for outputAttrName, outputObjRef in protocolObj.iterOutputAttributes():
            if outputObjRef is None:
                continue

            refs.append({
                "name": outputAttrName,
                "object": outputObjRef,
                "protocolId": safeCall(protocolObj, "getObjId", None),
                "outputName": outputAttrName,
                "label": outputAttrName,
            })

        return refs

    inputRefs = getProtocolInputRefs(protocol)
    outputRefs = getProtocolOutputRefs(protocol)
    localRefs = inputRefs + outputRefs

    def findInputRef(predicate, tsIds: Optional[TypingSet[str]] = None) -> Optional[Dict[str, Any]]:
        for ref in inputRefs:
            obj = ref["object"]
            if not predicate(obj):
                continue

            if tsIds:
                candidateTsIds = getTsIds(obj)
                if candidateTsIds and not candidateTsIds.intersection(tsIds):
                    continue

            return ref

        return None

    def findInputRefForObject(
            targetObj: Any,
            refs: List[Dict[str, Any]],
            predicate=None,
    ) -> Optional[Dict[str, Any]]:
        if targetObj is None:
            return None

        targetClass = className(targetObj)
        targetObjId = getObjId(targetObj)
        targetFileName = safeCall(targetObj, "getFileName", None)
        targetTsIds = getTsIds(targetObj)

        for ref in refs:
            obj = ref["object"]

            if predicate is not None and not predicate(obj):
                continue

            if obj is targetObj:
                return ref

            objId = getObjId(obj)
            if targetObjId is not None and objId is not None and str(objId) == str(targetObjId):
                return ref

            fileName = safeCall(obj, "getFileName", None)
            if targetFileName and fileName and str(fileName) == str(targetFileName):
                return ref

            objTsIds = getTsIds(obj)
            if targetTsIds and objTsIds and targetTsIds == objTsIds:
                return ref

            if className(obj) != targetClass:
                continue

        return None

    links = {
        "tiltSeries": None,
        "ctf": None,
        "tomogram": None,
        "coordinates3d": None,
    }
    summaries = {
        "tiltSeries": None,
        "ctf": None,
        "tomogram": None,
        "coordinates3d": None,
    }
    relationObjects = {
        "tiltSeries": None,
        "ctf": None,
        "tomogram": None,
        "coordinates3d": None,
    }
    relationsByKey: Dict[str, Dict[str, Any]] = {}

    def upsertRelation(keyValue: Any, **values: Any) -> None:
        key = str(keyValue) if keyValue is not None else ""
        if not key:
            return

        relation = relationsByKey.setdefault(key, {
            "key": key,
            "label": key,
        })

        for name, value in values.items():
            if value is not None:
                relation[name] = value

    def addSetRelations(kind: str, obj: Any) -> None:
        items = iterItems(obj)

        if not items:
            for tsId in sorted(getTsIds(obj)):
                if kind == "tiltSeries":
                    upsertRelation(tsId, tiltSeriesId=tsId, label=tsId)
                elif kind == "ctf":
                    upsertRelation(tsId, ctfSeriesId=tsId, tiltSeriesId=tsId, label=tsId)
                elif kind == "tomogram":
                    upsertRelation(tsId, tomogramId=tsId, label=tsId)
                elif kind == "coordinates3d":
                    upsertRelation(tsId, coordinatesTomogramId=tsId, label=tsId)
            return

        for index, item in enumerate(items):
            tsId = getItemTsId(item)
            objId = getObjId(item)
            key = firstNonEmpty(tsId, objId, index)
            label = getItemLabel(item, key)

            if kind == "tiltSeries":
                upsertRelation(
                    key,
                    tiltSeriesId=firstNonEmpty(tsId, objId, index),
                    label=label,
                )
            elif kind == "ctf":
                upsertRelation(
                    key,
                    ctfSeriesId=firstNonEmpty(tsId, objId, index),
                    tiltSeriesId=tsId,
                    label=label,
                )
            elif kind == "tomogram":
                upsertRelation(
                    key,
                    tomogramId=firstNonEmpty(tsId, objId, index),
                    tomogramVolumeId=index,
                    label=label,
                )
            elif kind == "coordinates3d":
                upsertRelation(
                    key,
                    coordinatesTomogramId=firstNonEmpty(tsId, objId, index),
                    label=label,
                )

    rootSource = {
        "protocolId": protocolId,
        "outputName": outputName,
        "label": outputName,
    }

    outputTsIds = getTsIds(outputObj)

    if isCoordinates3dSet(outputObj):
        links["coordinates3d"] = buildLink(outputObj, rootSource)
        summaries["coordinates3d"] = buildSummary(outputObj, outputTsIds)
        relationObjects["coordinates3d"] = outputObj

        tomograms = getCoordinates3dTomograms(outputObj)
        if tomograms is not None:
            tomoTsIds = outputTsIds or getTsIds(tomograms)
            tomogramRef = findInputRefForObject(tomograms, localRefs, isTomogramSet)
            links["tomogram"] = buildLink(tomograms, tomogramRef, statusValue="inferred")
            summaries["tomogram"] = buildSummary(tomograms, tomoTsIds)
            relationObjects["tomogram"] = tomograms
            outputTsIds = tomoTsIds

    elif isTomogramSet(outputObj):
        links["tomogram"] = buildLink(outputObj, rootSource)
        summaries["tomogram"] = buildSummary(outputObj, outputTsIds)
        relationObjects["tomogram"] = outputObj

    elif isCtfTomoSeriesSet(outputObj):
        links["ctf"] = buildLink(outputObj, rootSource)
        summaries["ctf"] = buildSummary(outputObj, outputTsIds)
        relationObjects["ctf"] = outputObj

        tiltSeries = safeCall(outputObj, "getSetOfTiltSeries", None)
        if tiltSeries is not None and isTiltSeriesSet(tiltSeries):
            tiltRef = findInputRefForObject(tiltSeries, localRefs, isTiltSeriesSet)
            links["tiltSeries"] = buildLink(tiltSeries, tiltRef, statusValue="inferred")
            summaries["tiltSeries"] = buildSummary(tiltSeries, outputTsIds)
            relationObjects["tiltSeries"] = tiltSeries

    elif isTiltSeriesSet(outputObj):
        links["tiltSeries"] = buildLink(outputObj, rootSource)
        summaries["tiltSeries"] = buildSummary(outputObj, outputTsIds)
        relationObjects["tiltSeries"] = outputObj

    if outputTsIds and links["ctf"] is None:
        ctfRef = findInputRef(isCtfTomoSeriesSet, outputTsIds)
        if ctfRef is not None:
            ctfSet = ctfRef["object"]
            links["ctf"] = buildLink(ctfSet, ctfRef)
            summaries["ctf"] = buildSummary(ctfSet, outputTsIds)
            relationObjects["ctf"] = ctfSet

            tiltSeries = safeCall(ctfSet, "getSetOfTiltSeries", None)
            if tiltSeries is not None and links["tiltSeries"] is None and isTiltSeriesSet(tiltSeries):
                ctfInputRefs = getProtocolInputRefsById(ctfRef.get("protocolId"))
                tiltRef = (
                        findInputRefForObject(tiltSeries, ctfInputRefs, isTiltSeriesSet)
                        or findInputRefForObject(tiltSeries, inputRefs, isTiltSeriesSet)
                )
                links["tiltSeries"] = buildLink(tiltSeries, tiltRef, statusValue="inferred")
                summaries["tiltSeries"] = buildSummary(tiltSeries, outputTsIds)
                relationObjects["tiltSeries"] = tiltSeries

    if outputTsIds and links["tiltSeries"] is None:
        tiltRef = findInputRef(isTiltSeriesSet, outputTsIds)
        if tiltRef is not None:
            tiltSeries = tiltRef["object"]
            links["tiltSeries"] = buildLink(tiltSeries, tiltRef)
            summaries["tiltSeries"] = buildSummary(tiltSeries, outputTsIds)
            relationObjects["tiltSeries"] = tiltSeries

    addSetRelations("tiltSeries", relationObjects["tiltSeries"])
    addSetRelations("ctf", relationObjects["ctf"])
    addSetRelations("tomogram", relationObjects["tomogram"])

    if relationObjects["tomogram"] is not None:
        addSetRelations("coordinates3d", relationObjects["tomogram"])
    else:
        addSetRelations("coordinates3d", relationObjects["coordinates3d"])

    relations = safeScipionValue({
        "items": list(relationsByKey.values()),
    })

    return {
        "root": {
            "projectId": projectId,
            "protocolId": protocolId,
            "outputName": outputName,
            "outputClass": className(outputObj),
        },
        "links": links,
        "summaries": summaries,
        "relations": relations,
    }
