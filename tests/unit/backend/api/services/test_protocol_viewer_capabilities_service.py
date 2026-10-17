"""RED 119: viewer web-capability declarations are safe, explicit and non-executable."""
from __future__ import annotations

import importlib

import pytest


def capability_module():
    return importlib.import_module(
        "app.backend.api.services.protocol_viewer_capabilities_service"
    )


def fixtures():
    from pyworkflow.protocol import Protocol
    from pyworkflow.viewer import ProtocolViewer, Viewer
    from app.backend.api.services.protocol_viewer_resolution_service import (
        resolveProtocolViewerCandidates,
    )

    class FakeProtocol(Protocol):
        pass

    class GraphicsViewer(Viewer):
        _targets = [FakeProtocol]
        _environments = ["tkinter", "django"]

        def __init__(self, *args, **kwargs):
            raise AssertionError("Viewer must not be instantiated")

        def visualize(self, *args, **kwargs):
            raise AssertionError("Viewer must not run")

    class ComplexViewer(ProtocolViewer):
        _targets = [FakeProtocol]
        _environments = ["tkinter"]

        @classmethod
        def can_handle_this_instance(cls, instance):
            raise AssertionError("Plugin hooks must not run")

        def __init__(self, *args, **kwargs):
            raise AssertionError("ProtocolViewer must not be instantiated")

        def _defineParams(self, form):
            raise AssertionError("Tk form must not be built")

    FakeProtocol.__module__ = "scientific.protocols"
    GraphicsViewer.__module__ = "scientific.viewers"
    ComplexViewer.__module__ = "another_plugin.viewers"
    registry = {"graphics": GraphicsViewer, "complex": ComplexViewer}
    candidate_result = resolveProtocolViewerCandidates(
        {"FakeProtocol": FakeProtocol}, registry, "FakeProtocol"
    )
    return FakeProtocol, GraphicsViewer, ComplexViewer, registry, candidate_result


def adapter(viewer, ident="basic-plot", capabilities=None, surface="react"):
    from app.backend.api.services.protocol_viewer_inventory_service import _class_identity
    return {_class_identity(viewer): {
        "id": ident,
        "surface": surface,
        "capabilities": capabilities or [{"kind": "plot", "effect": "read-only"}],
    }}


def describe(viewer=None, declarations=None):
    _, graphics, _, registry, candidates = fixtures()
    target = viewer or graphics
    planned = adapter(target) if declarations is None else declarations
    result = capability_module().describeProtocolViewerWebCapabilities(
        candidates, registry, planned
    )
    return result, registry, candidates


def item_by_name(result, name):
    return next(x for x in result["viewers"] if x["name"] == name)


def test_absent_adapters_never_claim_web_readiness():
    answer, _, _ = describe(declarations={})
    assert answer["webCapabilitySummary"] == {
        "candidateCount": 2,
        "declaredAdapterCount": 0,
        "unadaptedCount": 2,
        "webReadyCount": 0,
    }
    assert all(v["webAdapter"] is None and v["webCapabilities"] == []
               for v in answer["viewers"])
    assert all(v["webSupport"] == "unassessed" for v in answer["viewers"])
    assert answer["autoLaunchAllowed"] is False
    assert answer["selectedViewerId"] is None


def test_reviewed_adapter_declaration_is_not_implementation_or_permission():
    result, _, _ = describe()
    viewer = item_by_name(result, "GraphicsViewer")
    assert viewer["webAdapter"] == {
        "id": "basic-plot", "surface": "react", "status": "declared-not-integrated"
    }
    assert viewer["webCapabilities"] == [{"kind": "plot", "effect": "read-only"}]
    assert viewer["webSupport"] == "unassessed"
    assert result["webCapabilitySummary"]["declaredAdapterCount"] == 1
    assert result["webCapabilitySummary"]["webReadyCount"] == 0
    assert result["autoLaunchAllowed"] is False


def test_generic_capabilities_cover_read_derived_mutating_and_external_actions():
    _, graphics, _, registry, candidates = fixtures()
    kinds = [
        {"kind": "metadata-table", "effect": "read-only"},
        {"kind": "volume", "effect": "read-only"},
        {"kind": "particles", "effect": "read-only"},
        {"kind": "classes", "effect": "read-only"},
        {"kind": "plot", "effect": "derived-read"},
        {"kind": "image", "effect": "read-only"},
        {"kind": "html-report", "effect": "derived-read"},
        {"kind": "message", "effect": "read-only"},
        {"kind": "monitor", "effect": "read-only"},
        {"kind": "protocol-action", "effect": "mutating"},
        {"kind": "external-app", "effect": "external-process"},
    ]
    res = capability_module().describeProtocolViewerWebCapabilities(
        candidates, registry, adapter(graphics, capabilities=kinds, surface="external")
    )
    view = item_by_name(res, "GraphicsViewer")
    assert view["webCapabilities"] == kinds
    assert view["webAdapter"]["surface"] == "external"
    assert res["autoLaunchAllowed"] is False


def test_adapters_for_different_plugins_are_matched_by_full_identity():
    _, graphics, complex_cls, registry, candidates = fixtures()
    declarations = {}
    declarations.update(adapter(graphics, "graphs"))
    declarations.update(adapter(complex_cls, "analysis-form",
                                [{"kind": "classes", "effect": "read-only"}]))
    result = capability_module().describeProtocolViewerWebCapabilities(
        candidates, registry, declarations
    )
    assert result["webCapabilitySummary"]["declaredAdapterCount"] == 2
    assert item_by_name(result, "ComplexViewer")["webAdapter"]["id"] == "analysis-form"
    assert item_by_name(result, "GraphicsViewer")["webAdapter"]["id"] == "graphs"
    assert result["autoLaunchAllowed"] is False


