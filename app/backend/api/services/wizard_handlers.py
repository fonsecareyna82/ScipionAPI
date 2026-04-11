from __future__ import annotations

import base64
import importlib
import io
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

_MASK_RADIUS_HELP_MESSAGE = (
    "The values of the mask radius can be controlled via both the slider or the "
    "mousewheel (when the mouse cursor is over the image)."
)


def executeMaskRadiusWizard(
    *,
    wizardClass,
    protocol,
    paramName: str,
    descriptor: Optional[Dict[str, Any]] = None,
    wizardInputs: Optional[Dict[str, Any]] = None,
    currentProject=None,
    projectId: Optional[int] = None,
) -> Dict[str, Any]:
    currentValue = max(1, _readProtocolNumericValue(protocol, paramName, default=1))
    wizardInputs = wizardInputs or {}

    action = _normalizeMaskRadiusAction(wizardInputs)
    radius = _coercePositiveInt(wizardInputs.get("radius"), default=currentValue)
    selectedIndex = _coercePositiveInt(wizardInputs.get("selectedIndex"), default=1)

    if action == "apply":
        return {
            "paramUpdates": {
                paramName: radius,
            },
            "message": f"Mask radius set to {radius}",
            "availableValues": [],
        }

    viewerState = _buildMaskRadiusViewerState(
        protocol=protocol,
        currentProject=currentProject,
        radius=radius,
        selectedIndex=selectedIndex,
        canvasSize=512,
    )

    return {
        "paramUpdates": {},
        "message": _MASK_RADIUS_HELP_MESSAGE,
        "requiresUserInput": True,
        "availableValues": [],
        "inputSchema": {
            "type": "mask_radius",
            "paramName": paramName,
            "title": "Wizard",
        },
        "viewerState": viewerState,
    }


def executeWizardHandler(
    *,
    kind: str,
    wizardClass,
    protocol,
    paramName: str,
    descriptor: Optional[Dict[str, Any]] = None,
    wizardInputs: Optional[Dict[str, Any]] = None,
    currentProject=None,
    projectId: Optional[int] = None,
) -> Dict[str, Any]:
    handler = _HANDLERS.get(kind, executeGenericComputeWizard)
    return handler(
        wizardClass=wizardClass,
        protocol=protocol,
        paramName=paramName,
        descriptor=descriptor or {},
        wizardInputs=wizardInputs or {},
        currentProject=currentProject,
        projectId=projectId,
    )


def executeGenericComputeWizard(
    *,
    wizardClass,
    protocol,
    paramName: str,
    descriptor: Optional[Dict[str, Any]] = None,
    wizardInputs: Optional[Dict[str, Any]] = None,
    currentProject=None,
    projectId: Optional[int] = None,
) -> Dict[str, Any]:
    return _executeByCandidates(
        wizardClass=wizardClass,
        protocol=protocol,
        paramName=paramName,
        preferredMethodNames=_buildGenericMethodNames(paramName),
    )


def executeBoxSizeWizard(
    *,
    wizardClass,
    protocol,
    paramName: str,
    descriptor: Optional[Dict[str, Any]] = None,
    wizardInputs: Optional[Dict[str, Any]] = None,
    currentProject=None,
    projectId: Optional[int] = None,
) -> Dict[str, Any]:
    preferred = [
        "_getBoxSize",
        "getBoxSize",
        "estimateBoxSize",
        "calculateBoxSize",
    ]
    preferred.extend(_buildGenericMethodNames(paramName))
    return _executeByCandidates(
        wizardClass=wizardClass,
        protocol=protocol,
        paramName=paramName,
        preferredMethodNames=preferred,
    )


def executeConsensusRadiusWizard(
    *,
    wizardClass,
    protocol,
    paramName: str,
    descriptor: Optional[Dict[str, Any]] = None,
    wizardInputs: Optional[Dict[str, Any]] = None,
    currentProject=None,
    projectId: Optional[int] = None,
) -> Dict[str, Any]:
    preferred = [
        "_getConsensusRadius",
        "getConsensusRadius",
        "_getRadius",
        "getRadius",
        "estimateRadius",
        "calculateRadius",
    ]
    preferred.extend(_buildGenericMethodNames(paramName))
    return _executeByCandidates(
        wizardClass=wizardClass,
        protocol=protocol,
        paramName=paramName,
        preferredMethodNames=preferred,
    )


