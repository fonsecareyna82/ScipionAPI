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
from PIL import Image as PILImage, ImageEnhance, ImageFilter, ImageOps

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

PSD_PRE_DOWNSAMPLE_MIN_SIZE = 192
PSD_MAX_WORK_SIZE = 768

PSD_POST_BLUR_RADIUS = 0.55
PSD_AUTOCONTRAST_CUTOFF = 0.7
PSD_CONTRAST_GAIN = 1.18

PSD_GAMMA = 0.92
PSD_DISPLAY_AUTOCONTRAST_CUTOFF = 0.6
PSD_DISPLAY_CONTRAST_GAIN = 1.22
PSD_DISPLAY_GAMMA = 1.42
PSD_DISPLAY_DETAIL_GAIN = 0.18
PSD_UNSHARP_RADIUS = 1
PSD_UNSHARP_PERCENT = 150
PSD_UNSHARP_THRESHOLD = 2


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


def _polish_psd_image(image: PILImage.Image) -> PILImage.Image:
    image = image.filter(ImageFilter.GaussianBlur(radius=PSD_POST_BLUR_RADIUS))
    image = ImageOps.autocontrast(image, cutoff=PSD_AUTOCONTRAST_CUTOFF)
    image = ImageEnhance.Contrast(image).enhance(PSD_CONTRAST_GAIN)
    image = image.filter(
        ImageFilter.UnsharpMask(
            radius=PSD_UNSHARP_RADIUS,
            percent=PSD_UNSHARP_PERCENT,
            threshold=PSD_UNSHARP_THRESHOLD,
        )
    )
    return image

def _apply_psd_presentation(image: PILImage.Image) -> PILImage.Image:
    image = ImageOps.autocontrast(
        image,
        cutoff=PSD_DISPLAY_AUTOCONTRAST_CUTOFF,
    )

    baseArr = np.asarray(image, dtype=np.float32)
    blurredArr = np.asarray(
        image.filter(ImageFilter.GaussianBlur(radius=1.1)),
        dtype=np.float32,
    )

    enhancedArr = baseArr * (1.0 + PSD_DISPLAY_DETAIL_GAIN) - blurredArr * PSD_DISPLAY_DETAIL_GAIN
    enhancedArr = np.clip(enhancedArr, 0.0, 255.0).astype(np.uint8)

    image = PILImage.fromarray(enhancedArr, mode="L")
    image = ImageEnhance.Contrast(image).enhance(PSD_DISPLAY_CONTRAST_GAIN)

    lut = [
        int(round(255.0 * ((i / 255.0) ** PSD_DISPLAY_GAMMA)))
        for i in range(256)
    ]
    image = image.point(lut)

    image = image.filter(
        ImageFilter.UnsharpMask(
            radius=PSD_UNSHARP_RADIUS,
            percent=PSD_UNSHARP_PERCENT,
            threshold=PSD_UNSHARP_THRESHOLD,
        )
    )

    return image

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
    arr = _prepare_psd_input(arr, effectiveDownsample)

    if arr.ndim != 2 or arr.size == 0:
        image = buildFallbackPreviewBase(canvasSize=canvasSize).convert("RGB")
        return _pilImageToPngBytes(image)

    arr = arr.astype(np.float32, copy=False)
    arr -= float(np.mean(arr))

    std = float(np.std(arr))
    if std > 1e-6:
        arr /= std

    window = np.outer(np.hanning(arr.shape[0]), np.hanning(arr.shape[1])).astype(np.float32)
    arr *= window

    fft = np.fft.fftshift(np.fft.fft2(arr))
    power = np.log1p(np.abs(fft)).astype(np.float32, copy=False)
    power = _suppress_psd_center(power)

    norm = _normalize_to_uint8(
        power,
        lowPercentile=1.2,
        highPercentile=99.6,
        gamma=PSD_GAMMA,
    )

    image = PILImage.fromarray(norm, mode="L")
    image = _apply_psd_presentation(image)
    image = _apply_psd_downsample_zoom(image, effectiveDownsample)
    image = image.convert("RGB")
    image = _fitImageToCanvas(image, canvasSize)
    image = _applyCircularMask(image)
    return _pilImageToPngBytes(image)


