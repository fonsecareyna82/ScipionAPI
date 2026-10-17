"""RED 123: advisory ProtocolViewer action schemas never execute plugin code."""
from __future__ import annotations

import importlib
from copy import deepcopy

import pytest


def actions():
    return importlib.import_module(
        "app.backend.api.services.protocol_viewer_action_schema_service"
    )


def form_schema(*, include_hidden=False):
    return {
        "status": "static-preview", "sections": [{
            "label": "Visualization", "fields": [
                {"name": "displayVol", "label": "Display volume", "control": "select"},
                {"name": "showFsc", "label": "Show FSC", "control": "label"},
            ],
            "groups": [{"label": "Advanced", "fields": [
                {"name": "threshold", "label": "Threshold", "control": "number"},
            ]}],
        }], "hiddenFields": int(include_hidden),
    }


def setup_viewers():
    from pyworkflow.protocol import Protocol
    from pyworkflow.viewer import Viewer, ProtocolViewer
    from app.backend.api.services.protocol_viewer_resolution_service import resolveProtocolViewerCandidates
    from app.backend.api.services.protocol_viewer_form_schema_service import describeProtocolViewerStaticForms

    class FakeProtocol(Protocol):
        pass

    class PlainViewer(Viewer):
        _targets = [FakeProtocol]
        def __init__(self, *args, **kwargs):
            raise AssertionError("Viewer constructor was executed")

    class FormViewer(ProtocolViewer):
        _targets = [FakeProtocol]
        def __init__(self, *args, **kwargs):
            raise AssertionError("ProtocolViewer constructor was executed")
        def _defineParams(self, form):
            form.addSection(label="Visualization")
            form.addParam("displayVol", params.EnumParam, choices=["slice", "surface"], label="Display volume")
            form.addParam("showFsc", params.LabelParam, label="Show FSC")
            form.addParam("threshold", params.FloatParam, label="Threshold")
            form.addHidden("private", params.StringParam, default="DONT_EXPOSE_ME")
        def _getVisualizeDict(self):
            raise AssertionError("_getVisualizeDict was EXECUTED")
            return {"displayVol": self._showVolume, "showFsc": self._showFSC}
        def _showVolume(self, name):
            raise AssertionError("Handler executed")
        def _showFSC(self, name):
            raise AssertionError("Handler executed")

    FakeProtocol.__module__ = "viewerfixture.protocols"
    PlainViewer.__module__ = "viewerfixture.viewers"
    FormViewer.__module__ = "viewerfixture.viewers"
    registry = {"plain": PlainViewer, "form": FormViewer}
    candidates = resolveProtocolViewerCandidates({"FakeProtocol": FakeProtocol}, registry, "FakeProtocol")
    candidates = describeProtocolViewerStaticForms(candidates, registry)
    return FakeProtocol, PlainViewer, FormViewer, registry, candidates


def by_name(result, name):
    return next(candidate for candidate in result["viewers"] if candidate["name"] == name)


def test_literal_return_links_only_known_public_fields():
    src = '''def _getVisualizeDict(self):
    return {"displayVol": self._showVolume, "showFsc": self._showFSC}
'''
    d = actions().parseProtocolViewerStaticActionsSource(src, form_schema())
    assert d["status"] == "static-preview"
    assert [a["id"] for a in d["actions"]] == ["displayVol", "showFsc"]
    assert [a["label"] for a in d["actions"]] == ["Display volume", "Show FSC"]
    assert all(a["previewOnly"] is True and a["executionAllowed"] is False for a in d["actions"])
    assert d["renderable"] is False
    assert d["requiresRuntimeEvaluation"] is True


def test_named_mapping_return_supports_groups_without_executing_source():
    src = '''def _getVisualizeDict(self):
    handlers = {'threshold': self._showThreshold, 'showFsc': self._showFSC}
    return handlers
'''
    d = actions().parseProtocolViewerStaticActionsSource(src, form_schema())
    assert [a["id"] for a in d["actions"]] == ["threshold", "showFsc"]
    assert d["actions"][0]["control"] == "number"


def test_hidden_and_unmatched_handlers_are_not_exposed_or_named():
    src = '''def _getVisualizeDict(self):
    return {'private': self._secret, 'showFsc': self._showFSC, 'dynamicExtra': self._unsafe}
'''
    d = actions().parseProtocolViewerStaticActionsSource(src, form_schema(include_hidden=True))
    assert [a["id"] for a in d["actions"]] == ["showFsc"]
    assert d["unmatchedActionsOmitted"] == 2
    assert "private" not in str(d)
    assert "dynamicExtra" not in str(d)
    assert "_secret" not in str(d)


def test_conditional_override_is_only_a_partial_preview():
    src = '''def _getVisualizeDict(self):
    handlers = {'showFsc': self._showFSC}
    if self.protocol.finished():
        handlers['showFsc'] = self._other
    return handlers
'''
    d = actions().parseProtocolViewerStaticActionsSource(src, form_schema())
    assert d["status"] == "static-preview"
    assert d["dynamicEntriesSkipped"] > 0
    assert d["executionAllowed"] is False


def test_computed_keys_and_handler_calls_are_rejected():
    src = '''def _getVisualizeDict(self):
    return {self.secret(): self._showFSC, 'showFsc': self.exploit(),
            'displayVol': self._showVolume}
'''
    d = actions().parseProtocolViewerStaticActionsSource(src, form_schema())
    assert [a["id"] for a in d["actions"]] == ["displayVol"]
    assert d["dynamicEntriesSkipped"] == 2
    assert "secret" not in str(d)
    assert "exploit" not in str(d)


