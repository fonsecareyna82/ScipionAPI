"""Regression contract for non-executing, plugin-independent viewer discovery."""

import importlib
from pathlib import Path
from types import SimpleNamespace

_REPO_ROOT = Path(__file__).resolve().parents[5]


def _catalog_module():
    # Import at test time: RED fails individual tests, not collection.
    return importlib.import_module(
        "app.backend.api.services.protocol_viewer_inventory_service"
    )


def _fixtures():
    from pyworkflow.protocol import Protocol
    from pyworkflow.viewer import ProtocolViewer, Viewer

    class ExampleProtocol(Protocol):
        pass

    class DerivedProtocol(ExampleProtocol):
        pass

    class ParticleSet:
        pass

    class ForbiddenViewer(ProtocolViewer):
        _targets = [ExampleProtocol]
        _environments = ["tkinter", "django"]
        _label = "Scientific visualization"

        def __init__(self, *args, **kwargs):
            raise AssertionError("viewer constructor MUST NOT run during discovery")

        def _defineParams(self, form):
            raise AssertionError("viewer form MUST NOT be generated during discovery")

        def _getVisualizeDict(self):
            raise AssertionError("viewer actions MUST NOT be evaluated during discovery")

    class ObjectOnlyViewer(Viewer):
        _targets = [ParticleSet]
        _environments = ["tkinter"]

        def __init__(self, *args, **kwargs):
            raise AssertionError("viewer must not be constructed")

        def _visualize(self, *args, **kwargs):
            raise AssertionError("viewer must not visualize")

    class MixedViewer(Viewer):
        _targets = [DerivedProtocol, ParticleSet, "LegacyClass"]

    class InheritedViewer(ForbiddenViewer):
        pass

    # Explicit module names imitate independent third-party plugins.
    ForbiddenViewer.__module__ = "relion.viewers.fake"
    ObjectOnlyViewer.__module__ = "facilities.viewers.fake"
    MixedViewer.__module__ = "otherplugin.viewers.extra"
    InheritedViewer.__module__ = "otherplugin.viewers.inherited"
    return ForbiddenViewer, ObjectOnlyViewer, MixedViewer, InheritedViewer


def test_registered_protocol_viewer_is_inventoried_without_instantiation():
    module = _catalog_module()
    protocol_viewer, _, _, _ = _fixtures()
    entries = module.buildProtocolViewerInventory({"Relion": protocol_viewer})
    assert len(entries) == 1
    entry = entries[0]
    assert entry["plugin"] == "relion"
    assert entry["viewerKind"] == "protocol-form"
    assert entry["label"] == "Scientific visualization"
    assert entry["targetKinds"] == ["protocol"]
    assert entry["targets"][0]["name"] == "ExampleProtocol"
    assert entry["webSupport"] == "unassessed"
    assert entry["legacyDjangoDeclared"] is True


def test_viewer_registry_is_plugin_agnostic_and_distinguishes_object_targets():
    module = _catalog_module()
    protocol_viewer, output_viewer, mixed, _ = _fixtures()
    entries = module.buildProtocolViewerInventory({
        "One": mixed,
        "Two": protocol_viewer,
        "Three": output_viewer,
    })
    assert [entry["plugin"] for entry in entries] == ["facilities", "otherplugin", "relion"]
    fac = entries[0]
    assert fac["viewerKind"] == "simple"
    assert fac["targetKinds"] == ["object"]
    assert fac["legacyDjangoDeclared"] is False
    other = entries[1]
    assert other["targetKinds"] == ["object", "protocol", "unknown"]
    assert next(t for t in other["targets"] if t["name"] == "LegacyClass")["kind"] == "unknown"


def test_registry_aliases_collapse_without_losing_original_names():
    module = _catalog_module()
    protocol_viewer, *_ = _fixtures()
    entries = module.buildProtocolViewerInventory({"AliasZ": protocol_viewer, "AliasA": protocol_viewer})
    assert len(entries) == 1
    assert entries[0]["registrationNames"] == ["AliasA", "AliasZ"]
    assert entries[0]["id"].startswith("relion.viewers.fake.")


def test_discovery_never_evaluates_viewer_instance_customizations():
    module = _catalog_module()
    a, _, _, inherited = _fixtures()
    entries = module.buildProtocolViewerInventory({"A": a, "Inherited": inherited})
    assert len(entries) == 2
    inherited_entry = next(item for item in entries if item["name"] == "InheritedViewer")
    assert inherited_entry["viewerKind"] == "protocol-form"
    assert inherited_entry["targetKinds"] == ["protocol"]
    assert inherited_entry["environments"] == ["django", "tkinter"]


def test_broken_or_unregistered_viewers_do_not_break_inventory():
    module = _catalog_module()
    _, output_viewer, _, _ = _fixtures()
    entries = module.buildProtocolViewerInventory({"Bad": object(), "BadType": str, "Good": output_viewer})
    assert len(entries) == 1
    assert entries[0]["plugin"] == "facilities"
    assert all(not entry.get("webSupported", False) for entry in entries)


def test_viewer_registry_snapshot_is_refresh_synchronized(monkeypatch):
    domain_refresh = importlib.import_module(
        "app.backend.api.services.scipion_domain_refresh_service"
    )
    _, viewer_class, _, _ = _fixtures()
    calls = []

    class FakeDomain:
        def getViewers(self):
            calls.append("get")
            return {"V": viewer_class}

    monkeypatch.setattr(domain_refresh, "_refreshScipionDomainLocked", lambda force=False: calls.append("refresh"))
    monkeypatch.setattr(domain_refresh.Config, "getDomain", lambda: FakeDomain())
    result = domain_refresh.getScipionViewersSnapshot()
    assert calls == ["refresh", "get"]
    assert result == {"V": viewer_class}


def test_authenticated_diagnostic_endpoint_is_registered_before_plugin_detail():
    source = _REPO_ROOT.joinpath("app/backend/api/routers/plugin_router.py").read_text(encoding="utf-8")
    assert '@router.get("/viewers", response_model=Any)' in source
    assert 'Depends(getCurrentUser)' in source
    assert 'getScipionViewersSnapshot()' in source
    assert 'buildProtocolViewerInventory(' in source
    assert source.index('@router.get("/viewers", response_model=Any)') < source.index('@router.get("/{pluginName}", response_model=Any)')