def _prepare_psd_input(arr: np.ndarray, effectiveDownsample: float) -> np.ndarray:
    side = int(arr.shape[0])

    if effectiveDownsample > 1.0:
        reducedSide = max(
            PSD_PRE_DOWNSAMPLE_MIN_SIZE,
            int(round(float(side) / effectiveDownsample)),
        )

        if reducedSide < side:
            arr = _resizeArrayToGray(
                arr,
                reducedSide,
                reducedSide,
                resample=PILImage.Resampling.BOX,
            )

    if arr.shape[0] > PSD_MAX_WORK_SIZE:
        arr = _resizeArrayToGray(
            arr,
            PSD_MAX_WORK_SIZE,
            PSD_MAX_WORK_SIZE,
            resample=PILImage.Resampling.BILINEAR,
        )

    return arr.astype(np.float32, copy=False)


def _apply_psd_downsample_zoom(
    image: PILImage.Image,
    effectiveDownsample: float,
) -> PILImage.Image:
    if effectiveDownsample <= 1.01:
        return image

    width, height = image.size
    scaledWidth = max(width, int(round(width * effectiveDownsample)))
    scaledHeight = max(height, int(round(height * effectiveDownsample)))

    resized = image.resize(
        (scaledWidth, scaledHeight),
        PILImage.Resampling.BILINEAR,
    )

    left = max(0, (scaledWidth - width) // 2)
    top = max(0, (scaledHeight - height) // 2)
    right = left + width
    bottom = top + height

    return resized.crop((left, top, right, bottom))


def _normalize_to_uint8(
    arr: np.ndarray,
    lowPercentile: float,
    highPercentile: float,
    gamma: float = 1.0,
) -> np.ndarray:
    valid = arr[np.isfinite(arr)]
    if valid.size == 0:
        return np.zeros(arr.shape, dtype=np.uint8)

    low = float(np.percentile(valid, lowPercentile))
    high = float(np.percentile(valid, highPercentile))

    if high <= low:
        low = float(valid.min())
        high = float(valid.max())

    if high <= low:
        return np.zeros(arr.shape, dtype=np.uint8)

    norm = np.clip((arr - low) / (high - low + 1e-12), 0.0, 1.0)

    if gamma > 0 and abs(gamma - 1.0) > 1e-6:
        norm = np.power(norm, gamma)

    return (norm * 255.0).astype(np.uint8)


def _suppress_psd_center(power: np.ndarray) -> np.ndarray:
    height, width = power.shape[:2]
    cy = (height - 1) / 2.0
    cx = (width - 1) / 2.0

    yy, xx = np.ogrid[:height, :width]
    dist2 = (xx - cx) ** 2 + (yy - cy) ** 2

    innerRadius = max(3, int(round(min(width, height) * 0.010)))
    outerRadius = max(innerRadius + 2, int(round(innerRadius * 2.0)))

    innerMask = dist2 <= innerRadius ** 2
    ringMask = (dist2 > innerRadius ** 2) & (dist2 <= outerRadius ** 2)

    result = power.copy()
    validRing = ringMask & np.isfinite(power)

    if np.any(validRing):
        fillValue = float(np.median(power[validRing]))
    else:
        valid = np.isfinite(power)
        fillValue = float(np.median(power[valid])) if np.any(valid) else 0.0

    result[innerMask] = fillValue
    return result


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


def _resizeArrayToGray(
    arr: np.ndarray,
    width: int,
    height: int,
    resample=PILImage.Resampling.BILINEAR,
) -> np.ndarray:
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
        resample,
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