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

from typing import Any, Dict, List, Optional, Tuple

from .ctf import (
    _buildMicrographPreviewImage,
    _buildPsdPreviewImage,
    _coercePositiveFloat,
    _coercePositiveInt,
    _readProtocolFloatValue,
)
from .mask_radius import (
    listMaskRadiusItems,
    resolveMaskRadiusSelection,
    serializeMaskRadiusItem,
)

DOWNSAMPLE_HELP_MESSAGE = (
    "The downsampling factor can be controlled interactively in the web wizard."
)


def executeDownsamplePreviewWizard(
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

    downsampleParam = _resolveDownsampleParamName(
        primaryParam=str(paramName or "").strip(),
        targetParams=list(descriptor.get("targetParams") or []),
    )

    currentDownsample = _readProtocolFloatValue(protocol, downsampleParam, default=1.0)

    action = _normalizeDownsampleAction(wizardInputs)
    selectedIndex = _coercePositiveInt(wizardInputs.get("selectedIndex"), default=1)

    downsample = _coercePositiveFloat(
        wizardInputs.get("downsample"),
        default=currentDownsample,
        minimum=1.0,
    )

    if action == "apply":
        return {
            "paramUpdates": {
                downsampleParam: downsample,
            },
            "message": "Downsample wizard value applied",
            "availableValues": [],
        }

    viewerState = _buildDownsampleViewerState(
        protocol=protocol,
        downsample=downsample,
        selectedIndex=selectedIndex,
        downsampleParam=downsampleParam,
        canvasSize=512,
    )

    return {
        "paramUpdates": {},
        "message": DOWNSAMPLE_HELP_MESSAGE,
        "requiresUserInput": True,
        "availableValues": [],
        "inputSchema": {
            "type": "downsample_preview",
            "paramName": downsampleParam,
            "title": "Wizard",
            "fields": [
                {
                    "name": "downsample",
                    "label": downsampleParam,
                    "kind": "number",
                    "value": float(downsample),
                    "min": float(viewerState.get("downsampleMin") or 1.0),
                    "max": float(viewerState.get("downsampleMax") or 8.0),
                    "step": float(viewerState.get("downsampleStep") or 0.01),
                },
            ],
        },
        "viewerState": viewerState,
    }


def _resolveDownsampleParamName(
    primaryParam: str,
    targetParams: List[str],
) -> str:
    normalized = [str(item).strip() for item in targetParams if str(item).strip()]

    downsampleParam = next(
        (item for item in normalized if "down" in item.lower() or "factor" in item.lower()),
        "downFactor",
    )

    if primaryParam:
        downsampleParam = primaryParam

    return downsampleParam


def _normalizeDownsampleAction(wizardInputs: Dict[str, Any]) -> str:
    if not wizardInputs:
        return "open"

    actionRaw = wizardInputs.get("action")
    if actionRaw is None:
        if "downsample" in wizardInputs:
            return "apply"
        return "open"

    action = str(actionRaw).strip().lower()
    if action in {"open", "preview", "apply"}:
        return action

    return "open"


def _buildDownsampleViewerState(
    *,
    protocol,
    downsample: float,
    selectedIndex: int,
    downsampleParam: str,
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

    resolvedIndex = int(selectedItem["index"]) if selectedItem else 1

    return {
        "items": [serializeMaskRadiusItem(item) for item in items],
        "selectedIndex": resolvedIndex,
        "downsample": float(downsample),
        "downsampleMin": 1.0,
        "downsampleMax": max(8.0, float(downsample) * 2.0),
        "downsampleStep": 0.01,
        "downsampleParam": downsampleParam,
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


def _pilImageToDataUrl(image) -> str:
    from .ctf import _pilImageToDataUrl as _ctfPilImageToDataUrl

    return _ctfPilImageToDataUrl(image)