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
from typing import Any, Dict, List, Sequence

logger = logging.getLogger(__name__)


def executeByCandidates(
    *,
    wizardClass,
    protocol,
    paramName: str,
    preferredMethodNames: Sequence[str],
) -> Dict[str, Any]:
    instance = instantiateWizard(wizardClass)
    target = instance if instance is not None else wizardClass

    attempted: List[str] = []

    for methodName in uniqueStrings(preferredMethodNames):
        method = getattr(target, methodName, None)
        if not callable(method):
            continue

        for args in buildArgumentCandidates(protocol, paramName):
            attempted.append(f"{wizardClass.__name__}.{methodName}{args}")
            try:
                result = method(*args)
                return normalizeHandlerResult(paramName, result)
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


def instantiateWizard(wizardClass):
    try:
        return wizardClass()
    except Exception:
        return None


def buildArgumentCandidates(protocol, paramName: str):
    return [
        (protocol, paramName),
        (protocol,),
        (),
    ]


def buildGenericMethodNames(paramName: str) -> List[str]:
    suffix = toPascalCase(paramName)

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

    return uniqueStrings(names)


def toPascalCase(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return raw[0].upper() + raw[1:]


def uniqueStrings(items: Sequence[str]) -> List[str]:
    seen = set()
    result: List[str] = []

    for item in items:
        token = str(item or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        result.append(token)

    return result


def _coerceWizardValue(rawValue: Any) -> Any:
    if rawValue is None:
        return None

    if isinstance(rawValue, (str, int, float, bool)):
        return rawValue

    if isinstance(rawValue, dict):
        return {
            str(key): _coerceWizardValue(value)
            for key, value in rawValue.items()
        }

    if isinstance(rawValue, list):
        return [_coerceWizardValue(item) for item in rawValue]

    if isinstance(rawValue, tuple):
        return tuple(_coerceWizardValue(item) for item in rawValue)

    for getterName in ("get", "getObjValue", "getValue"):
        getter = getattr(rawValue, getterName, None)
        if not callable(getter):
            continue

        try:
            value = getter()
            if value is rawValue:
                continue
            return _coerceWizardValue(value)
        except Exception:
            continue

    try:
        return int(rawValue)
    except Exception:
        pass

    try:
        return float(rawValue)
    except Exception:
        pass

    return rawValue


def normalizeHandlerResult(paramName: str, rawResult: Any) -> Dict[str, Any]:
    if rawResult is None:
        raise RuntimeError("Wizard returned no result")

    rawResult = _coerceWizardValue(rawResult)

    if isinstance(rawResult, dict):
        if isinstance(rawResult.get("paramUpdates"), dict):
            normalized = dict(rawResult)
            normalized["paramUpdates"] = _coerceWizardValue(rawResult["paramUpdates"])
            return normalized

        if paramName in rawResult:
            return {"paramUpdates": {paramName: _coerceWizardValue(rawResult[paramName])}}

        if len(rawResult) == 1:
            onlyKey = next(iter(rawResult.keys()))
            return {"paramUpdates": {str(onlyKey): _coerceWizardValue(rawResult[onlyKey])}}

        return {"paramUpdates": _coerceWizardValue(rawResult)}

    if isinstance(rawResult, (list, tuple)):
        if len(rawResult) == 1:
            return {"paramUpdates": {paramName: _coerceWizardValue(rawResult[0])}}

        if len(rawResult) == 2 and isinstance(rawResult[0], str):
            return {"paramUpdates": {rawResult[0]: _coerceWizardValue(rawResult[1])}}

    return {"paramUpdates": {paramName: _coerceWizardValue(rawResult)}}


def loadSchedulerLanesFromWizardModule(wizardClass) -> List[str]:
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
            lanes = extractLaneValues(raw)
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


def extractLaneValues(raw: Any) -> List[str]:
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
            return extractLaneValues(items[0])

        values: List[str] = []
        for item in items:
            if isinstance(item, (list, tuple, set, dict)):
                nested = extractLaneValues(item)
                if nested:
                    values.extend(nested)
                    continue

            token = str(item).strip()
            if token:
                values.append(token)

        return uniqueStrings(values)

    return []


def readProtocolParamValue(protocol, paramName: str) -> str:
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


def readProtocolNumericValue(protocol, paramName: str, default: int = 0) -> int:
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