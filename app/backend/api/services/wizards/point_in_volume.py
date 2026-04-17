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

import math
from typing import Any, Dict, Optional, Tuple

import numpy as np
from fastapi import HTTPException, status

from app.backend.utils.volume_utils import readVolumeArray3d


POINT_IN_VOLUME_HELP_MESSAGE = (
    "Select the new center inside the input volume and apply the coordinates."
)


def executePointInVolumeWizard(
    *,
    wizardClass,
    protocol,
    paramName: str,
    descriptor: Optional[Dict[str, Any]] = None,
    wizardInputs: Optional[Dict[str, Any]] = None,
    currentProject=None,
    projectId: Optional[int] = None,
) -> Dict[str, Any]:
    wizardInputs = wizardInputs or {}
    action = _normalizePointInVolumeAction(wizardInputs)

    volumePath = _resolveInputVolumePath(protocol)
    volumeData, _props = readVolumeArray3d(volumePath)

    if volumeData is None or volumeData.ndim != 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Input volume is not a valid 3D map",
        )

    volumeData = np.asarray(volumeData, dtype=np.float32)
    dimsZYX = [int(volumeData.shape[0]), int(volumeData.shape[1]), int(volumeData.shape[2])]

    if action == "apply":
        point = _resolveAppliedPoint(wizardInputs, dimsZYX)
        return {
            "paramUpdates": {
                "xin": float(point["x"]),
                "yin": float(point["y"]),
                "zin": float(point["z"]),
            },
            "message": "Point in volume applied",
            "availableValues": [],
        }

    currentPoint = {
        "x": _readProtocolFloatValue(protocol, "xin", default=0.0),
        "y": _readProtocolFloatValue(protocol, "yin", default=0.0),
        "z": _readProtocolFloatValue(protocol, "zin", default=0.0),
    }
    currentVoxel = _centerCoordsToVoxel(currentPoint, dimsZYX)

    previewVolume = _downsampleVolumePreviewUint8(volumeData, maxDim=64)

    return {
        "paramUpdates": {},
        "message": POINT_IN_VOLUME_HELP_MESSAGE,
        "requiresUserInput": True,
        "availableValues": [],
        "inputSchema": {
            "type": "point_in_volume",
            "paramName": paramName,
            "title": "Wizard",
            "fields": [],
        },
        "viewerState": {
            "dims": dimsZYX,
            "previewDims": [
                int(previewVolume.shape[0]),
                int(previewVolume.shape[1]),
                int(previewVolume.shape[2]),
            ],
            "previewValues": previewVolume.ravel(order="C").astype(np.uint8).tolist(),
            "axisOrder": ["z", "y", "x"],
            "point": currentPoint,
            "pointVoxel": currentVoxel,
            "bounds": {
                "xMin": -0.5 * float(dimsZYX[2]),
                "xMax": 0.5 * float(dimsZYX[2]),
                "yMin": -0.5 * float(dimsZYX[1]),
                "yMax": 0.5 * float(dimsZYX[1]),
                "zMin": -0.5 * float(dimsZYX[0]),
                "zMax": 0.5 * float(dimsZYX[0]),
            },
        },
    }


def _normalizePointInVolumeAction(wizardInputs: Dict[str, Any]) -> str:
    if not wizardInputs:
        return "open"

    actionRaw = wizardInputs.get("action")
    if actionRaw is None:
        if any(
            key in wizardInputs
            for key in ("x", "y", "z", "point", "pointVoxel", "voxelX", "voxelY", "voxelZ")
        ):
            return "apply"
        return "open"

    action = str(actionRaw).strip().lower()
    if action in {"open", "preview", "apply"}:
        return action

    return "open"


def _resolveInputVolumePath(protocol) -> str:
    inputVolHolder = getattr(protocol, "inputVol", None)
    if inputVolHolder is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This wizard requires protocol.inputVol",
        )

    getFn = getattr(inputVolHolder, "get", None)
    volumeObj = getFn() if callable(getFn) else inputVolHolder
    if volumeObj is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Select an input volume first",
        )

    fileNameFn = getattr(volumeObj, "getFileName", None)
    if not callable(fileNameFn):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Input volume does not expose getFileName()",
        )

    volumePath = fileNameFn()
    if not volumePath:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Input volume file not found",
        )

    return str(volumePath)


def _readProtocolFloatValue(protocol, paramName: str, default: float = 0.0) -> float:
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
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError
        return parsed
    except Exception:
        return float(default)