def test_duplicate_and_spread_mapping_entries_are_skipped():
    src = '''def _getVisualizeDict(self):
    return {'showFsc': self._showFSC, 'showFsc': self._evil, **self.other}
'''
    d = actions().parseProtocolViewerStaticActionsSource(src, form_schema())
    assert d["actionsDiscovered"] == 1
    assert d["dynamicEntriesSkipped"] == 2
    assert "evil" not in str(d)


def test_unknown_form_is_never_a_public_action_schema():
    src = '''def _getVisualizeDict(self):
    return {'displayVol': self._showVolume}
'''
    assert actions().parseProtocolViewerStaticActionsSource(src, None)["status"] == "unavailable"
    assert actions().parseProtocolViewerStaticActionsSource(src, {"status": "unavailable"})["actions"] == []


def test_invalid_source_and_oversized_source_fail_closed():
    parse = actions().parseProtocolViewerStaticActionsSource
    assert parse("invalid syntax here!", form_schema())["actions"] == []
    assert parse("x" * 150000, form_schema())["actions"] == []
    assert parse("def other(self): return {'showFsc': self._showFSC}", form_schema())["actions"] == []
    assert parse("async def _getVisualizeDict(self): return {}", form_schema())["actions"] == []


def test_action_scanner_preserves_registration_and_never_invokes_plugin_hooks():
    _, _, _, registry, candidates = setup_viewers()
    result = actions().describeProtocolViewerStaticActions(candidates, registry)
    assert by_name(result, "PlainViewer")["actionSchema"] is None
    schema = by_name(result, "FormViewer")["actionSchema"]
    assert schema["status"] == "static-preview"
    assert [a["id"] for a in schema["actions"]] == ["displayVol", "showFsc"]
    assert result["actionSchemaSummary"]["executableActionCount"] == 0
    assert result["autoLaunchAllowed"] is False


def test_registry_alias_does_not_duplicate_actions():
    _, _, form, registry, candidates = setup_viewers()
    registry["Duplicate"] = form
    result = actions().describeProtocolViewerStaticActions(candidates, registry)
    assert result["actionSchemaSummary"]["protocolViewerCount"] == 1
    assert result["actionSchemaSummary"]["actionsDiscovered"] == 2


def test_forged_candidate_is_rejected_before_source_read():
    _, _, _, registry, candidates = setup_viewers()
    candidates["viewers"][0]["id"] = "forged.plugins.BadViewer"
    def forbid(*args):
        raise AssertionError("Source should never be read")
    with pytest.raises(actions().ProtocolViewerActionsError) as error:
        actions().describeProtocolViewerStaticActions(candidates, registry, source_loader=forbid)
    assert error.value.code == "unregistered_viewer"


def test_missing_source_is_safe_and_does_not_modify_input():
    _, _, _, registry, candidates = setup_viewers()
    original = deepcopy(candidates)
    def missing(*_):
        raise OSError("No source")
    result = actions().describeProtocolViewerStaticActions(candidates, registry, source_loader=missing)
    assert by_name(result, "FormViewer")["actionSchema"]["status"] == "unavailable"
    assert result["actionSchemaSummary"]["executableActionCount"] == 0
    assert candidates == original


def test_fake_client_flags_cannot_promote_static_actions_to_web_ready():
    _, _, _, registry, candidates = setup_viewers()
    candidates["autoLaunchAllowed"] = True
    candidates["selectedViewerId"] = by_name(candidates, "FormViewer")["id"]
    d = actions().describeProtocolViewerStaticActions(candidates, registry)
    assert d["autoLaunchAllowed"] is False
    assert d["selectedViewerId"] is None
    assert by_name(d, "FormViewer")["actionSchema"]["executionAllowed"] is False
    assert by_name(d, "FormViewer")["actionSchema"]["renderable"] is False


def test_persisted_endpoint_returns_safe_actions_not_postgresql_params():
    from app.backend.api.services.protocol_viewer_persisted_resolution_service import (
        resolvePersistedProtocolViewerCandidates,
    )
    protocol_class, _, _, registry, _ = setup_viewers()
    calls = []
    class Mapper:
        def getProjectProtocolByProtocolId(self, *, projectId, protocolId):
            calls.append((projectId, protocolId))
            return {"id": 910, "projectId": projectId, "protocolId": str(protocolId),
                    "protocolClassName": "FakeProtocol", "status": "finished",
                    "params": {"jwt": "ULTRA_SECRET_NOT_FOR_THE_CLIENT"}}
        def getProjectProtocolByDbId(self, **kwargs):
            raise AssertionError("DB-ID fallback must not be used")
    result = resolvePersistedProtocolViewerCandidates(
        mapper=Mapper(), project_id=8, protocol_id=17,
        snapshot={"protocols": {"FakeProtocol": protocol_class},
                  "viewers": registry, "preferredViewers": {}, "webAdapters": {}},
    )
    assert calls == [(8, 17)]
    assert result["actionSchemaSummary"] == {
        "protocolViewerCount": 1, "staticPreviewCount": 1,
        "actionsDiscovered": 2, "executableActionCount": 0,
    }
    assert by_name(result, "FormViewer")["actionSchema"]["actionsDiscovered"] == 2
    assert "ULTRA_SECRET_NOT_FOR_THE_CLIENT" not in str(result)
    assert result["autoLaunchAllowed"] is False
