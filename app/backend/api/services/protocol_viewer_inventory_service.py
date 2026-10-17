"""Read-only descriptors for Scipion's registered viewer classes.

Discovery imports plugin viewer modules through Scipion's Domain registry. Once
registered, this service never instantiates a viewer or evaluates its methods.
Legacy WEB_DJANGO does not imply React compatibility.
"""

from __future__ import annotations

import inspect
from typing import Any, Dict, List, Mapping

from pyworkflow.protocol import Protocol
from pyworkflow.viewer import ProtocolViewer, Viewer


def _static_value(viewer_class: type, name: str, default: Any = None) -> Any:
    """Read declared/inherited class metadata without executing properties."""
    try:
        result = inspect.getattr_static(viewer_class, name, default)
    except (AttributeError, TypeError):
        return default
    return result


def _class_identity(clazz: type) -> str:
    return "%s.%s" % (clazz.__module__, clazz.__qualname__)


def _target_descriptor(target: Any) -> Dict[str, str]:
    if isinstance(target, type):
        return {
            "name": target.__name__,
            "qualifiedName": _class_identity(target),
            "kind": "protocol" if issubclass(target, Protocol) else "object",
        }
    # Some old plugins register names rather than Python classes.
    if isinstance(target, str):
        return {"name": target, "qualifiedName": target, "kind": "unknown"}
    # An unexpected target must not trigger a plugin-defined __str__ or repr.
    return {"name": "<unsupported>", "qualifiedName": "", "kind": "unknown"}


def buildProtocolViewerInventory(registry: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Serialize installed viewer registry metadata without running viewer code.

    This is an inventory, NOT a compatibility decision or an invocation API.
    Duplicate registration aliases for the same class are folded together.
    """
    unique: Dict[str, Dict[str, Any]] = {}

    for registration_name, viewer_class in registry.items():
        if not isinstance(viewer_class, type) or not issubclass(viewer_class, Viewer):
            continue

        identity = _class_identity(viewer_class)
        if identity in unique:
            unique[identity]["registrationNames"].append(str(registration_name))
            continue

        raw_targets = _static_value(viewer_class, "_targets", ())
        targets = (
            [_target_descriptor(target) for target in raw_targets]
            if isinstance(raw_targets, (tuple, list))
            else []
        )
        targets.sort(key=lambda item: (item["qualifiedName"], item["kind"]))

        raw_environments = _static_value(viewer_class, "_environments", ())
        environments = (
            sorted({value for value in raw_environments if isinstance(value, str)})
            if isinstance(raw_environments, (tuple, list, set, frozenset))
            else []
        )

        raw_label = _static_value(viewer_class, "_label", None)
        label = raw_label.strip() if isinstance(raw_label, str) and raw_label.strip() else viewer_class.__name__
        target_kinds = sorted({target["kind"] for target in targets})

        unique[identity] = {
            "id": identity,
            "name": viewer_class.__name__,
            "label": label,
            "plugin": viewer_class.__module__.split(".", 1)[0],
            "module": viewer_class.__module__,
            "registrationNames": [str(registration_name)],
            "viewerKind": "protocol-form" if issubclass(viewer_class, ProtocolViewer) else "simple",
            "targets": targets,
            "targetKinds": target_kinds,
            "environments": environments,
            "legacyDjangoDeclared": "django" in environments,
            # Only dedicated web adapters may subsequently assert actual support.
            "webSupport": "unassessed",
        }

    results = list(unique.values())
    for item in results:
        item["registrationNames"].sort()
    results.sort(key=lambda item: (item["plugin"].lower(), item["name"].lower(), item["id"]))
    return results
