"""RED 113: safe, plugin-independent protocol-class viewer matching."""

import importlib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[5]


def _module():
    return importlib.import_module(
        "app.backend.api.services.protocol_viewer_resolution_service"
    )


def _fixtures():
    from pyworkflow.protocol import Protocol
    from pyworkflow.viewer import ProtocolViewer, Viewer

    class BaseProtocol(Protocol):
        pass

    class DerivedProtocol(BaseProtocol):
        pass

    class OtherProtocol(Protocol):
        pass

    class OutputObject:
        pass

    class AInheritedViewer(Viewer):
        _targets = [BaseProtocol]
        _environments = ["tkinter"]

        def __init__(self, *args, **kwargs):
            raise AssertionError("must never instantiate a viewer")

    class BExactViewer(ProtocolViewer):
        _targets = [DerivedProtocol]
        _environments = ["tkinter", "django"]

        def __init__(self, *args, **kwargs):
            raise AssertionError("must never instantiate a viewer")

        def _defineParams(self, form):
            raise AssertionError("must never create viewer form")

        def _getVisualizeDict(self):
            raise AssertionError("must never access viewer actions")

    class CExactViewer(Viewer):
        _targets = [DerivedProtocol, BaseProtocol]
        _environments = ["tkinter"]

    class DObjectViewer(Viewer):
        _targets = [OutputObject]
        _environments = ["tkinter"]

    class EWebOnlyViewer(Viewer):
        _targets = [DerivedProtocol]
        _environments = ["django"]

    class ZConditionalViewer(Viewer):
        _targets = [DerivedProtocol]
        _environments = ["tkinter"]

        @classmethod
        def can_handle_this_instance(cls, instance):
            raise AssertionError("instance checks are not safe at class discovery")

    for clazz in [AInheritedViewer, BExactViewer, CExactViewer, DObjectViewer,
                  EWebOnlyViewer, ZConditionalViewer]:
        clazz.__module__ = "exampleplugin.viewers.testing"
    BaseProtocol.__module__ = "exampleplugin.protocols.testing"
    DerivedProtocol.__module__ = "exampleplugin.protocols.testing"
    OtherProtocol.__module__ = "exampleplugin.protocols.testing"

    protocols = {"DerivedAlias": DerivedProtocol, "Base": BaseProtocol,
                 "Other": OtherProtocol}
    viewers = {cls.__name__: cls for cls in [AInheritedViewer, BExactViewer,
                CExactViewer, DObjectViewer, EWebOnlyViewer, ZConditionalViewer]}
    return protocols, viewers, DerivedProtocol


def _resolve(*, preferred=None, protocol_name="DerivedProtocol", environment="tkinter",
             registry=None):
    protocols, viewers, _ = _fixtures()
    if registry is not None:
        viewers = registry
    return _module().resolveProtocolViewerCandidates(
        protocol_registry=protocols,
        viewer_registry=viewers,
        protocol_class_id=protocol_name,
        preferred_viewers=preferred or {},
        environment=environment,
    )


def test_exact_classes_win_before_inherited_even_if_alias_sorts_first():
    result = _resolve()
    ids = [entry["name"] for entry in result["viewers"]]
    assert ids == ["BExactViewer", "CExactViewer", "ZConditionalViewer", "AInheritedViewer"]
    assert [entry["matchReason"] for entry in result["viewers"]] == [
        "exact", "exact", "exact", "inherited"
    ]
    assert result["firstCandidateId"] == result["viewers"][0]["id"]
    assert result["viewerCount"] == 4
    assert result["selectionMode"] == "class-only"
    assert result["instanceChecksApplied"] is False
    assert result["autoLaunchAllowed"] is False


def test_configured_preferred_viewer_wins_with_declared_order():
    result = _resolve(preferred={"DerivedProtocol": [
        "exampleplugin.viewers.testing.AInheritedViewer",
        "exampleplugin.viewers.testing.CExactViewer",
    ]})
    assert [item["name"] for item in result["viewers"]][:3] == [
        "AInheritedViewer", "CExactViewer", "BExactViewer"
    ]
    assert [item["matchReason"] for item in result["viewers"]][:2] == [
        "preferred", "preferred"
    ]


def test_django_only_and_output_only_are_excluded_by_default():
    result = _resolve()
    assert "DObjectViewer" not in [item["name"] for item in result["viewers"]]
    assert "EWebOnlyViewer" not in [item["name"] for item in result["viewers"]]
    web = _resolve(environment="django")
    assert set(item["name"] for item in web["viewers"]) == {"BExactViewer", "EWebOnlyViewer"}
    assert all(item["webSupport"] == "unassessed" for item in web["viewers"])


