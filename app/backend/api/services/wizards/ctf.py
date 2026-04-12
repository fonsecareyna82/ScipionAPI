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

from functools import lru_cache

import base64
import io
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image as PILImage, ImageFilter

from .base import instantiateWizard
from .mask_radius import (
    buildFallbackPreviewBase,
    getMaskRadiusSamplingRate,
    listMaskRadiusItems,
    openImageSource,
    resolveMaskRadiusSelection,
    serializeMaskRadiusItem,
)

logger = logging.getLogger(__name__)

CTF_HELP_MESSAGE = (
    "The values of the CTF downsampling and the low/high frequency limits can be "
    "controlled interactively in the web wizard."
)


def executeCtfPreviewWizard(
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
    wizardInputs = wizardInputs or {}

    downsampleParam, lowFreqParam, highFreqParam = _resolveCtfParamNames(
        primaryParam=str(paramName or "").strip(),
        targetParams=list(descriptor.get("targetParams") or []),
    )

    autoEnabled = _readProtocolBoolValue(protocol, "AutoDownsampling", default=False)

    currentDownsample = _readProtocolFloatValue(protocol, downsampleParam, default=1.0)
    autoDownsample = (
        _getWizardAutoDownsampling(
            wizardClass=wizardClass,
            protocol=protocol,
            fallback=currentDownsample,
        )
        if autoEnabled
        else currentDownsample
    )

    currentLowFreq = _readProtocolFloatValue(protocol, lowFreqParam, default=0.10)
    currentHighFreq = _readProtocolFloatValue(protocol, highFreqParam, default=0.35)

    action = _normalizeCtfAction(wizardInputs)
    selectedIndex = _coercePositiveInt(wizardInputs.get("selectedIndex"), default=1)

    downsample = _coercePositiveFloat(
        wizardInputs.get("downsample"),
        default=autoDownsample,
        minimum=1.0,
    )
    lowFreq = _coercePositiveFloat(
        wizardInputs.get("lowFreq"),
        default=currentLowFreq,
        minimum=0.01,
    )
    highFreq = _coercePositiveFloat(
        wizardInputs.get("highFreq"),
        default=currentHighFreq,
        minimum=0.01,
    )

    if action == "apply":
        paramUpdates = {
            downsampleParam: downsample,
            lowFreqParam: lowFreq,
            highFreqParam: highFreq,
        }

        if autoEnabled and abs(float(downsample) - float(autoDownsample)) > 1e-6:
            paramUpdates["AutoDownsampling"] = False

        return {
            "paramUpdates": paramUpdates,
            "message": "CTF wizard values applied",
            "availableValues": [],
        }

    viewerState = _buildCtfViewerState(
        protocol=protocol,
        downsample=downsample,
        lowFreq=lowFreq,
        highFreq=highFreq,
        selectedIndex=selectedIndex,
        downsampleParam=downsampleParam,
        lowFreqParam=lowFreqParam,
        highFreqParam=highFreqParam,
        autoEnabled=autoEnabled,
        autoDownsample=autoDownsample,
        canvasSize=512,
    )

    return {
        "paramUpdates": {},
        "message": CTF_HELP_MESSAGE,
        "requiresUserInput": True,
        "availableValues": [],
        "inputSchema": {
            "type": "ctf_preview",
            "paramName": downsampleParam,
            "title": "Wizard",
            "fields": [
                {
                    "name": "downsample",
                    "label": downsampleParam,
                    "kind": "number",
                    "value": float(downsample),
                    "min": 1.0,
                    "max": float(viewerState.get("downsampleMax") or 8.0),
                    "step": float(viewerState.get("downsampleStep") or 0.01),
                },
                {
                    "name": "lowFreq",
                    "label": lowFreqParam,
                    "kind": "number",
                    "value": float(lowFreq),
                    "min": float(viewerState.get("lowFreqMin") or 0.01),
                    "max": float(viewerState.get("lowFreqMax") or 0.5),
                    "step": float(viewerState.get("freqStep") or 0.01),
                },
                {
                    "name": "highFreq",
                    "label": highFreqParam,
                    "kind": "number",
                    "value": float(highFreq),
                    "min": float(viewerState.get("highFreqMin") or 0.01),
                    "max": float(viewerState.get("highFreqMax") or 0.5),
                    "step": float(viewerState.get("freqStep") or 0.01),
                },
            ],
        },
        "viewerState": viewerState,
    }


def _resolveCtfParamNames(
    primaryParam: str,
    targetParams: List[str],
) -> Tuple[str, str, str]:
    normalized = [str(item).strip() for item in targetParams if str(item).strip()]

    downsampleParam = next(
        (item for item in normalized if "down" in item.lower() or "factor" in item.lower()),
        "ctfDownFactor",
    )
    lowFreqParam = next(
        (item for item in normalized if "low" in item.lower()),
        "lowRes",
    )
    highFreqParam = next(
        (item for item in normalized if "high" in item.lower()),
        "highRes",
    )

    if primaryParam:
        primaryLower = primaryParam.lower()
        if "down" in primaryLower or "factor" in primaryLower:
            downsampleParam = primaryParam
        elif "low" in primaryLower:
            lowFreqParam = primaryParam
        elif "high" in primaryLower:
            highFreqParam = primaryParam

    return downsampleParam, lowFreqParam, highFreqParam


def _normalizeCtfAction(wizardInputs: Dict[str, Any]) -> str:
    if not wizardInputs:
        return "open"

    actionRaw = wizardInputs.get("action")
    if actionRaw is None:
        if any(key in wizardInputs for key in ("downsample", "lowFreq", "highFreq")):
            return "apply"
        return "open"

    action = str(actionRaw).strip().lower()
    if action in {"open", "preview", "apply"}:
        return action

    return "open"


def _readProtocolFloatValue(protocol, paramName: str, default: float = 0.0) -> float:
    if not paramName:
        return float(default)

    protVar = getattr(protocol, paramName, None)
    if protVar is None:
        return float(default)

    getter = getattr(protVar, "get", None)
    value = None

    if callable(getter):
        try:
            value = getter()
        except Exception:
            value = None

    if value is None:
        value = protVar

    if value in (None, ""):
        return float(default)

    try:
        return float(value)
    except Exception:
        try:
            return float(str(value).strip())
        except Exception:
            return float(default)


def _readProtocolBoolValue(protocol, paramName: str, default: bool = False) -> bool:
    protVar = getattr(protocol, paramName, None)
    if protVar is None:
        return bool(default)

    getter = getattr(protVar, "get", None)
    value = None

    if callable(getter):
        try:
            value = getter()
        except Exception:
            value = None

    if value is None:
        value = protVar

    if isinstance(value, bool):
        return value

    if value in (None, ""):
        return bool(default)

    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _getWizardAutoDownsampling(
    *,
    wizardClass,
    protocol,
    fallback: float,
) -> float:
    instance = instantiateWizard(wizardClass)
    if instance is None:
        return float(fallback)

    method = getattr(instance, "getAutodownsampling", None)
    if not callable(method):
        return float(fallback)

    try:
        value = method(protocol)
        if value in (None, ""):
            return float(fallback)
        return max(1.0, float(value))
    except Exception:
        return float(fallback)


def _coercePositiveFloat(value: Any, default: float, minimum: float = 0.0) -> float:
    if value in (None, ""):
        return max(float(minimum), float(default))

    try:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError
        return max(float(minimum), parsed)
    except Exception:
        return max(float(minimum), float(default))


def _coercePositiveInt(value: Any, default: int) -> int:
    if value in (None, ""):
        return max(1, int(default))

    try:
        parsed = int(round(float(value)))
        return max(1, parsed)
    except Exception:
        return max(1, int(default))


def _buildCtfViewerState(
    *,
    protocol,
    downsample: float,
    lowFreq: float,
    highFreq: float,
    selectedIndex: int,
    downsampleParam: str,
    lowFreqParam: str,
    highFreqParam: str,
    autoEnabled: bool,
    autoDownsample: float,
    canvasSize: int = 512,
) -> Dict[str, Any]:
    items = listMaskRadiusItems(protocol)
    selectedItem = resolveMaskRadiusSelection(items, selectedIndex)

    micrographImage, sourceWidth, sourceHeight = _buildMicrographPreviewImage(
        selectedItem=selectedItem,
        canvasSize=canvasSize,
    )
    psdImage = _buildPsdPreviewImage(
        selectedItem=selectedItem,
        downsample=downsample,
        canvasSize=canvasSize,
    )

    samplingRate = getMaskRadiusSamplingRate(protocol)

    freqMax = max(
        0.5,
        float(lowFreq) * 1.5,
        float(highFreq) * 1.5,
    )

    resolvedIndex = int(selectedItem["index"]) if selectedItem else 1

    return {
        "items": [serializeMaskRadiusItem(item) for item in items],
        "selectedIndex": resolvedIndex,
        "downsample": float(downsample),
        "downsampleMin": 1.0,
        "downsampleMax": max(8.0, float(autoDownsample) * 4.0, float(downsample) * 2.0),
        "downsampleStep": 0.01,
        "lowFreq": float(lowFreq),
        "lowFreqMin": 0.01,
        "lowFreqMax": freqMax,
        "highFreq": float(highFreq),
        "highFreqMin": 0.01,
        "highFreqMax": freqMax,
        "freqStep": 0.01,
        "samplingRate": samplingRate,
        "showInAngstroms": True,
        "downsampleParam": downsampleParam,
        "lowFreqParam": lowFreqParam,
        "highFreqParam": highFreqParam,
        "autoDownsampling": bool(autoEnabled),
        "autoDownsampleValue": float(autoDownsample),
        "micrographPreview": {
            "imageUrl": _pilImageToDataUrl(micrographImage),
            "width": micrographImage.width,
            "height": micrographImage.height,
            "caption": "Micrograph",
            "sourceWidth": int(sourceWidth),
            "sourceHeight": int(sourceHeight),
        },
        "psdPreview": {
            "imageUrl": _pilImageToDataUrl(psdImage),
            "width": psdImage.width,
            "height": psdImage.height,
            "caption": "PSD",
            "sourceWidth": int(sourceWidth),
            "sourceHeight": int(sourceHeight),
        },
        "preview": {
            "imageUrl": _pilImageToDataUrl(psdImage),
            "width": psdImage.width,
            "height": psdImage.height,
            "caption": "PSD",
            "sourceWidth": int(sourceWidth),
            "sourceHeight": int(sourceHeight),
        },
    }


def _buildMicrographPreviewImage(
    *,
    selectedItem: Optional[Dict[str, Any]],
    canvasSize: int = 512,
) -> Tuple[PILImage.Image, int, int]:
    source = _extractSelectedSource(selectedItem)
    if source is None:
        fallback = buildFallbackPreviewBase(canvasSize=canvasSize).convert("RGB")
        return fallback, fallback.width, fallback.height

    filePath, sourceIndex = source
    cachedPng = _build_cached_micrograph_preview(filePath, sourceIndex, canvasSize)
    image = _pngBytesToPilImage(cachedPng)

    arr = _load_cached_micrograph_array(filePath, sourceIndex)
    if arr is None:
        return image, image.width, image.height

    return image, int(arr.shape[1]), int(arr.shape[0])


def _buildPsdPreviewImage(
    *,
    selectedItem: Optional[Dict[str, Any]],
    downsample: float,
    canvasSize: int = 512,
) -> PILImage.Image:
    source = _extractSelectedSource(selectedItem)
    if source is None:
        return buildFallbackPreviewBase(canvasSize=canvasSize).convert("RGB")

    filePath, sourceIndex = source
    downsampleKey = max(100, int(round(float(downsample) * 100.0)))
    cachedPng = _build_cached_psd_preview(filePath, sourceIndex, canvasSize, downsampleKey)
    return _pngBytesToPilImage(cachedPng)


def _extractSelectedSource(
    selectedItem: Optional[Dict[str, Any]],
) -> Optional[Tuple[str, int]]:
    if not selectedItem:
        return None

    filePath = str(selectedItem.get("filePath") or "").strip()
    if not filePath:
        return None

    indexRaw = selectedItem.get("sourceIndex", selectedItem.get("index"))
    try:
        sourceIndex = int(indexRaw) if indexRaw is not None else 1
    except Exception:
        sourceIndex = 1

    return filePath, sourceIndex


@lru_cache(maxsize=128)
def _load_cached_micrograph_array(filePath: str, sourceIndex: int) -> Optional[np.ndarray]:
    pilImg = openImageSource(filePath, index=sourceIndex)
    if pilImg is None:
        return None

    if hasattr(pilImg, "convert"):
        try:
            pilImg = pilImg.convert("L")
        except Exception:
            pass

    arr = np.asarray(pilImg, dtype=np.float32)
    arr = np.squeeze(arr)

    if arr.ndim != 2 or arr.size == 0:
        return None

    return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)