def executeNumberOfClassesWizard(
    *,
    wizardClass,
    protocol,
    paramName: str,
    descriptor: Optional[Dict[str, Any]] = None,
    wizardInputs: Optional[Dict[str, Any]] = None,
    currentProject=None,
    projectId: Optional[int] = None,
) -> Dict[str, Any]:
    preferred = [
        "_getNumberOfClasses",
        "getNumberOfClasses",
        "estimateNumberOfClasses",
        "calculateNumberOfClasses",
        "suggestNumberOfClasses",
    ]
    preferred.extend(_buildGenericMethodNames(paramName))
    return _executeByCandidates(
        wizardClass=wizardClass,
        protocol=protocol,
        paramName=paramName,
        preferredMethodNames=preferred,
    )


def executeComputeLaneSelectorWizard(
    *,
    wizardClass,
    protocol,
    paramName: str,
    descriptor: Optional[Dict[str, Any]] = None,
    wizardInputs: Optional[Dict[str, Any]] = None,
    currentProject=None,
    projectId: Optional[int] = None,
) -> Dict[str, Any]:
    lanes = _loadSchedulerLanesFromWizardModule(wizardClass)
    if not lanes:
        raise RuntimeError(
            f"No scheduler lanes available for wizard '{wizardClass.__name__}'"
        )

    currentValue = _readProtocolParamValue(protocol, paramName)
    selectedLane = currentValue if currentValue in lanes else lanes[0]

    return {
        "paramUpdates": {paramName: str(selectedLane)},
        "message": f"Selected compute lane '{selectedLane}'",
        "availableValues": lanes,
    }


_HANDLERS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "compute": executeGenericComputeWizard,
    "box_size": executeBoxSizeWizard,
    "consensus_radius": executeConsensusRadiusWizard,
    "number_of_classes": executeNumberOfClassesWizard,
    "compute_lane_selector": executeComputeLaneSelectorWizard,
    "mask_radius": executeMaskRadiusWizard,
}


def _executeByCandidates(
    *,
    wizardClass,
    protocol,
    paramName: str,
    preferredMethodNames: Sequence[str],
) -> Dict[str, Any]:
    instance = _instantiateWizard(wizardClass)
    target = instance if instance is not None else wizardClass

    attempted: List[str] = []

    for methodName in _uniqueStrings(preferredMethodNames):
        method = getattr(target, methodName, None)
        if not callable(method):
            continue

        for args in _buildArgumentCandidates(protocol, paramName):
            attempted.append(f"{wizardClass.__name__}.{methodName}{args}")
            try:
                result = method(*args)
                return _normalizeHandlerResult(paramName, result)
            except TypeError:
                continue
            except Exception as e:
                logger.warning(
                    "Wizard callable failed: %s.%s -> %s",
                    wizardClass.__name__,
                    methodName,
                    e,
                )
                continue

    raise RuntimeError(
        "No supported callable succeeded for wizard "
        f"'{wizardClass.__name__}'. Attempted: {attempted}"
    )


def _instantiateWizard(wizardClass):
    try:
        return wizardClass()
    except Exception:
        return None


def _buildArgumentCandidates(protocol, paramName: str):
    return [
        (protocol, paramName),
        (protocol,),
        (),
    ]


def _buildGenericMethodNames(paramName: str) -> List[str]:
    suffix = _toPascalCase(paramName)

    names = [
        f"_get{suffix}",
        f"get{suffix}",
        f"estimate{suffix}",
        f"calculate{suffix}",
        f"compute{suffix}",
        f"suggest{suffix}",
        "getResult",
        "estimate",
        "calculate",
        "compute",
    ]

    return _uniqueStrings(names)


