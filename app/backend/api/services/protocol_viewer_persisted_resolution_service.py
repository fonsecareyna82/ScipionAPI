"""Read-only viewer candidates for a concrete PostgreSQL protocol row.

Never instantiate protocols or viewers, deserialize inputs, or invoke plugin
callbacks. A persisted row is *not* proof of per-instance viewer eligibility.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping

from app.backend.api.services.protocol_viewer_resolution_service import (
    ProtocolViewerResolutionError,
    resolveProtocolViewerCandidates,
)
from app.backend.api.services.protocol_viewer_eligibility_service import (
    assessProtocolViewerEligibility,
)
from app.backend.api.services.protocol_viewer_capabilities_service import (
    describeProtocolViewerWebCapabilities,
)
from app.backend.api.services.protocol_viewer_form_schema_service import (
    describeProtocolViewerStaticForms,
)
from app.backend.api.services.protocol_viewer_action_schema_service import (
    describeProtocolViewerStaticActions,
)
from app.backend.api.services.protocol_viewer_contract_service import (
    validateProtocolViewerContracts,
)


class PersistedProtocolViewerError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def resolvePersistedProtocolViewerCandidates(
    *,
    mapper: Any,
    project_id: int,
    protocol_id: int,
    snapshot: Mapping[str, Any],
) -> Dict[str, Any]:
    """Resolve Scipion protocol-ID strictly inside its owning PostgreSQL project.

    Read only the persisted protocol identity. Even class-level selection stays
    advisory until per-instance hooks and web adapters are evaluated elsewhere.
    """
    if mapper is None:
        raise PersistedProtocolViewerError("missing_mapper", "PostgreSQL mapper is required")
    if not isinstance(project_id, int) or isinstance(project_id, bool) or project_id < 1:
        raise PersistedProtocolViewerError("invalid_identity", "Invalid project id")
    if not isinstance(protocol_id, int) or isinstance(protocol_id, bool) or protocol_id < 1:
        raise PersistedProtocolViewerError("invalid_identity", "Invalid Scipion protocol id")

    # Public protocolId is the Scipion runtime ID, NOT protocols.id.
    # Never fall back to a DB-ID lookup when this row is missing.
    row = mapper.getProjectProtocolByProtocolId(
        projectId=project_id, protocolId=protocol_id,
    )
    if not isinstance(row, Mapping):
        raise PersistedProtocolViewerError("not_found", "Protocol not found in project")
    try:
        row_project = int(row["projectId"])
        row_protocol = int(row["protocolId"])
        row_db_id = int(row["id"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise PersistedProtocolViewerError(
            "invalid_row", "Incomplete persisted protocol identity"
        ) from exc
    if row_project != project_id or row_protocol != protocol_id or row_db_id <= 0:
        raise PersistedProtocolViewerError(
            "identity_mismatch", "Persisted protocol does not match requested project and protocol"
        )
    class_name = row.get("protocolClassName")
    if not isinstance(class_name, str) or not class_name.strip():
        raise PersistedProtocolViewerError(
            "invalid_row", "Persisted protocol has no class name"
        )
    try:
        candidates = resolveProtocolViewerCandidates(
            protocol_registry=snapshot["protocols"],
            viewer_registry=snapshot["viewers"],
            protocol_class_id=class_name.strip(),
            preferred_viewers=snapshot.get("preferredViewers", {}),
            environment="tkinter",
        )
    except ProtocolViewerResolutionError as exc:
        raise PersistedProtocolViewerError(
            "ambiguous_class" if exc.code == "ambiguous" else "unregistered_class",
            str(exc),
        ) from exc

    # Do not disclose persisted parameters or paths in a diagnostic endpoint.
    # Avoid selecting a viewer automatically: can_handle_this_instance and
    # custom can_handle_this may reject the actual protocol at runtime.
    candidates.update({
        "projectId": project_id,
        "protocolId": str(protocol_id),
        "protocolDbId": row_db_id,
        "protocolStatus": str(row.get("status") or "").strip().lower(),
        "protocolClassName": class_name.strip(),
        "dataSource": "postgresql",
        "selectionMode": "persisted-protocol-class",
        "instanceMaterialized": False,
        "instanceChecksApplied": False,
        "autoLaunchAllowed": False,
        "selectedViewerId": None,
    })
    # Only classify static hook implementations; never reconstruct protocol
    # instances, run plugin callbacks, or infer availability in React.
    assessProtocolViewerEligibility(
        candidates, snapshot["viewers"],
    )
    # A declaration is not proof of an implemented web renderer or eligibility.
    declared_capabilities = describeProtocolViewerWebCapabilities(
        candidates, snapshot["viewers"],
        adapters=snapshot.get("webAdapters"),
    )
    # Only an advisory AST preview: never build Tk forms or invoke plugin hooks.
    static_forms = describeProtocolViewerStaticForms(
        declared_capabilities, snapshot["viewers"],
    )
    # Keep all static descriptors non-executable; verify cross-schema consistency.
    static_actions = describeProtocolViewerStaticActions(
        static_forms, snapshot["viewers"],
    )
    validated = validateProtocolViewerContracts(
        static_actions, snapshot["viewers"],
    )
    return validated
