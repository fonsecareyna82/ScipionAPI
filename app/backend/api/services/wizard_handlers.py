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

import importlib
import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


def executeWizardHandler(
    *,
    kind: str,
    wizardClass,
    protocol,
    paramName: str,
    descriptor: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    handler = _HANDLERS.get(kind, executeGenericComputeWizard)
    return handler(
        wizardClass=wizardClass,
        protocol=protocol,
        paramName=paramName,
        descriptor=descriptor or {},
    )


def executeGenericComputeWizard(
    *,
    wizardClass,
    protocol,
    paramName: str,
    descriptor: Optional[Dict[str, Any]] = None,
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