@lru_cache(maxsize=256)
def _build_cached_micrograph_preview(filePath: str, sourceIndex: int, canvasSize: int) -> bytes:
    arr = _load_cached_micrograph_array(filePath, sourceIndex)
    if arr is None:
        image = buildFallbackPreviewBase(canvasSize=canvasSize).convert("RGB")
        return _pilImageToPngBytes(image)

    valid = arr[np.isfinite(arr)]
    if valid.size == 0:
        image = buildFallbackPreviewBase(canvasSize=canvasSize).convert("RGB")
        return _pilImageToPngBytes(image)

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

    image = PILImage.fromarray(norm, mode="L").convert("RGB")
    image = _fitImageToCanvas(image, canvasSize)
    return _pilImageToPngBytes(image)


@lru_cache(maxsize=256)
def _build_cached_psd_preview(
    filePath: str,
    sourceIndex: int,
    canvasSize: int,
    downsampleKey: int,
) -> bytes:
    arr = _load_cached_micrograph_array(filePath, sourceIndex)
    if arr is None:
        image = buildFallbackPreviewBase(canvasSize=canvasSize).convert("RGB")
        return _pilImageToPngBytes(image)

    arr = _centerCropSquare(arr)

    effectiveDownsample = max(1.0, float(downsampleKey) / 100.0)
    if effectiveDownsample > 1.0:
        targetSize = max(256, int(round(arr.shape[0] / effectiveDownsample)))
        arr = _resizeArrayToGray(arr, targetSize, targetSize)

    arr = arr.astype(np.float32, copy=False)
    arr -= float(np.mean(arr))

    window = np.outer(np.hanning(arr.shape[0]), np.hanning(arr.shape[1]))
    arr *= window

    fft = np.fft.fftshift(np.fft.fft2(arr))
    power = np.log1p(np.abs(fft) ** 2)

    validPower = power[np.isfinite(power)]
    if validPower.size == 0:
        image = buildFallbackPreviewBase(canvasSize=canvasSize).convert("RGB")
        return _pilImageToPngBytes(image)

    low0 = float(np.percentile(validPower, 0.5))
    high0 = float(np.percentile(validPower, 99.8))

    if high0 <= low0:
        low0 = float(validPower.min())
        high0 = float(validPower.max())

    if high0 <= low0:
        power8 = np.zeros_like(power, dtype=np.uint8)
    else:
        clipped0 = np.clip(power, low0, high0)
        power8 = ((clipped0 - low0) / (high0 - low0 + 1e-12) * 255.0).astype(np.uint8)

    blurred = np.asarray(
        PILImage.fromarray(power8, mode="L").filter(ImageFilter.GaussianBlur(radius=10)),
        dtype=np.float32,
    )
    enhanced = power8.astype(np.float32) - 0.85 * blurred

    validEnhanced = enhanced[np.isfinite(enhanced)]
    if validEnhanced.size == 0:
        image = buildFallbackPreviewBase(canvasSize=canvasSize).convert("RGB")
        return _pilImageToPngBytes(image)

    low1 = float(np.percentile(validEnhanced, 1.0))
    high1 = float(np.percentile(validEnhanced, 99.7))

    if high1 <= low1:
        low1 = float(validEnhanced.min())
        high1 = float(validEnhanced.max())

    if high1 <= low1:
        norm = np.zeros_like(enhanced, dtype=np.uint8)
    else:
        clipped1 = np.clip(enhanced, low1, high1)
        norm = ((clipped1 - low1) / (high1 - low1 + 1e-12) * 255.0).astype(np.uint8)

    image = PILImage.fromarray(norm, mode="L").convert("RGB")
    image = _fitImageToCanvas(image, canvasSize)
    image = _applyCircularMask(image)
    return _pilImageToPngBytes(image)


