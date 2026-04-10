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
    currentValue = _readProtocolNumericValue(protocol, paramName, default=0)

    if not wizardInputs:
        previewUrl = _buildMaskRadiusPreviewUrl(
            projectId=projectId,
            protocol=protocol,
            paramName=paramName,
            currentProject=currentProject,
            radius=currentValue,
        )

        return {
            "paramUpdates": {},
            "message": "Wizard requires user input",
            "requiresUserInput": True,
            "availableValues": [],
            "inputSchema": {
                "type": "mask_radius",
                "paramName": paramName,
                "title": "Mask radius",
                "fields": [
                    {
                        "name": "radius",
                        "label": "Radius",
                        "kind": "number",
                        "value": currentValue,
                        "min": 1,
                        "step": 1,
                    }
                ],
            },
            "preview": {
                "imageUrl": previewUrl,
                "width": 512 if previewUrl else None,
                "height": 512 if previewUrl else None,
            },
        }

    radiusRaw = wizardInputs.get("radius")
    if radiusRaw is None:
        raise RuntimeError("Wizard input 'radius' is required")

    radius = int(round(float(radiusRaw)))
    if radius < 1:
        radius = 1

    return {
        "paramUpdates": {
            paramName: radius,
        },
        "message": f"Mask radius set to {radius}",
        "availableValues": [],
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


def _buildMaskRadiusPreviewUrl(
    *,
    projectId: Optional[int],
    protocol,
    paramName: str,
    currentProject=None,
    radius: Optional[int] = None,
) -> Optional[str]:
    try:
        radiusValue = radius if radius is not None else _readProtocolNumericValue(protocol, paramName, default=0)
        if radiusValue is None or int(radiusValue) <= 0:
            radiusValue = 1
        radiusValue = int(radiusValue)

        image, scale = _buildMaskRadiusPreviewImage(
            protocol=protocol,
            currentProject=currentProject,
            radius=radiusValue,
            canvasSize=512,
        )
        _ = scale  # reserved for future use

        return _pilImageToDataUrl(image)
    except Exception as e:
        logger.warning("Could not build mask radius preview: %s", e, exc_info=True)
        return None


def _buildMaskRadiusPreviewImage(
    *,
    protocol,
    currentProject=None,
    radius: int,
    canvasSize: int = 512,
) -> Tuple[Image.Image, float]:
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

    canvas = Image.new("RGBA", (canvasSize, canvasSize), (22, 27, 34, 255))
    offsetX = (canvasSize - previewW) // 2
    offsetY = (canvasSize - previewH) // 2
    canvas.paste(resized, (offsetX, offsetY))

    overlay = Image.new("RGBA", (canvasSize, canvasSize), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    centerX = offsetX + previewW / 2.0
    centerY = offsetY + previewH / 2.0

    scaledRadius = max(4, int(round(radius * fitScale)))
    maxAllowed = max(4, min(previewW, previewH) // 2 - 4)
    scaledRadius = min(scaledRadius, maxAllowed)

    bbox = (
        int(round(centerX - scaledRadius)),
        int(round(centerY - scaledRadius)),
        int(round(centerX + scaledRadius)),
        int(round(centerY + scaledRadius)),
    )

    draw.ellipse(
        bbox,
        outline=(255, 90, 90, 255),
        width=3,
        fill=(255, 90, 90, 40),
    )

    draw.ellipse(
        (
            int(round(centerX - 2)),
            int(round(centerY - 2)),
            int(round(centerX + 2)),
            int(round(centerY + 2)),
        ),
        fill=(255, 255, 255, 220),
    )

    result = Image.alpha_composite(canvas, overlay).convert("RGB")
    return result, fitScale


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
    bg = Image.new("RGB", (canvasSize, canvasSize), (28, 34, 44))
    draw = ImageDraw.Draw(bg)

    pad = 36
    draw.rectangle(
        (pad, pad, canvasSize - pad, canvasSize - pad),
        outline=(90, 100, 116),
        width=2,
    )

    cx = canvasSize // 2
    cy = canvasSize // 2
    draw.line((cx, pad + 20, cx, canvasSize - pad - 20), fill=(70, 78, 92), width=1)
    draw.line((pad + 20, cy, canvasSize - pad - 20, cy), fill=(70, 78, 92), width=1)

    return bg


def _pilImageToDataUrl(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"