def _toPascalCase(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return raw[0].upper() + raw[1:]


def _uniqueStrings(items: Sequence[str]) -> List[str]:
    seen = set()
    result: List[str] = []

    for item in items:
        token = str(item or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        result.append(token)

    return result


def _normalizeHandlerResult(paramName: str, rawResult: Any) -> Dict[str, Any]:
    if rawResult is None:
        raise RuntimeError("Wizard returned no result")

    if isinstance(rawResult, dict):
        if isinstance(rawResult.get("paramUpdates"), dict):
            return rawResult

        if paramName in rawResult:
            return {"paramUpdates": {paramName: rawResult[paramName]}}

        if len(rawResult) == 1:
            onlyKey = next(iter(rawResult.keys()))
            return {"paramUpdates": {str(onlyKey): rawResult[onlyKey]}}

        return {"paramUpdates": rawResult}

    if isinstance(rawResult, (list, tuple)):
        if len(rawResult) == 1:
            return {"paramUpdates": {paramName: rawResult[0]}}

        if len(rawResult) == 2 and isinstance(rawResult[0], str):
            return {"paramUpdates": {rawResult[0]: rawResult[1]}}

    return {"paramUpdates": {paramName: rawResult}}


def _loadSchedulerLanesFromWizardModule(wizardClass) -> List[str]:
    moduleName = getattr(wizardClass, "__module__", "")
    if not moduleName:
        return []

    try:
        module = importlib.import_module(moduleName)
    except Exception as e:
        logger.warning("Cannot import wizard module '%s': %s", moduleName, e)
        return []

    providerNames = [
        "getSchedulerLanes",
        "getComputeLanes",
    ]

    for providerName in providerNames:
        provider = getattr(module, providerName, None)
        if not callable(provider):
            continue

        try:
            raw = provider()
            lanes = _extractLaneValues(raw)
            if lanes:
                return lanes
        except Exception as e:
            logger.warning(
                "Cannot obtain scheduler lanes from %s.%s: %s",
                moduleName,
                providerName,
                e,
            )

    return []


def _extractLaneValues(raw: Any) -> List[str]:
    if raw is None:
        return []

    if isinstance(raw, str):
        token = raw.strip()
        return [token] if token else []

    if isinstance(raw, dict):
        values: List[str] = []
        for key in raw.keys():
            token = str(key).strip()
            if token:
                values.append(token)
        return values

    if isinstance(raw, (list, tuple, set)):
        items = list(raw)

        if len(items) == 2 and isinstance(items[0], (list, tuple, set)):
            return _extractLaneValues(items[0])

        values: List[str] = []
        for item in items:
            if isinstance(item, (list, tuple, set, dict)):
                nested = _extractLaneValues(item)
                if nested:
                    values.extend(nested)
                    continue

            token = str(item).strip()
            if token:
                values.append(token)

        return _uniqueStrings(values)

    return []


def _readProtocolParamValue(protocol, paramName: str) -> str:
    protVar = getattr(protocol, paramName, None)
    if protVar is None:
        return ""

    getter = getattr(protVar, "get", None)
    if callable(getter):
        try:
            value = getter()
            return "" if value is None else str(value).strip()
        except Exception:
            pass

    try:
        return str(protVar).strip()
    except Exception:
        return ""


def _readProtocolNumericValue(protocol, paramName: str, default: int = 0) -> int:
    protVar = getattr(protocol, paramName, None)
    if protVar is None:
        return default

    value = None
    getter = getattr(protVar, "get", None)

    if callable(getter):
        try:
            value = getter()
        except Exception:
            value = None

    if value is None:
        try:
            value = protVar
        except Exception:
            value = None

    if value in (None, ""):
        return default

    try:
        return int(round(float(value)))
    except Exception:
        return default


def _normalizeMaskRadiusAction(wizardInputs: Dict[str, Any]) -> str:
    if not wizardInputs:
        return "open"

    actionRaw = wizardInputs.get("action")
    if actionRaw is None:
        if "radius" in wizardInputs:
            return "apply"
        return "open"

    action = str(actionRaw).strip().lower()
    if action in {"preview", "apply", "open"}:
        return action
    return "open"


def _coercePositiveInt(value: Any, default: int) -> int:
    if value in (None, ""):
        return max(1, int(default))

    try:
        parsed = int(round(float(value)))
        return max(1, parsed)
    except Exception:
        return max(1, int(default))


def _buildMaskRadiusViewerState(
    *,
    protocol,
    currentProject=None,
    radius: int,
    selectedIndex: int,
    canvasSize: int = 512,
) -> Dict[str, Any]:
    items = _listMaskRadiusItems(protocol)
    selectedItem = _resolveMaskRadiusSelection(items, selectedIndex)

    previewImage, _, origW, origH = _buildMaskRadiusPreviewImage(
        protocol=protocol,
        currentProject=currentProject,
        radius=radius,
        selectedItem=selectedItem,
        canvasSize=canvasSize,
    )

    samplingRate = _getMaskRadiusSamplingRate(protocol)
    radiusAngstrom = None
    if samplingRate is not None and samplingRate > 0:
        radiusAngstrom = round(float(radius) * float(samplingRate), 1)

    return {
        "items": [_serializeMaskRadiusItem(item) for item in items],
        "selectedIndex": int(selectedItem["index"]) if selectedItem else 1,
        "radius": int(radius),
        "radiusMin": 1,
        "radiusStep": 1,
        "radiusAngstrom": radiusAngstrom,
        "samplingRate": samplingRate,
        "preview": {
            "imageUrl": _pilImageToDataUrl(previewImage),
            "width": previewImage.width,
            "height": previewImage.height,
            "caption": "Central slice",
        },
    }


def _listMaskRadiusItems(protocol, maxItems: int = 200) -> List[Dict[str, Any]]:
    collection = _findPreviewCollection(protocol)
    if collection is None:
        source = _findPreviewImageSource(protocol)
        if source is None:
            return []
        filePath, index = source
        return [
            {
                "id": _buildMaskRadiusItemId(filePath, index, 1),
                "label": _formatMaskRadiusItemLabel(filePath, index, 1),
                "index": int(index) if index is not None else 1,
                "filePath": str(filePath),
            }
        ]

    items: List[Dict[str, Any]] = []
    for position, item in enumerate(_iterCollectionItems(collection), start=1):
        if len(items) >= maxItems:
            break

        source = _extractDirectImageSource(item)
        if source is None:
            continue

        filePath, index = source
        safeIndex = int(index) if index is not None else position
        items.append(
            {
                "id": _buildMaskRadiusItemId(filePath, safeIndex, position),
                "label": _formatMaskRadiusItemLabel(filePath, safeIndex, position),
                "index": safeIndex,
                "filePath": str(filePath),
            }
        )

    if items:
        return items

    source = _extractImageSourceFromObject(collection)
    if source is not None:
        filePath, index = source
        return [
            {
                "id": _buildMaskRadiusItemId(filePath, index, 1),
                "label": _formatMaskRadiusItemLabel(filePath, index, 1),
                "index": int(index) if index is not None else 1,
                "filePath": str(filePath),
            }
        ]

    return []


def _findPreviewCollection(protocol):
    candidateAttrs = [
        "inputParticles",
        "inputImages",
        "inputImage",
        "inputMicrographs",
        "inputMicrograph",
        "inputAverages",
        "inputAverage",
        "inputClasses",
        "inputClass",
        "inputVolumes",
        "inputVolume",
        "inputVol",
        "source",
        "images",
        "particles",
        "volume",
    ]

    for attrName in candidateAttrs:
        holder = getattr(protocol, attrName, None)
        obj = _dereferencePointerLike(holder)
        if obj is None:
            continue

        if callable(getattr(obj, "iterItems", None)):
            return obj

        source = _extractImageSourceFromObject(obj)
        if source is not None:
            return obj

    return None


def _iterCollectionItems(collection):
    iterItems = getattr(collection, "iterItems", None)
    if not callable(iterItems):
        return []

    try:
        return iterItems(iterate=False)
    except TypeError:
        try:
            return iterItems()
        except Exception:
            return []
    except Exception:
        return []


def _serializeMaskRadiusItem(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(item.get("id") or ""),
        "label": str(item.get("label") or ""),
        "index": int(item.get("index") or 1),
    }


def _resolveMaskRadiusSelection(
    items: List[Dict[str, Any]],
    selectedIndex: int,
) -> Optional[Dict[str, Any]]:
    if not items:
        return None

    for item in items:
        if int(item.get("index") or 0) == int(selectedIndex):
            return item

    return items[0]


def _buildMaskRadiusItemId(filePath: str, index: Optional[int], position: int) -> str:
    baseName = os.path.basename(str(filePath or "")).strip() or "item"
    token = int(index) if index is not None else int(position)
    return f"{baseName}:{token}"


def _formatMaskRadiusItemLabel(filePath: str, index: Optional[int], position: int) -> str:
    baseName = os.path.basename(str(filePath or "")).strip() or "image"
    token = int(index) if index is not None else int(position)
    return f"{token:03d}@{baseName}"


def _getMaskRadiusSamplingRate(protocol) -> Optional[float]:
    collection = _findPreviewCollection(protocol)
    if collection is None:
        return None
    return _readSamplingRateFromObject(collection)


def _readSamplingRateFromObject(obj) -> Optional[float]:
    if obj is None:
        return None

    methodNames = [
        "getSamplingRate",
        "getSampling",
        "getPixelSize",
        "getTsSampling",
        "getRate",
    ]

    for methodName in methodNames:
        method = getattr(obj, methodName, None)
        if not callable(method):
            continue

        try:
            value = method()
            if value in (None, ""):
                continue
            parsed = float(value)
            if parsed > 0:
                return parsed
        except Exception:
            continue

    attrNames = [
        "samplingRate",
        "sampling",
        "pixelSize",
    ]

    for attrName in attrNames:
        try:
            value = getattr(obj, attrName, None)
            if callable(getattr(value, "get", None)):
                value = value.get()
            if value in (None, ""):
                continue
            parsed = float(value)
            if parsed > 0:
                return parsed
        except Exception:
            continue

    return None


def _buildMaskRadiusPreviewImage(
    *,
    protocol,
    currentProject=None,
    radius: int,
    selectedItem: Optional[Dict[str, Any]] = None,
    canvasSize: int = 512,
) -> Tuple[Image.Image, float, float, float]:
    baseImage = _loadPreviewBaseImageFromSelection(selectedItem)

    if baseImage is None:
        baseImage = _loadPreviewBaseImage(protocol, canvasSize=canvasSize)

    if baseImage is None:
        baseImage = _buildFallbackPreviewBase(canvasSize=canvasSize)

    baseImage = baseImage.convert("RGBA")

    origW, origH = baseImage.size
    if origW <= 0 or origH <= 0:
        baseImage = _buildFallbackPreviewBase(canvasSize=canvasSize).convert("RGBA")
        origW, origH = baseImage.size

    fitScale = min(canvasSize / float(origW), canvasSize / float(origH))
    previewW = max(1, int(round(origW * fitScale)))
    previewH = max(1, int(round(origH * fitScale)))

    resized = baseImage.resize((previewW, previewH), Image.Resampling.BILINEAR)

    canvas = Image.new("RGBA", (canvasSize, canvasSize), (205, 205, 205, 255))
    offsetX = (canvasSize - previewW) // 2
    offsetY = (canvasSize - previewH) // 2
    canvas.paste(resized, (offsetX, offsetY))

    return canvas.convert("RGB"), fitScale, origW, origH


def _loadPreviewBaseImageFromSelection(
    selectedItem: Optional[Dict[str, Any]],
) -> Optional[Image.Image]:
    if not selectedItem:
        return None

    filePath = str(selectedItem.get("filePath") or "").strip()
    if not filePath or not os.path.exists(filePath):
        return None

    index = selectedItem.get("index")
    try:
        safeIndex = int(index) if index is not None else None
    except Exception:
        safeIndex = None

    pilImg = _openImageSource(filePath, index=safeIndex)
    if pilImg is None:
        return None

    return _normalizePreviewImage(pilImg)


def _loadPreviewBaseImage(protocol, canvasSize: int = 512) -> Optional[Image.Image]:
    source = _findPreviewImageSource(protocol)
    if source is None:
        return None

    filePath, index = source
    if not filePath or not os.path.exists(filePath):
        return None

    pilImg = _openImageSource(filePath, index=index)
    if pilImg is None:
        return None

    return _normalizePreviewImage(pilImg)


def _normalizePreviewImage(pilImg: Image.Image) -> Optional[Image.Image]:
    arr = np.asarray(pilImg)
    if arr.ndim == 3 and arr.shape[-1] >= 3:
        arr = arr[..., :3].mean(axis=-1)

    arr = arr.astype(np.float32, copy=False)

    finiteMask = np.isfinite(arr)
    if not finiteMask.any():
        return None

    valid = arr[finiteMask]
    low = float(np.percentile(valid, 1.0))
    high = float(np.percentile(valid, 99.0))

    if high <= low:
        low = float(valid.min())
        high = float(valid.max())

    if high <= low:
        norm = np.zeros_like(arr, dtype=np.uint8)
    else:
        clipped = np.clip(arr, low, high)
        norm = ((clipped - low) / (high - low + 1e-12) * 255.0).astype(np.uint8)

    img = Image.fromarray(norm, mode="L").convert("RGB")
    return img


def _findPreviewImageSource(protocol) -> Optional[Tuple[str, Optional[int]]]:
    candidateAttrs = [
        "inputParticles",
        "inputImages",
        "inputImage",
        "inputMicrographs",
        "inputMicrograph",
        "inputAverages",
        "inputAverage",
        "inputClasses",
        "inputClass",
        "inputVolumes",
        "inputVolume",
        "inputVol",
        "source",
        "images",
        "particles",
        "volume",
    ]

    for attrName in candidateAttrs:
        holder = getattr(protocol, attrName, None)
        obj = _dereferencePointerLike(holder)
        if obj is None:
            continue

        source = _extractImageSourceFromObject(obj)
        if source is not None:
            return source

    return None


def _dereferencePointerLike(obj):
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


def _extractImageSourceFromObject(obj) -> Optional[Tuple[str, Optional[int]]]:
    source = _extractDirectImageSource(obj)
    if source is not None:
        return source

    iterItems = getattr(obj, "iterItems", None)
    if callable(iterItems):
        try:
            for item in iterItems(iterate=False):
                source = _extractDirectImageSource(item)
                if source is not None:
                    return source
                break
        except TypeError:
            try:
                for item in iterItems():
                    source = _extractDirectImageSource(item)
                    if source is not None:
                        return source
                    break
            except Exception:
                pass
        except Exception:
            pass

    firstItem = getattr(obj, "getFirstItem", None)
    if callable(firstItem):
        try:
            item = firstItem()
            if item is not None:
                source = _extractDirectImageSource(item)
                if source is not None:
                    return source
        except Exception:
            pass

    return None


def _extractDirectImageSource(obj) -> Optional[Tuple[str, Optional[int]]]:
    getLocation = getattr(obj, "getLocation", None)
    if callable(getLocation):
        try:
            location = getLocation()
            if (
                isinstance(location, (list, tuple))
                and len(location) == 2
                and location[1]
            ):
                index = int(location[0]) if location[0] is not None else None
                filePath = str(location[1])
                return filePath, index
        except Exception:
            pass

    getFileName = getattr(obj, "getFileName", None)
    if callable(getFileName):
        try:
            filePath = getFileName()
            if filePath:
                index = None
                getIndex = getattr(obj, "getIndex", None)
                if callable(getIndex):
                    try:
                        index = int(getIndex())
                    except Exception:
                        index = None
                return str(filePath), index
        except Exception:
            pass

    return None


def _openImageSource(filePath: str, index: Optional[int] = None) -> Optional[Image.Image]:
    fileExt = os.path.splitext(filePath)[1].lower()

    if fileExt in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
        try:
            return Image.open(filePath).convert("L")
        except Exception:
            pass

    try:
        from pwem.emlib.image.image_readers import ImageReadersRegistry

        reader = ImageReadersRegistry.open(filePath)

        if index is not None:
            try:
                pilImg = reader.getImage(index=index, pilImage=True)
                if pilImg is not None:
                    return pilImg.convert("L") if hasattr(pilImg, "convert") else pilImg
            except Exception:
                pass

        try:
            pilImg = reader.getImage(index=1, pilImage=True)
            if pilImg is not None:
                return pilImg.convert("L") if hasattr(pilImg, "convert") else pilImg
        except Exception:
            pass

        try:
            pilImg = reader.getImage(index=0, pilImage=True)
            if pilImg is not None:
                return pilImg.convert("L") if hasattr(pilImg, "convert") else pilImg
        except Exception:
            pass

        try:
            pilImg = reader.getCentralImage(pilImage=True)
            if pilImg is not None:
                return pilImg.convert("L") if hasattr(pilImg, "convert") else pilImg
        except Exception:
            pass
    except Exception:
        pass

    return None


def _buildFallbackPreviewBase(canvasSize: int = 512) -> Image.Image:
    bg = Image.new("RGB", (canvasSize, canvasSize), (196, 196, 196))
    draw = ImageDraw.Draw(bg)

    pad = 18
    draw.rectangle(
        (pad, pad, canvasSize - pad, canvasSize - pad),
        outline=(150, 150, 150),
        width=1,
    )

    cx = canvasSize // 2
    cy = canvasSize // 2
    draw.line((cx, pad + 12, cx, canvasSize - pad - 12), fill=(165, 165, 165), width=1)
    draw.line((pad + 12, cy, canvasSize - pad - 12, cy), fill=(165, 165, 165), width=1)

    return bg


def _pilImageToDataUrl(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"