def test_duplicate_registry_aliases_do_not_duplicate_capabilities():
    _, graphics, _, registry, candidates = fixtures()
    registry["graphics_alias"] = graphics
    result = capability_module().describeProtocolViewerWebCapabilities(
        candidates, registry, adapter(graphics)
    )
    assert result["webCapabilitySummary"]["declaredAdapterCount"] == 1
    assert sum(x["name"] == "GraphicsViewer" for x in result["viewers"]) == 1


def test_stale_adapters_for_uninstalled_plugins_are_ignored_without_import():
    _, graphics, _, registry, candidates = fixtures()
    declarations = adapter(graphics)
    declarations["obsolete_plugin.viewers.NonexistentViewer"] = {
        "id": "broken", "surface": "react", "capabilities": [object()]
    }
    result = capability_module().describeProtocolViewerWebCapabilities(
        candidates, registry, declarations
    )
    assert result["webCapabilitySummary"]["declaredAdapterCount"] == 1


def test_invalid_capability_kind_fails_closed():
    _, graphics, _, registry, candidates = fixtures()
    with pytest.raises(capability_module().ProtocolViewerCapabilitiesError) as exc:
        capability_module().describeProtocolViewerWebCapabilities(
            candidates, registry, adapter(graphics, capabilities=[
                {"kind": "launch-arbitrary-python", "effect": "read-only"}
            ])
        )
    assert exc.value.code == "invalid_capability"


def test_invalid_effect_fails_closed():
    _, graphics, _, registry, candidates = fixtures()
    with pytest.raises(capability_module().ProtocolViewerCapabilitiesError) as exc:
        capability_module().describeProtocolViewerWebCapabilities(
            candidates, registry, adapter(graphics, capabilities=[
                {"kind": "plot", "effect": "unrestricted-exec"}
            ])
        )
    assert exc.value.code == "invalid_effect"


def test_callbacks_and_unreviewed_ready_flags_cannot_enter_descriptors():
    _, graphics, _, registry, candidates = fixtures()
    declarations = adapter(graphics)
    descriptor = next(iter(declarations.values()))
    descriptor["callback"] = lambda: 1
    descriptor["webReady"] = True
    with pytest.raises(capability_module().ProtocolViewerCapabilitiesError) as exc:
        capability_module().describeProtocolViewerWebCapabilities(
            candidates, registry, declarations
        )
    assert exc.value.code == "invalid_adapter"


def test_unregistered_viewer_id_is_rejected_even_if_an_adapter_claims_it():
    _, graphics, _, registry, candidates = fixtures()
    candidates["viewers"][0]["id"] = "unknown.viewers.UntrustedViewer"
    with pytest.raises(capability_module().ProtocolViewerCapabilitiesError) as exc:
        capability_module().describeProtocolViewerWebCapabilities(
            candidates, registry, adapter(graphics)
        )
    assert exc.value.code == "unregistered_viewer"


def test_declarations_and_previous_candidates_are_not_mutated():
    _, graphics, _, registry, candidates = fixtures()
    declarations = adapter(graphics)
    original = [dict(v) for v in candidates["viewers"]]
    res = capability_module().describeProtocolViewerWebCapabilities(
        candidates, registry, declarations
    )
    res["viewers"][0]["webCapabilities"].append({"kind": "image", "effect": "read-only"})
    assert candidates["viewers"] == original
    assert declarations == adapter(graphics)


def test_persisted_protocol_integration_is_read_only_and_never_executes_custom_hooks():
    from app.backend.api.services.protocol_viewer_persisted_resolution_service import (
        resolvePersistedProtocolViewerCandidates,
    )
    prot, graphics, complex_cls, registry, _ = fixtures()
    calls = []
    secret = "SECRET_MUST_NOT_LEAK"
    class Mapper:
        def getProjectProtocolByProtocolId(self, *, projectId, protocolId):
            calls.append((projectId, protocolId))
            return {"id": 83, "projectId": 9, "protocolId": "1200",
                    "protocolClassName": "FakeProtocol", "status": "finished",
                    "params": {"password": secret}}
        def getProjectProtocolByDbId(self, **kwargs):
            raise AssertionError("Must not query PostgreSQL DB ids")
    result = resolvePersistedProtocolViewerCandidates(
        mapper=Mapper(), project_id=9, protocol_id=1200,
        snapshot={"protocols": {"FakeProtocol": prot},
                  "viewers": registry, "preferredViewers": {},
                  "webAdapters": adapter(complex_cls, "plugin-agnostic", [
                      {"kind": "classes", "effect": "derived-read"}
                  ])},
    )
    assert calls == [(9, 1200)]
    assert result["protocolStatus"] == "finished"
    assert result["dataSource"] == "postgresql"
    assert result["webCapabilitySummary"]["declaredAdapterCount"] == 1
    restricted = item_by_name(result, "ComplexViewer")
    assert restricted["eligibilityAssessment"]["requiresControlledRuntimeEvaluation"] is True
    assert restricted["eligibilityAssessment"]["webLaunchAllowed"] is False
    assert restricted["eligibilityAssessment"]["webAdapterStatus"] == "declared-not-integrated"
    assert result["autoLaunchAllowed"] is False
    assert result["instanceMaterialized"] is False
    assert result["instanceChecksApplied"] is False
    assert secret not in str(result)
