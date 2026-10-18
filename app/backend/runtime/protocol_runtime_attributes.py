"""Scalar attributes that protocols create while they run.

Scipion stores every attribute of a protocol, not only its form parameters.
Plugins rely on that: cryoSPARC keeps its project, workspace and job ids in
attributes such as ``projectName`` or ``currenJob``, and many protocols write
``summaryVar``/``methodsVar``. Continue, the summaries and the viewers read them
back. They are kept in the protocol params under ``RUNTIME_ATTRIBUTES_KEY``.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

import pyworkflow.object as pwobject

RUNTIME_ATTRIBUTES_KEY = "_scipionRuntimeAttributes"

# Protocol attributes the server manages itself (status, timing, execution
# bookkeeping, host and run configuration). They are never stored or restored
# here, so they cannot override that management.
MANAGED_PROTOCOL_ATTRIBUTES = frozenset({
    "status", "initTime", "endTime", "_error", "interactive", "_resultFiles",
    "_needsGPU", "workingDir", "_outputs", "_useOutputList", "expertLevel",
    "lastUpdateTimeStamp", "numberOfMpi", "numberOfThreads", "hostName",
    "hostFullName", "_jobId", "_pid", "_stepsDone", "_cpuTime",
    "_numberOfSteps", "allowHeader", "forceSchedule", "hostConfig", "runMode",
    "runName", "_useQueue", "_queueParams", "_prerequisites", "gpuList",
    "_objComment", "_steps", "_stepsExecutor",
})

_SCALAR_CLASSES = {
    "String": pwobject.String,
    "Integer": pwobject.Integer,
    "Float": pwobject.Float,
    "Boolean": pwobject.Boolean,
}
_MAX_ATTRIBUTES = 200
_MAX_STRING = 65536


def _jsonValue(attribute) -> Any:
    value = attribute.get()
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    return text if len(text) <= _MAX_STRING else None


def outputNames(protocol) -> set:
    """Names of the protocol's outputs, created or possible (an output can be a scalar,
    e.g. crYOLO's ``boxsize``)."""
    names = set()
    try:
        names.update(str(name) for name in (getattr(protocol, "_outputs", None) or []))
    except Exception:
        pass
    try:
        names.update(name for name, _ in protocol.iterOutputAttributes())
    except Exception:
        pass
    # Outputs the protocol declares it may create (Protocol._possibleOutputs).
    possible = getattr(type(protocol), "_possibleOutputs", None)
    if isinstance(possible, dict):
        names.update(str(name) for name in possible)
    return names


def collectRuntimeAttributes(protocol, definitionNames: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """Scalar attributes of ``protocol`` that are neither form params, outputs nor managed.

    Outputs are stored as outputs. Kept here, a scalar output would be restored
    as a plain attribute before the next run, and plugins that create an
    output only when the attribute is missing (``if not hasattr(self,
    "boxsize")``) would never create it again.
    """
    excluded = set(definitionNames) | MANAGED_PROTOCOL_ATTRIBUTES | outputNames(protocol)
    result: Dict[str, Dict[str, Any]] = {}
    try:
        attributes = list(protocol.getAttributes())
    except Exception:
        return result
    for name, attribute in attributes:
        if (len(result) >= _MAX_ATTRIBUTES or not isinstance(name, str)
                or not name.isidentifier() or name in excluded):
            continue
        className = type(attribute).__name__
        if _SCALAR_CLASSES.get(className) is not type(attribute):
            continue
        result[name] = {"class": className, "value": _jsonValue(attribute)}
    return result


def applyRuntimeAttributes(protocol, stored: Optional[Dict[str, Any]]) -> None:
    """Restore stored scalar attributes; form params, outputs and managed ones are untouched."""
    if not isinstance(stored, dict):
        return
    outputs = outputNames(protocol)
    for name, entry in stored.items():
        if (not isinstance(name, str) or not name.isidentifier()
                or name in MANAGED_PROTOCOL_ATTRIBUTES or name in outputs
                or not isinstance(entry, dict)):
            continue
        scalarClass = _SCALAR_CLASSES.get(entry.get("class"))
        if scalarClass is None:
            continue
        try:
            if protocol.getParam(name) is not None:
                continue
        except Exception:
            pass
        value = entry.get("value")
        if value is not None and not isinstance(value, (str, bool, int, float)):
            continue
        current = getattr(protocol, name, None)
        try:
            if type(current) is scalarClass:
                current.set(value)
            elif current is None:
                setattr(protocol, name, scalarClass(value))
        except Exception:
            continue