def test_alias_collapsing_and_sorted_registration_names_do_not_duplicate_viewers():
    protocols, viewers, _ = _fixtures()
    viewers = {"AAlias": viewers["CExactViewer"], **viewers,
               "ZZAlias": viewers["CExactViewer"]}
    result = _module().resolveProtocolViewerCandidates(
        protocols, viewers, "DerivedProtocol", {}, "tkinter"
    )
    assert [x["name"] for x in result["viewers"]].count("CExactViewer") == 1
    item = next(x for x in result["viewers"] if x["name"] == "CExactViewer")
    assert item["registrationNames"] == ["AAlias", "CExactViewer", "ZZAlias"]


def test_inherited_targets_are_matched_by_python_mro_without_plugin_callbacks():
    result = _resolve()
    inherited = next(x for x in result["viewers"] if x["name"] == "AInheritedViewer")
    assert inherited["matchedTarget"] == "exampleplugin.protocols.testing._fixtures.<locals>.BaseProtocol"
    conditional = next(x for x in result["viewers"] if x["name"] == "ZConditionalViewer")
    assert conditional["instanceConditionUnverified"] is True
    assert result["hasUnverifiedInstanceConditions"] is True


def test_protocol_class_must_be_registered_not_dynamically_imported():
    with pytest.raises(_module().ProtocolViewerResolutionError) as exc:
        _resolve(protocol_name="untrusted.module.DoesNotExist")
    assert exc.value.code == "not_found"
    assert "untrusted" in str(exc.value)


def test_ambiguous_short_protocol_names_are_rejected_but_qualified_name_works():
    from pyworkflow.protocol import Protocol
    protocols, viewers, _ = _fixtures()
    twin1 = type("Twin", (Protocol,), {"__module__": "alpha.protocols"})
    twin2 = type("Twin", (Protocol,), {"__module__": "beta.protocols"})
    protocols["first"] = twin1
    protocols["second"] = twin2
    with pytest.raises(_module().ProtocolViewerResolutionError) as exc:
        _module().resolveProtocolViewerCandidates(protocols, viewers, "Twin")
    assert exc.value.code == "ambiguous"
    selected = _module().resolveProtocolViewerCandidates(protocols, viewers, "alpha.protocols.Twin")
    assert selected["protocol"]["id"] == "alpha.protocols.Twin"
    assert selected["viewerCount"] == 0
    assert selected["firstCandidateId"] is None


def test_unregistered_and_malformed_viewer_entries_fail_closed():
    from pyworkflow.viewer import Viewer
    protocols, viewers, _ = _fixtures()
    class Bad(Viewer):
        _targets = "DerivedProtocol"
        _environments = ["tkinter"]
    viewers["Bad"] = Bad
    viewers["Bogus"] = object()
    result = _module().resolveProtocolViewerCandidates(
        protocols, viewers, "DerivedProtocol",
        {"DerivedProtocol": ["bogus.module.NoViewer", object(), None]},
    )
    assert result["viewerCount"] == 4


def test_snapshot_refresh_is_atomic_with_protoc_viewer_and_preferences(monkeypatch):
    refresh = importlib.import_module("app.backend.api.services.scipion_domain_refresh_service")
    calls = []
    class FakeDomain:
        def getProtocols(self):
            calls.append("protocols")
            return {"P": object()}
        def getViewers(self):
            calls.append("viewers")
            return {"V": object()}
    monkeypatch.setattr(refresh, "_refreshScipionDomainLocked", lambda force=False: calls.append("refresh"))
    monkeypatch.setattr(refresh.Config, "getDomain", lambda: FakeDomain())
    monkeypatch.setattr(refresh.Config, "VIEWERS", {"P": ["module.Viewer"]}, raising=False)
    result = refresh.getScipionViewerResolutionSnapshot()
    assert calls == ["refresh", "protocols", "viewers"]
    assert result["protocols"] == {"P": object()} or set(result["protocols"]) == {"P"}
    assert result["viewers"].keys() == {"V"}
    assert result["preferredViewers"] == {"P": ["module.Viewer"]}


def test_authenticated_resolver_endpoint_is_static_and_before_plugin_name_route():
    source = _REPO_ROOT.joinpath("app/backend/api/routers/plugin_router.py").read_text(encoding="utf-8")
    assert '@router.get("/viewers/resolve", response_model=Any)' in source
    start = source.index('@router.get("/viewers/resolve", response_model=Any)')
    end = source.index('@router.get("/{pluginName}", response_model=Any)')
    resolver = source[start:end]
    assert 'Depends(getCurrentUser)' in resolver
    assert 'getScipionViewerResolutionSnapshot()' in resolver
    assert 'resolveProtocolViewerCandidates(' in resolver
    assert 'ProtocolViewerResolutionError' in resolver
    assert source.index('@router.get("/viewers", response_model=Any)') < start < end
