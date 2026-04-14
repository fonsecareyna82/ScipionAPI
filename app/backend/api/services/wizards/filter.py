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

import io
import math
from typing import Any, Dict, List, Optional, Tuple

import base64
import numpy as np
from PIL import Image as PILImage

from .mask_radius import (
    buildFallbackPreviewBase,
    getMaskRadiusSamplingRate,
    listMaskRadiusItems,
    openImageSource,
    resolveMaskRadiusSelection,
    serializeMaskRadiusItem,
)

FILTER_HELP_MESSAGE = (
    "The Fourier filter parameters can be controlled interactively in the web wizard."
)

GAUSSIAN_HELP_MESSAGE = (
    "The Gaussian filter parameter can be edited in the web wizard."
)

FILTER_PREVIEW_CANVAS_SIZE = 512
FILTER_WORK_SIZE = 512


def executeFilterPreviewWizard(
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

    action = _normalizeWizardAction(wizardInputs)
    selectedIndex = _coercePositiveInt(wizardInputs.get("selectedIndex"), default=1)

    lowParam, highParam, decayParam = _resolveFilterParamNames(
        protocol=protocol,
        primaryParam=str(paramName or "").strip(),
        targetParams=list(descriptor.get("targetParams") or []),
    )

    lowValue = _coerceFloat(
        wizardInputs.get("lowFreq", wizardInputs.get(lowParam)),
        default=_readProtocolFloatValue(protocol, lowParam, default=0.0),
        minimum=0.0,
    )
    highValue = _coerceFloat(
        wizardInputs.get("highFreq", wizardInputs.get(highParam)),
        default=_readProtocolFloatValue(protocol, highParam, default=0.0),
        minimum=0.0,
    )
    decayValue = _coerceFloat(
        wizardInputs.get("decay", wizardInputs.get(decayParam)),
        default=_readProtocolFloatValue(protocol, decayParam, default=0.0),
        minimum=0.0,
    )

    if action == "apply":
        return {
            "paramUpdates": {
                lowParam: lowValue,
                highParam: highValue,
                decayParam: decayValue,
            },
            "message": "Filter wizard values applied",
            "availableValues": [],
        }

    viewerState = _buildFilterViewerState(
        protocol=protocol,
        selectedIndex=selectedIndex,
        lowValue=lowValue,
        highValue=highValue,
        decayValue=decayValue,
        lowParam=lowParam,
        highParam=highParam,
        decayParam=decayParam,
        canvasSize=FILTER_PREVIEW_CANVAS_SIZE,
    )

    return {
        "paramUpdates": {},
        "message": FILTER_HELP_MESSAGE,
        "requiresUserInput": True,
        "availableValues": [],
        "inputSchema": {
            "type": "filter_preview",
            "paramName": lowParam,
            "title": "Wizard",
            "fields": [
                {
                    "name": "lowFreq",
                    "label": lowParam,
                    "kind": "number",
                    "value": float(lowValue),
                    "min": float(viewerState.get("lowFreqMin") or 0.0),
                    "max": float(viewerState.get("lowFreqMax") or 1.0),
                    "step": float(viewerState.get("freqStep") or 0.01),
                },
                {
                    "name": "highFreq",
                    "label": highParam,
                    "kind": "number",
                    "value": float(highValue),
                    "min": float(viewerState.get("highFreqMin") or 0.0),
                    "max": float(viewerState.get("highFreqMax") or 1.0),
                    "step": float(viewerState.get("freqStep") or 0.01),
                },
                {
                    "name": "decay",
                    "label": decayParam,
                    "kind": "number",
                    "value": float(decayValue),
                    "min": float(viewerState.get("decayMin") or 0.0),
                    "max": float(viewerState.get("decayMax") or 1.0),
                    "step": float(viewerState.get("freqStep") or 0.01),
                },
            ],
        },
        "viewerState": viewerState,
    }


def executeGaussianPreviewWizard(
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

    action = _normalizeWizardAction(wizardInputs)
    sigmaParam = _resolveGaussianParamName(
        primaryParam=str(paramName or "").strip(),
        targetParams=list(descriptor.get("targetParams") or []),
    )

    sigmaValue = _coerceFloat(
        wizardInputs.get("sigma", wizardInputs.get(sigmaParam)),
        default=_readProtocolFloatValue(protocol, sigmaParam, default=0.0),
        minimum=0.0,
    )

    if action == "apply":
        return {
            "paramUpdates": {
                sigmaParam: sigmaValue,
            },
            "message": "Gaussian wizard value applied",
            "availableValues": [],
        }

    sigmaMax = max(1.0, float(sigmaValue) * 2.0, 0.5)

    return {
        "paramUpdates": {},
        "message": GAUSSIAN_HELP_MESSAGE,
        "requiresUserInput": True,
        "availableValues": [],
        "inputSchema": {
            "type": "gaussian_preview",
            "paramName": sigmaParam,
            "title": "Wizard",
            "fields": [
                {
                    "name": "sigma",
                    "label": sigmaParam,
                    "kind": "number",
                    "value": float(sigmaValue),
                    "min": 0.0,
                    "max": float(sigmaMax),
                    "step": 0.01,
                },
            ],
        },
    }


def _buildFilterViewerState(
    *,
    protocol,
    selectedIndex: int,
    lowValue: float,
    highValue: float,
    decayValue: float,
    lowParam: str,
    highParam: str,
    decayParam: str,
    canvasSize: int = FILTER_PREVIEW_CANVAS_SIZE,
) -> Dict[str, Any]:
    items = listMaskRadiusItems(protocol)
    selectedItem = resolveMaskRadiusSelection(items, selectedIndex)

    samplingRate = getMaskRadiusSamplingRate(protocol)
    freqInAngstrom = _readProtocolBoolValue(protocol, "freqInAngstrom", default=False)
    filterMode = _readProtocolRawValue(protocol, "filterModeFourier")

    originalImage, sourceWidth, sourceHeight = _buildOriginalPreviewImage(
        selectedItem=selectedItem,
        canvasSize=canvasSize,
    )
    filteredImage = _buildFilteredPreviewImage(
        selectedItem=selectedItem,
        lowValue=lowValue,
        highValue=highValue,
        decayValue=decayValue,
        samplingRate=samplingRate,
        freqInAngstrom=freqInAngstrom,
        filterMode=filterMode,
        canvasSize=canvasSize,
    )

    freqMax = _resolveFrequencyMax(
        freqInAngstrom=freqInAngstrom,
        lowValue=lowValue,
        highValue=highValue,
        decayValue=decayValue,
    )
    freqStep = 0.1 if freqInAngstrom else 0.01

    resolvedIndex = int(selectedItem["index"]) if selectedItem else 1

    return {
        "items": [serializeMaskRadiusItem(item) for item in items],
        "selectedIndex": resolvedIndex,
        "lowFreq": float(lowValue),
        "lowFreqMin": 0.0,
        "lowFreqMax": float(freqMax),
        "highFreq": float(highValue),
        "highFreqMin": 0.0,
        "highFreqMax": float(freqMax),
        "decay": float(decayValue),
        "decayMin": 0.0,
        "decayMax": float(freqMax),
        "freqStep": float(freqStep),
        "samplingRate": samplingRate,
        "freqInAngstrom": bool(freqInAngstrom),
        "unitLabel": "Å" if freqInAngstrom else "digital frequency",
        "filterMode": str(filterMode) if filterMode not in (None, "") else "",
        "lowFreqParam": lowParam,
        "highFreqParam": highParam,
        "decayParam": decayParam,
        "originalPreview": {
            "imageUrl": _pilImageToDataUrl(originalImage),
            "width": originalImage.width,
            "height": originalImage.height,
            "caption": "Image",
            "sourceWidth": int(sourceWidth),
            "sourceHeight": int(sourceHeight),
        },
        "filteredPreview": {
            "imageUrl": _pilImageToDataUrl(filteredImage),
            "width": filteredImage.width,
            "height": filteredImage.height,
            "caption": "Filtered",
            "sourceWidth": int(sourceWidth),
            "sourceHeight": int(sourceHeight),
        },
        "preview": {
            "imageUrl": _pilImageToDataUrl(filteredImage),
            "width": filteredImage.width,
            "height": filteredImage.height,
            "caption": "Filtered",
            "sourceWidth": int(sourceWidth),
            "sourceHeight": int(sourceHeight),
        },
    }


def _resolveFilterParamNames(
    *,
    protocol,
    primaryParam: str,
    targetParams: List[str],
) -> Tuple[str, str, str]:
    normalized = [str(item).strip() for item in targetParams if str(item).strip()]
    freqInAngstrom = _readProtocolBoolValue(protocol, "freqInAngstrom", default=False)

    if freqInAngstrom:
        defaults = ("lowFreqA", "highFreqA", "freqDecayA")
    else:
        defaults = ("lowFreqDig", "highFreqDig", "freqDecayDig")

    lowParam = next((item for item in normalized if item == defaults[0]), defaults[0])
    highParam = next((item for item in normalized if item == defaults[1]), defaults[1])
    decayParam = next((item for item in normalized if item == defaults[2]), defaults[2])

    if primaryParam:
        lower = primaryParam.lower()
        if "low" in lower:
            lowParam = primaryParam
        elif "high" in lower:
            highParam = primaryParam
        elif "decay" in lower:
            decayParam = primaryParam

    return lowParam, highParam, decayParam


def _resolveGaussianParamName(
    *,
    primaryParam: str,
    targetParams: List[str],
) -> str:
    normalized = [str(item).strip() for item in targetParams if str(item).strip()]
    if primaryParam:
        return primaryParam
    if normalized:
        return normalized[0]
    return "freqSigma"


def _normalizeWizardAction(wizardInputs: Dict[str, Any]) -> str:
    if not wizardInputs:
        return "open"

    actionRaw = wizardInputs.get("action")
    if actionRaw is None:
        return "apply"

    action = str(actionRaw).strip().lower()
    if action in {"open", "preview", "apply"}:
        return action

    return "open"


def _resolveFrequencyMax(
    *,
    freqInAngstrom: bool,
    lowValue: float,
    highValue: float,
    decayValue: float,
) -> float:
    if freqInAngstrom:
        return max(
            20.0,
            float(lowValue) * 1.5,
            float(highValue) * 1.5,
            float(decayValue) * 1.5,
        )

    return max(
        0.5,
        float(lowValue) * 1.25,
        float(highValue) * 1.25,
        float(decayValue) * 1.25,
    )


def _readProtocolRawValue(protocol, paramName: str):
    if not paramName:
        return None

    protVar = getattr(protocol, paramName, None)
    if protVar is None:
        return None

    getter = getattr(protVar, "get", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            return protVar

    return protVar


def _readProtocolFloatValue(protocol, paramName: str, default: float = 0.0) -> float:
    value = _readProtocolRawValue(protocol, paramName)

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
    value = _readProtocolRawValue(protocol, paramName)

    if isinstance(value, bool):
        return value

    if value in (None, ""):
        return bool(default)

    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _coerceFloat(value: Any, default: float, minimum: float = 0.0) -> float:
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


def _buildOriginalPreviewImage(
    *,
    selectedItem: Optional[Dict[str, Any]],
    canvasSize: int = FILTER_PREVIEW_CANVAS_SIZE,
) -> Tuple[PILImage.Image, int, int]:
    source = _extractSelectedSource(selectedItem)
    if source is None:
        fallback = buildFallbackPreviewBase(canvasSize=canvasSize).convert("RGB")
        return fallback, fallback.width, fallback.height

    filePath, sourceIndex = source
    cachedPng = _build_cached_original_preview(filePath, sourceIndex, canvasSize)
    image = _pngBytesToPilImage(cachedPng)

    arr = _load_cached_array(filePath, sourceIndex)
    if arr is None:
        return image, image.width, image.height

    return image, int(arr.shape[1]), int(arr.shape[0])


def _buildFilteredPreviewImage(
    *,
    selectedItem: Optional[Dict[str, Any]],
    lowValue: float,
    highValue: float,
    decayValue: float,
    samplingRate: Optional[float],
    freqInAngstrom: bool,
    filterMode: Any,
    canvasSize: int = FILTER_PREVIEW_CANVAS_SIZE,
) -> PILImage.Image:
    source = _extractSelectedSource(selectedItem)
    if source is None:
        return buildFallbackPreviewBase(canvasSize=canvasSize).convert("RGB")

    filePath, sourceIndex = source
    lowKey = int(round(float(lowValue) * 1000.0))
    highKey = int(round(float(highValue) * 1000.0))
    decayKey = int(round(float(decayValue) * 1000.0))
    samplingKey = int(round(float(samplingRate or 0.0) * 1000.0))
    modeKey = str(filterMode or "")

    cachedPng = _build_cached_filtered_preview(
        filePath=filePath,
        sourceIndex=sourceIndex,
        canvasSize=canvasSize,
        lowKey=lowKey,
        highKey=highKey,
        decayKey=decayKey,
        samplingKey=samplingKey,
        freqInAngstrom=freqInAngstrom,
        modeKey=modeKey,
    )
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
def _load_cached_array(filePath: str, sourceIndex: int) -> Optional[np.ndarray]:
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


@lru_cache(maxsize=128)
def _load_cached_preview_base_array(filePath: str, sourceIndex: int) -> Optional[np.ndarray]:
    arr = _load_cached_array(filePath, sourceIndex)
    if arr is None:
        return None

    valid = arr[np.isfinite(arr)]
    if valid.size == 0:
        return None

    low = float(np.percentile(valid, 0.5))
    high = float(np.percentile(valid, 99.5))

    if high <= low:
        low = float(valid.min())
        high = float(valid.max())

    if high <= low:
        norm = np.zeros_like(arr, dtype=np.uint8)
    else:
        clipped = np.clip(arr, low, high)
        norm = ((clipped - low) / (high - low + 1e-12) * 255.0).astype(np.uint8)

    return norm.astype(np.float32, copy=False)


def _buildOriginalPreviewImage(
    *,
    selectedItem: Optional[Dict[str, Any]],
    canvasSize: int = FILTER_PREVIEW_CANVAS_SIZE,
) -> Tuple[PILImage.Image, int, int]:
    source = _extractSelectedSource(selectedItem)
    if source is None:
        fallback = buildFallbackPreviewBase(canvasSize=canvasSize).convert("RGB")
        return fallback, fallback.width, fallback.height

    filePath, sourceIndex = source
    baseArr = _load_cached_preview_base_array(filePath, sourceIndex)
    if baseArr is None:
        fallback = buildFallbackPreviewBase(canvasSize=canvasSize).convert("RGB")
        return fallback, fallback.width, fallback.height

    image = PILImage.fromarray(baseArr.astype(np.uint8), mode="L").convert("RGB")
    image = _fit_image_to_canvas(image, canvasSize)
    return image, int(baseArr.shape[1]), int(baseArr.shape[0])


@lru_cache(maxsize=512)
def _build_cached_filtered_preview(
    *,
    filePath: str,
    sourceIndex: int,
    canvasSize: int,
    lowKey: int,
    highKey: int,
    decayKey: int,
    samplingKey: int,
    freqInAngstrom: bool,
    modeKey: str,
) -> bytes:
    baseArr = _load_cached_preview_base_array(filePath, sourceIndex)
    if baseArr is None:
        image = buildFallbackPreviewBase(canvasSize=canvasSize).convert("RGB")
        return _pilImageToPngBytes(image)

    lowValue = float(lowKey) / 1000.0
    highValue = float(highKey) / 1000.0
    decayValue = float(decayKey) / 1000.0
    samplingRate = float(samplingKey) / 1000.0 if samplingKey > 0 else None

    filtered = _apply_fourier_filter(
        arr=baseArr,
        lowValue=lowValue,
        highValue=highValue,
        decayValue=decayValue,
        samplingRate=samplingRate,
        freqInAngstrom=freqInAngstrom,
        modeKey=modeKey,
    )

    image = _arrayToPreviewImage(
        filtered,
        canvasSize=canvasSize,
        lowPercentile=0.2,
        highPercentile=99.8,
    )
    return _pilImageToPngBytes(image)


def _apply_fourier_filter(
    *,
    arr: np.ndarray,
    lowValue: float,
    highValue: float,
    decayValue: float,
    samplingRate: Optional[float],
    freqInAngstrom: bool,
    modeKey: str,
) -> np.ndarray:
    work = _prepare_filter_input(arr, targetSize=FILTER_WORK_SIZE)
    work = work.astype(np.float32, copy=False)
    work -= float(np.mean(work))

    std = float(np.std(work))
    if std > 1e-6:
        work /= std

    radialFreq = _build_shifted_radial_frequency_grid(work.shape[0], work.shape[1])

    lowDigital = _to_digital_frequency(
        value=lowValue,
        samplingRate=samplingRate,
        freqInAngstrom=freqInAngstrom,
    )
    highDigital = _to_digital_frequency(
        value=highValue,
        samplingRate=samplingRate,
        freqInAngstrom=freqInAngstrom,
    )

    lowCut = min(lowDigital, highDigital)
    highCut = max(lowDigital, highDigital)

    if freqInAngstrom:
        sigma = _resolution_decay_to_digital_sigma(
            cutoffValue=max(lowValue, highValue),
            decayValue=decayValue,
            samplingRate=samplingRate,
        )
    else:
        sigma = max(0.001, min(0.10, decayValue))

    mode = _normalize_filter_mode(modeKey)

    if mode == "low_pass":
        mask = 1.0 / (1.0 + np.exp((radialFreq - highCut) / sigma))
    elif mode == "high_pass":
        mask = 1.0 / (1.0 + np.exp((lowCut - radialFreq) / sigma))
    else:
        lowMask = 1.0 / (1.0 + np.exp((lowCut - radialFreq) / sigma))
        highMask = 1.0 / (1.0 + np.exp((radialFreq - highCut) / sigma))
        mask = lowMask * highMask

    fft = np.fft.fftshift(np.fft.fft2(work))
    filteredFft = fft * mask.astype(np.complex64)
    filtered = np.real(np.fft.ifft2(np.fft.ifftshift(filteredFft))).astype(np.float32)

    return filtered


def _prepare_filter_input(arr: np.ndarray, targetSize: int) -> np.ndarray:
    arr = np.asarray(arr, dtype=np.float32)
    arr = _center_crop_square(arr)

    if arr.shape[0] > targetSize:
        arr = _resize_array_to_gray(arr, targetSize, targetSize)
    elif arr.shape[0] < targetSize:
        arr = _resize_array_to_gray(arr, targetSize, targetSize)

    return arr

def _build_shifted_radial_frequency_grid(height: int, width: int) -> np.ndarray:
    fy = np.fft.fftfreq(height)
    fx = np.fft.fftfreq(width)
    gridX, gridY = np.meshgrid(fx, fy)
    radial = np.sqrt(gridX ** 2 + gridY ** 2)
    return np.fft.fftshift(radial).astype(np.float32, copy=False)


def _resolution_decay_to_digital_sigma(
    *,
    cutoffValue: float,
    decayValue: float,
    samplingRate: Optional[float],
) -> float:
    if cutoffValue <= 0 or decayValue <= 0 or not samplingRate or samplingRate <= 0:
        return 0.01

    baseFreq = float(np.clip(float(samplingRate) / float(cutoffValue), 0.0, 0.5))
    shiftedCutoff = float(cutoffValue) + float(decayValue)
    shiftedFreq = float(np.clip(float(samplingRate) / float(shiftedCutoff), 0.0, 0.5))

    sigma = abs(baseFreq - shiftedFreq)
    return float(np.clip(sigma, 0.001, 0.10))

def _to_digital_frequency(
    *,
    value: float,
    samplingRate: Optional[float],
    freqInAngstrom: bool,
) -> float:
    if value <= 0:
        return 0.0

    if freqInAngstrom:
        if not samplingRate or samplingRate <= 0:
            return 0.0
        return float(np.clip(float(samplingRate) / float(value), 0.0, 0.5))

    return float(np.clip(value, 0.0, 0.5))


def _to_decay_frequency(
    *,
    value: float,
    samplingRate: Optional[float],
    freqInAngstrom: bool,
) -> float:
    if value <= 0:
        return 0.01

    if freqInAngstrom:
        if not samplingRate or samplingRate <= 0:
            return 0.01
        return float(np.clip(float(samplingRate) / float(value), 0.002, 0.25))

    return float(np.clip(value, 0.002, 0.25))


def _normalize_filter_mode(modeKey: str) -> str:
    raw = str(modeKey or "").strip().lower()

    if raw in {"0", "low", "lowpass", "low_pass"}:
        return "low_pass"

    if raw in {"1", "high", "highpass", "high_pass"}:
        return "high_pass"

    if raw in {"2", "band", "bandpass", "band_pass"}:
        return "band_pass"

    if "low" in raw and "band" not in raw:
        return "low_pass"

    if "high" in raw and "band" not in raw:
        return "high_pass"

    return "band_pass"


def _arrayToPreviewImage(
    arr: np.ndarray,
    canvasSize: int,
    lowPercentile: float = 1.0,
    highPercentile: float = 99.0,
) -> PILImage.Image:
    arr = np.asarray(arr, dtype=np.float32)
    finiteMask = np.isfinite(arr)

    if not finiteMask.any():
        return buildFallbackPreviewBase(canvasSize=canvasSize).convert("RGB")

    valid = arr[finiteMask]
    low = float(np.percentile(valid, lowPercentile))
    high = float(np.percentile(valid, highPercentile))

    if high <= low:
        low = float(valid.min())
        high = float(valid.max())

    if high <= low:
        norm = np.zeros_like(arr, dtype=np.uint8)
    else:
        clipped = np.clip(arr, low, high)
        norm = ((clipped - low) / (high - low + 1e-12) * 255.0).astype(np.uint8)

    image = PILImage.fromarray(norm, mode="L").convert("RGB")
    return _fit_image_to_canvas(image, canvasSize)


def _center_crop_square(arr: np.ndarray) -> np.ndarray:
    height, width = arr.shape[:2]
    size = min(height, width)

    offsetY = max(0, (height - size) // 2)
    offsetX = max(0, (width - size) // 2)

    return arr[offsetY:offsetY + size, offsetX:offsetX + size]


def _resize_array_to_gray(arr: np.ndarray, width: int, height: int) -> np.ndarray:
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


def _fit_image_to_canvas(image: PILImage.Image, canvasSize: int) -> PILImage.Image:
    fitScale = min(canvasSize / float(image.width), canvasSize / float(image.height))
    previewW = max(1, int(round(image.width * fitScale)))
    previewH = max(1, int(round(image.height * fitScale)))

    resized = image.resize((previewW, previewH), PILImage.Resampling.BILINEAR)

    canvas = PILImage.new("RGB", (canvasSize, canvasSize), (205, 205, 205))
    offsetX = (canvasSize - previewW) // 2
    offsetY = (canvasSize - previewH) // 2
    canvas.paste(resized, (offsetX, offsetY))
    return canvas


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