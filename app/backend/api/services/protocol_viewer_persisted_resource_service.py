"""Resolve one Scipion Set output to advisory, read-only web-viewer metadata.

This is a narrow internal building block, not an action executor or HTTP API.
The caller MUST authorize the user/project before calling it. Neither a valid
output nor a supported web viewer authorizes a ProtocolViewer callback.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Dict

_OUTPUT_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}\Z")

# These are exact, already supported branches of AnalyzeOutputDialog, not
# plugin-specific assumptions or a declaration that a callback can execute.
_OUTPUT_VIEWERS = {
    "SetOfParticles": "metadata",
    "SetOfMicrographs": "metadata",
    "SetOfClasses2D": "metadata",
    "SetOfClasses3D": "metadata",
    "SetOfVolumes": "volume",
    "SetOfFSCs": "fsc",
    "SetOfCTF": "ctf",
    "SetOfCoordinates": "coords2d",
    "SetOfCoordinates3D": "integrated-tomography",
    "SetOfTiltSeries": "integrated-tomography",
    "SetOfCTFTomoSeries": "integrated-tomography",
    "SetOfTomograms": "integrated-tomography",
}


class ProtocolViewerResourceResolutionError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _positive_persisted_id(value: Any) -> int:
    if type(value) is int and value > 0:
        return value
    if type(value) is str and value.isascii() and value.isdecimal() and int(value) > 0:
        return int(value)
    raise ProtocolViewerResourceResolutionError("invalid_persisted_identity")


def _reserved(properties: Any) -> bool:
    # An undecodable/malformed property map must never be treated as published.
    if not isinstance(properties, Mapping):
        return True
    value = properties.get("runtimeReserved", False)
    if value is False or value is None or value == "false":
        return False
    return True


def resolvePersistedProtocolViewerOutputResource(*, mapper: Any, set_mapper: Any,
                                                  project_id: int, protocol_id: int,
                                                  output_name: str) -> Dict[str, Any]:
    """Inspect one exact output without materializing the protocol or loading Set items.

    Protocol IDs are Scipion runtime IDs; the Set mapper receives ONLY the
    validated internal PostgreSQL protocol row ID. The response is diagnostic,
    not a command, URL, persisted pointer, or verified viewer/action binding.
    """
    if type(project_id) is not int or project_id <= 0 or type(protocol_id) is not int or protocol_id <= 0:
        raise ProtocolViewerResourceResolutionError("invalid_identity")
    if type(output_name) is not str or not _OUTPUT_NAME.fullmatch(output_name):
        raise ProtocolViewerResourceResolutionError("invalid_output_name")
    if mapper is None or set_mapper is None:
        raise ProtocolViewerResourceResolutionError("missing_mapper")

    row = mapper.getProjectProtocolByProtocolId(projectId=project_id, protocolId=protocol_id)
    if not isinstance(row, Mapping):
        raise ProtocolViewerResourceResolutionError("protocol_not_found")
    row_db_id = _positive_persisted_id(row.get("id"))
    if _positive_persisted_id(row.get("projectId")) != project_id or _positive_persisted_id(row.get("protocolId")) != protocol_id:
        raise ProtocolViewerResourceResolutionError("protocol_identity_mismatch")

    # limit=0 prevents fetching any Set member. This existing Scipion mapper
    # performs only scoped PostgreSQL lookups, with no SQLite fallback.
    stored = set_mapper.getStoredSet(projectId=project_id, protocolDbId=row_db_id,
                                     outputName=output_name, limit=0, offset=0)
    if not isinstance(stored, Mapping):
        raise ProtocolViewerResourceResolutionError("output_not_found")
    if (_positive_persisted_id(stored.get("id")) <= 0 or
            _positive_persisted_id(stored.get("projectId")) != project_id or
            _positive_persisted_id(stored.get("protocolDbId")) != row_db_id or
            stored.get("outputName") != output_name):
        raise ProtocolViewerResourceResolutionError("output_identity_mismatch")
    if _reserved(stored.get("properties")):
        raise ProtocolViewerResourceResolutionError("output_not_published")

    output_class = stored.get("setClassName")
    viewer_kind = _OUTPUT_VIEWERS.get(output_class) if type(output_class) is str else None
    if viewer_kind is None:
        raise ProtocolViewerResourceResolutionError("unsupported_output_class")

    # Output type is verified in persistence. Viewer eligibility, action-to-
    # resource binding, adapter integration and execution remain unverified.
    return {
        "status": "metadata-verified",
        "source": "postgresql",
        "projectId": project_id,
        "protocolId": str(protocol_id),
        "outputName": output_name,
        "resourceKind": "persisted-set",
        "outputClassName": output_class,
        "webViewerKind": viewer_kind,
        "availability": "blocked",
        "blockers": ["action_binding_not_verified", "web_action_not_implemented"],
        "instanceVerified": False,
        "renderable": False,
        "executionAllowed": False,
    }