def _coerceFloat(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return float(default)

    try:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError
        return parsed
    except Exception:
        return float(default)


def _centerCoordsToVoxel(point: Dict[str, float], dimsZYX) -> Dict[str, float]:
    zDim, yDim, xDim = dimsZYX

    voxelX = float(point["x"]) + 0.5 * float(xDim)
    voxelY = float(point["y"]) + 0.5 * float(yDim)
    voxelZ = float(point["z"]) + 0.5 * float(zDim)

    voxelX = min(max(voxelX, 0.0), float(xDim - 1))
    voxelY = min(max(voxelY, 0.0), float(yDim - 1))
    voxelZ = min(max(voxelZ, 0.0), float(zDim - 1))

    return {
        "x": voxelX,
        "y": voxelY,
        "z": voxelZ,
    }


def _voxelCoordsToCenter(pointVoxel: Dict[str, float], dimsZYX) -> Dict[str, float]:
    zDim, yDim, xDim = dimsZYX

    voxelX = min(max(float(pointVoxel["x"]), 0.0), float(xDim - 1))
    voxelY = min(max(float(pointVoxel["y"]), 0.0), float(yDim - 1))
    voxelZ = min(max(float(pointVoxel["z"]), 0.0), float(zDim - 1))

    return {
        "x": voxelX - 0.5 * float(xDim),
        "y": voxelY - 0.5 * float(yDim),
        "z": voxelZ - 0.5 * float(zDim),
    }


def _resolveAppliedPoint(wizardInputs: Dict[str, Any], dimsZYX) -> Dict[str, float]:
    point = wizardInputs.get("point")
    if isinstance(point, dict):
        if all(axis in point for axis in ("x", "y", "z")):
            return {
                "x": _coerceFloat(point.get("x"), 0.0),
                "y": _coerceFloat(point.get("y"), 0.0),
                "z": _coerceFloat(point.get("z"), 0.0),
            }

    if all(key in wizardInputs for key in ("x", "y", "z")):
        return {
            "x": _coerceFloat(wizardInputs.get("x"), 0.0),
            "y": _coerceFloat(wizardInputs.get("y"), 0.0),
            "z": _coerceFloat(wizardInputs.get("z"), 0.0),
        }

    pointVoxel = wizardInputs.get("pointVoxel")
    if isinstance(pointVoxel, dict) and all(axis in pointVoxel for axis in ("x", "y", "z")):
        return _voxelCoordsToCenter(pointVoxel, dimsZYX)

    if all(key in wizardInputs for key in ("voxelX", "voxelY", "voxelZ")):
        return _voxelCoordsToCenter(
            {
                "x": _coerceFloat(wizardInputs.get("voxelX"), 0.0),
                "y": _coerceFloat(wizardInputs.get("voxelY"), 0.0),
                "z": _coerceFloat(wizardInputs.get("voxelZ"), 0.0),
            },
            dimsZYX,
        )

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Missing point coordinates for point_in_volume wizard",
    )


def _downsampleVolumePreviewUint8(volumeData: np.ndarray, maxDim: int = 64) -> np.ndarray:
    volumeData = np.asarray(volumeData, dtype=np.float32)

    if volumeData.ndim != 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid volume preview shape",
        )

    preview = _binVolumeToMaxDim(volumeData, maxDim=maxDim)

    finiteMask = np.isfinite(preview)
    if not finiteMask.any():
        return np.zeros(preview.shape, dtype=np.uint8)

    valid = preview[finiteMask]
    low = float(np.percentile(valid, 1.0))
    high = float(np.percentile(valid, 99.0))

    if high <= low:
        low = float(valid.min())
        high = float(valid.max())

    if high <= low:
        return np.zeros(preview.shape, dtype=np.uint8)

    clipped = np.clip(preview, low, high)
    norm = (clipped - low) / (high - low + 1e-12)
    return (255.0 * norm).astype(np.uint8)


def _binVolumeToMaxDim(volumeData: np.ndarray, maxDim: int = 64) -> np.ndarray:
    zDim, yDim, xDim = volumeData.shape
    maxCurrentDim = max(zDim, yDim, xDim)

    if maxCurrentDim <= maxDim:
        return volumeData.astype(np.float32, copy=False)

    factor = int(np.ceil(float(maxCurrentDim) / float(maxDim)))
    if factor <= 1:
        return volumeData.astype(np.float32, copy=False)

    zCrop = (zDim // factor) * factor
    yCrop = (yDim // factor) * factor
    xCrop = (xDim // factor) * factor

    if min(zCrop, yCrop, xCrop) <= 0:
        return volumeData.astype(np.float32, copy=False)

    cropped = volumeData[:zCrop, :yCrop, :xCrop]
    binned = cropped.reshape(
        zCrop // factor, factor,
        yCrop // factor, factor,
        xCrop // factor, factor,
    ).mean(axis=(1, 3, 5))

    return binned.astype(np.float32, copy=False)