def _centerCropSquare(arr: np.ndarray) -> np.ndarray:
    height, width = arr.shape[:2]
    size = min(height, width)

    offsetY = max(0, (height - size) // 2)
    offsetX = max(0, (width - size) // 2)

    return arr[offsetY:offsetY + size, offsetX:offsetX + size]


def _applyCircularMask(image: PILImage.Image) -> PILImage.Image:
    rgb = np.asarray(image.convert("RGB")).copy()
    height, width = rgb.shape[:2]

    yy, xx = np.ogrid[:height, :width]
    cy = height / 2.0
    cx = width / 2.0
    radius = min(width, height) / 2.0

    dist2 = (xx - cx) ** 2 + (yy - cy) ** 2
    mask = dist2 <= radius ** 2

    background = np.full_like(rgb, 165)
    background[mask] = rgb[mask]

    return PILImage.fromarray(background, mode="RGB")


def _fitImageToCanvas(image: PILImage.Image, canvasSize: int) -> PILImage.Image:
    fitScale = min(canvasSize / float(image.width), canvasSize / float(image.height))
    previewW = max(1, int(round(image.width * fitScale)))
    previewH = max(1, int(round(image.height * fitScale)))

    resized = image.resize((previewW, previewH), PILImage.Resampling.BILINEAR)

    canvas = PILImage.new("RGB", (canvasSize, canvasSize), (205, 205, 205))
    offsetX = (canvasSize - previewW) // 2
    offsetY = (canvasSize - previewH) // 2
    canvas.paste(resized, (offsetX, offsetY))
    return canvas


def _resizeArrayToGray(arr: np.ndarray, width: int, height: int) -> np.ndarray:
    arr = np.asarray(arr, dtype=np.float32)
    amin = float(np.min(arr))
    amax = float(np.max(arr))

    if not math.isfinite(amin) or not math.isfinite(amax) or amax <= amin:
        arr8 = np.zeros(arr.shape, dtype=np.uint8)
    else:
        arr8 = ((arr - amin) / (amax - amin + 1e-12) * 255.0).clip(0, 255).astype(np.uint8)

    image = PILImage.fromarray(arr8, mode="L")
    image = image.resize(
        (max(1, int(width)), max(1, int(height))),
        PILImage.Resampling.BILINEAR,
    )
    return np.asarray(image, dtype=np.float32)


def _pilImageToPngBytes(image: PILImage.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _pngBytesToPilImage(data: bytes) -> PILImage.Image:
    return PILImage.open(io.BytesIO(data)).convert("RGB")


def _pngBytesToDataUrl(data: bytes) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _pilImageToDataUrl(image: PILImage.Image) -> str:
    return _pngBytesToDataUrl(_pilImageToPngBytes(image))