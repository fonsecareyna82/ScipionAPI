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

from typing import Any, Dict, Optional

from .base import (
    buildGenericMethodNames,
    executeByCandidates,
    loadSchedulerLanesFromWizardModule,
    normalizeHandlerResult,
    readProtocolParamValue,
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
    return executeByCandidates(
        wizardClass=wizardClass,
        protocol=protocol,
        paramName=paramName,
        preferredMethodNames=buildGenericMethodNames(paramName),
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
    protocolMethodNames = [
        "getBoxSize",
        "_getBoxSize",
    ]

    for methodName in protocolMethodNames:
        method = getattr(protocol, methodName, None)
        if not callable(method):
            continue

        try:
            result = method()
            return normalizeHandlerResult(paramName, result)
        except Exception:
            continue

    preferred = [
        "_getBoxSize",
        "getBoxSize",
        "estimateBoxSize",
        "calculateBoxSize",
    ]
    preferred.extend(buildGenericMethodNames(paramName))

    return executeByCandidates(
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
    preferred.extend(buildGenericMethodNames(paramName))
    return executeByCandidates(
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
    preferred.extend(buildGenericMethodNames(paramName))
    return executeByCandidates(
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
    lanes = loadSchedulerLanesFromWizardModule(wizardClass)
    if not lanes:
        raise RuntimeError(
            f"No scheduler lanes available for wizard '{wizardClass.__name__}'"
        )

    currentValue = readProtocolParamValue(protocol, paramName)
    selectedLane = currentValue if currentValue in lanes else lanes[0]

    return {
        "paramUpdates": {paramName: str(selectedLane)},
        "message": f"Selected compute lane '{selectedLane}'",
        "availableValues": lanes,
    }