# ******************************************************************************
# *
# * Authors:     Yunior C. Fonseca Reyna
# *
# * Unidad de  Bioinformatica of Centro Nacional de Biotecnologia , CSIC
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 3 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************

from __future__ import annotations

import base64
import io
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw

from .base import readProtocolNumericValue

logger = logging.getLogger(__name__)

MASK_RADIUS_HELP_MESSAGE = (
    "The values of the mask radius can be controlled via both the slider or the "
    "mousewheel (when the mouse cursor is over the image)."
)

MASK_RADII_HELP_MESSAGE = (
    "The values of the inner and outer radii can be controlled via the sliders "
    "or the mousewheel (when the mouse cursor is over the image)."
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
    currentValue = max(1, readProtocolNumericValue(protocol, paramName, default=1))
    wizardInputs = wizardInputs or {}

    action = normalizeMaskRadiusAction(wizardInputs)
    radius = coercePositiveInt(wizardInputs.get("radius"), default=currentValue)
    selectedIndex = coercePositiveInt(wizardInputs.get("selectedIndex"), default=1)

    if action == "apply":
        return {
            "paramUpdates": {
                paramName: radius,
            },
            "message": f"Mask radius set to {radius}",
            "availableValues": [],
        }

    viewerState = buildMaskRadiusViewerState(
        protocol=protocol,
        currentProject=currentProject,
        radius=radius,
        selectedIndex=selectedIndex,
        canvasSize=512,
    )

    return {
        "paramUpdates": {},
        "message": MASK_RADIUS_HELP_MESSAGE,
        "requiresUserInput": True,
        "availableValues": [],
        "inputSchema": {
            "type": "mask_radius",
            "paramName": paramName,
            "title": "Wizard",
        },
        "viewerState": viewerState,
    }


def executeMaskRadiiWizard(
    *,
    wizardClass,
    protocol,
    paramName: str,
    descriptor: Optional[Dict[str, Any]] = None,
    wizardInputs: Optional[Dict[str, Any]] = None,
    currentProject=None,
    projectId: Optional[int] = None,
) -> Dict[str, Any]:
    descriptor = descriptor or {}
    targetParams = list(descriptor.get("targetParams") or [])
    wizardInputs = wizardInputs or {}

    primaryParam = str(paramName or "").strip()
    secondaryParam = _resolveSecondaryMaskRadiiParam(primaryParam, targetParams)

    innerDefault, outerDefault = _readMaskRadiiDefaults(
        protocol=protocol,
        primaryParam=primaryParam,
        secondaryParam=secondaryParam,
    )

    action = normalizeMaskRadiusAction(wizardInputs)
    innerRadius = coercePositiveInt(
        wizardInputs.get("innerRadius"),
        default=innerDefault,
    )
    outerRadius = coercePositiveInt(
        wizardInputs.get("outerRadius"),
        default=outerDefault,
    )
    if outerRadius < innerRadius:
        outerRadius = innerRadius

    selectedIndex = coercePositiveInt(wizardInputs.get("selectedIndex"), default=1)

    if action == "apply":
        return {
            "paramUpdates": {
                primaryParam: innerRadius,
                secondaryParam: outerRadius,
            },
            "message": f"Mask radii set to {innerRadius} / {outerRadius}",
            "availableValues": [],
        }

    viewerState = buildMaskRadiiViewerState(
        protocol=protocol,
        currentProject=currentProject,
        innerRadius=innerRadius,
        outerRadius=outerRadius,
        selectedIndex=selectedIndex,
        primaryParam=primaryParam,
        secondaryParam=secondaryParam,
        canvasSize=512,
    )

    return {
        "paramUpdates": {},
        "message": MASK_RADII_HELP_MESSAGE,
        "requiresUserInput": True,
        "availableValues": [],
        "inputSchema": {
            "type": "mask_radii",
            "paramName": primaryParam,
            "title": "Wizard",
            "fields": [
                {
                    "name": "innerRadius",
                    "label": primaryParam,
                    "kind": "number",
                    "value": int(innerRadius),
                },
                {
                    "name": "outerRadius",
                    "label": secondaryParam,
                    "kind": "number",
                    "value": int(outerRadius),
                },
            ],
        },
        "viewerState": viewerState,
    }


def _resolveSecondaryMaskRadiiParam(
    primaryParam: str,
    targetParams: List[str],
) -> str:
    normalized = [str(item).strip() for item in targetParams if str(item).strip()]
    fallbackMap = {
        "innerRadius": "outerRadius",
        "particleRadius": "noiseRadius",
    }

    for candidate in normalized:
        if candidate != primaryParam:
            return candidate

    return fallbackMap.get(primaryParam, "outerRadius")


def _readMaskRadiiDefaults(
    *,
    protocol,
    primaryParam: str,
    secondaryParam: str,
) -> Tuple[int, int]:
    innerDefault = max(1, readProtocolNumericValue(protocol, primaryParam, default=1))
    outerDefault = max(innerDefault, readProtocolNumericValue(protocol, secondaryParam, default=max(innerDefault, 2 * innerDefault)))

    return innerDefault, outerDefault


def normalizeMaskRadiusAction(wizardInputs: Dict[str, Any]) -> str:
    if not wizardInputs:
        return "open"

    actionRaw = wizardInputs.get("action")
    if actionRaw is None:
        if "radius" in wizardInputs or "innerRadius" in wizardInputs or "outerRadius" in wizardInputs:
            return "apply"
        return "open"

    action = str(actionRaw).strip().lower()
    if action in {"preview", "apply", "open"}:
        return action
    return "open"


def coercePositiveInt(value: Any, default: int) -> int:
    if value in (None, ""):
        return max(1, int(default))

    try:
        parsed = int(round(float(value)))
        return max(1, parsed)
    except Exception:
        return max(1, int(default))


def buildMaskRadiusViewerState(
    *,
    protocol,
    currentProject=None,
    radius: int,
    selectedIndex: int,
    canvasSize: int = 512,
) -> Dict[str, Any]:
    items = listMaskRadiusItems(protocol)
    selectedItem = resolveMaskRadiusSelection(items, selectedIndex)

    previewImage, _, origW, origH = buildMaskRadiusPreviewImage(
        protocol=protocol,
        currentProject=currentProject,
        radius=radius,
        selectedItem=selectedItem,
        canvasSize=canvasSize,
    )

    samplingRate = getMaskRadiusSamplingRate(protocol)
    radiusAngstrom = None
    if samplingRate is not None and samplingRate > 0:
        radiusAngstrom = round(float(radius) * float(samplingRate), 1)

    radiusMax = max(1, int(min(origW, origH) // 2))

    return {
        "items": [serializeMaskRadiusItem(item) for item in items],
        "selectedIndex": int(selectedItem["index"]) if selectedItem else 1,
        "radius": int(radius),
        "radiusMin": 1,
        "radiusMax": radiusMax,
        "radiusStep": 1,
        "radiusAngstrom": radiusAngstrom,
        "samplingRate": samplingRate,
        "preview": {
            "imageUrl": pilImageToDataUrl(previewImage),
            "width": previewImage.width,
            "height": previewImage.height,
            "caption": "Central slice",
            "sourceWidth": int(origW),
            "sourceHeight": int(origH),
        },
    }


def buildMaskRadiiViewerState(
    *,
    protocol,
    currentProject=None,
    innerRadius: int,
    outerRadius: int,
    selectedIndex: int,
    primaryParam: str,
    secondaryParam: str,
    canvasSize: int = 512,
) -> Dict[str, Any]:
    items = listMaskRadiusItems(protocol)
    selectedItem = resolveMaskRadiusSelection(items, selectedIndex)

    previewImage, _, origW, origH = buildMaskRadiusPreviewImage(
        protocol=protocol,
        currentProject=currentProject,
        radius=outerRadius,
        selectedItem=selectedItem,
        canvasSize=canvasSize,
    )

    samplingRate = getMaskRadiusSamplingRate(protocol)

    innerRadiusAngstrom = None
    outerRadiusAngstrom = None
    if samplingRate is not None and samplingRate > 0:
        innerRadiusAngstrom = round(float(innerRadius) * float(samplingRate), 1)
        outerRadiusAngstrom = round(float(outerRadius) * float(samplingRate), 1)

    radiusMax = max(1, int(min(origW, origH) // 2))

    return {
        "items": [serializeMaskRadiusItem(item) for item in items],
        "selectedIndex": int(selectedItem["index"]) if selectedItem else 1,
        "innerRadius": int(innerRadius),
        "outerRadius": int(outerRadius),
        "innerRadiusMin": 1,
        "outerRadiusMin": 1,
        "radiusMax": radiusMax,
        "radiusStep": 1,
        "innerRadiusAngstrom": innerRadiusAngstrom,
        "outerRadiusAngstrom": outerRadiusAngstrom,
        "samplingRate": samplingRate,
        "primaryParam": primaryParam,
        "secondaryParam": secondaryParam,
        "preview": {
            "imageUrl": pilImageToDataUrl(previewImage),
            "width": previewImage.width,
            "height": previewImage.height,
            "caption": "Central slice",
            "sourceWidth": int(origW),
            "sourceHeight": int(origH),
        },
    }


def listMaskRadiusItems(protocol, maxItems: int = 200) -> List[Dict[str, Any]]:
    collection = findPreviewCollection(protocol)
    if collection is None:
        source = findPreviewImageSource(protocol)
        if source is None:
            return []
        filePath, index = source
        return [
            {
                "id": buildMaskRadiusItemId(filePath, index, 1),
                "label": formatMaskRadiusItemLabel(filePath, index, 1),
                "index": int(index) if index is not None else 1,
                "filePath": str(filePath),
            }
        ]

    items: List[Dict[str, Any]] = []
    for position, item in enumerate(iterCollectionItems(collection), start=1):
        if len(items) >= maxItems:
            break

        source = extractDirectImageSource(item)
        if source is None:
            continue

        filePath, index = source
        safeIndex = int(index) if index is not None else position
        items.append(
            {
                "id": buildMaskRadiusItemId(filePath, safeIndex, position),
                "label": formatMaskRadiusItemLabel(filePath, safeIndex, position),
                "index": safeIndex,
                "filePath": str(filePath),
            }
        )

    if items:
        return items

    source = extractImageSourceFromObject(collection)
    if source is not None:
        filePath, index = source
        return [
            {
                "id": buildMaskRadiusItemId(filePath, index, 1),
                "label": formatMaskRadiusItemLabel(filePath, index, 1),
                "index": int(index) if index is not None else 1,
                "filePath": str(filePath),
            }
        ]

    return []


def findPreviewCollection(protocol):
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
        obj = dereferencePointerLike(holder)
        if obj is None:
            continue

        if callable(getattr(obj, "iterItems", None)):
            return obj

        source = extractImageSourceFromObject(obj)
        if source is not None:
            return obj

    return None


def iterCollectionItems(collection):
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


def serializeMaskRadiusItem(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(item.get("id") or ""),
        "label": str(item.get("label") or ""),
        "index": int(item.get("index") or 1),
    }


def resolveMaskRadiusSelection(
    items: List[Dict[str, Any]],
    selectedIndex: int,
) -> Optional[Dict[str, Any]]:
    if not items:
        return None

    for item in items:
        if int(item.get("index") or 0) == int(selectedIndex):
            return item

    return items[0]


def buildMaskRadiusItemId(filePath: str, index: Optional[int], position: int) -> str:
    baseName = os.path.basename(str(filePath or "")).strip() or "item"
    token = int(index) if index is not None else int(position)
    return f"{baseName}:{token}"


def formatMaskRadiusItemLabel(filePath: str, index: Optional[int], position: int) -> str:
    baseName = os.path.basename(str(filePath or "")).strip() or "image"
    token = int(index) if index is not None else int(position)
    return f"{token:03d}@{baseName}"


def getMaskRadiusSamplingRate(protocol) -> Optional[float]:
    collection = findPreviewCollection(protocol)
    if collection is None:
        return None
    return readSamplingRateFromObject(collection)


def readSamplingRateFromObject(obj) -> Optional[float]:
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


def buildMaskRadiusPreviewImage(
    *,
    protocol,
    currentProject=None,
    radius: int,
    selectedItem: Optional[Dict[str, Any]] = None,
    canvasSize: int = 512,
) -> Tuple[Image.Image, float, float, float]:
    baseImage = loadPreviewBaseImageFromSelection(selectedItem)

    if baseImage is None:
        baseImage = loadPreviewBaseImage(protocol, canvasSize=canvasSize)

    if baseImage is None:
        baseImage = buildFallbackPreviewBase(canvasSize=canvasSize)

    baseImage = baseImage.convert("RGBA")

    origW, origH = baseImage.size
    if origW <= 0 or origH <= 0:
        baseImage = buildFallbackPreviewBase(canvasSize=canvasSize).convert("RGBA")
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


def loadPreviewBaseImageFromSelection(
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

    pilImg = openImageSource(filePath, index=safeIndex)
    if pilImg is None:
        return None

    return normalizePreviewImage(pilImg)


def loadPreviewBaseImage(protocol, canvasSize: int = 512) -> Optional[Image.Image]:
    source = findPreviewImageSource(protocol)
    if source is None:
        return None

    filePath, index = source
    if not filePath or not os.path.exists(filePath):
        return None

    pilImg = openImageSource(filePath, index=index)
    if pilImg is None:
        return None

    return normalizePreviewImage(pilImg)


def normalizePreviewImage(pilImg: Image.Image) -> Optional[Image.Image]:
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


def findPreviewImageSource(protocol) -> Optional[Tuple[str, Optional[int]]]:
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
        obj = dereferencePointerLike(holder)
        if obj is None:
            continue

        source = extractImageSourceFromObject(obj)
        if source is not None:
            return source

    return None


def dereferencePointerLike(obj):
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


def extractImageSourceFromObject(obj) -> Optional[Tuple[str, Optional[int]]]:
    source = extractDirectImageSource(obj)
    if source is not None:
        return source

    iterItems = getattr(obj, "iterItems", None)
    if callable(iterItems):
        try:
            for item in iterItems(iterate=False):
                source = extractDirectImageSource(item)
                if source is not None:
                    return source
                break
        except TypeError:
            try:
                for item in iterItems():
                    source = extractDirectImageSource(item)
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
                source = extractDirectImageSource(item)
                if source is not None:
                    return source
        except Exception:
            pass

    return None


def extractDirectImageSource(obj) -> Optional[Tuple[str, Optional[int]]]:
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


def openImageSource(filePath: str, index: Optional[int] = None) -> Optional[Image.Image]:
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


def buildFallbackPreviewBase(canvasSize: int = 512) -> Image.Image:
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


def pilImageToDataUrl(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"