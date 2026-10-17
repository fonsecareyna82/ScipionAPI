"""RED 121: bounded, read-only previews of ProtocolViewer form definitions."""
from __future__ import annotations

import importlib
from copy import deepcopy

import pytest


def forms():
    return importlib.import_module(
        "app.backend.api.services.protocol_viewer_form_schema_service"
    )


def fake_setup():
    from pyworkflow.protocol import Protocol
    from pyworkflow.viewer import Viewer, ProtocolViewer
    from app.backend.api.services.protocol_viewer_resolution_service import resolveProtocolViewerCandidates

    class FakeProt(Protocol):
        pass

    class SimpleViewer(Viewer):
        _targets = [FakeProt]

        def __init__(self, *args, **kwargs):
            raise AssertionError("Viewer instantiated")

    class FormViewer(ProtocolViewer):
        _targets = [FakeProt]

        def __init__(self, *args, **kwargs):
            raise AssertionError("ProtocolViewer instantiated")

        def _defineParams(self, form):
            form.addSection(label="Visualization")
            group = form.addGroup("Volume")
            group.addParam("mode", params.EnumParam, choices=["slices", "chimera"], default=0,
                           label="Display volume with", help="Choose mode")
            group.addParam("cutoff", params.FloatParam, default=0.143, label="Threshold")
            group.addHidden("privateInternal", params.IntParam, default=44)
            form.addParam("enabled", params.BooleanParam, default=True, label="Enabled")
            form.addParam("iterRange", params.NumericRangeParam, label="Iterations")
            form.addParam("showFsc", params.LabelParam, label="Display FSC")

    FakeProt.__module__ = "sample.protocols"
    SimpleViewer.__module__ = "sample.viewers"
    FormViewer.__module__ = "sample.viewers"
    registry = {"simple": SimpleViewer, "form": FormViewer}
    candidates = resolveProtocolViewerCandidates(
        {"FakeProt": FakeProt}, registry, "FakeProt"
    )
    return FakeProt, SimpleViewer, FormViewer, registry, candidates


def get_candidate(result, name):
    return next(v for v in result["viewers"] if v["name"] == name)


def test_literal_sections_groups_fields_and_defaults():
    src = '''def _defineParams(self, form):
    form.addSection(label="Visualization")
    group = form.addGroup("Volume")
    group.addParam("mode", params.EnumParam, choices=["slices", "chimera"], default=0, label="Display volume with")
    group.addParam("threshold", params.FloatParam, default=0.143, label="Threshold")
    form.addParam("enabled", params.BooleanParam, default=True, label="Enabled")
'''
    answer = forms().parseProtocolViewerStaticFormSource(src)
    assert answer["status"] == "static-preview"
    assert answer["sections"][0]["label"] == "Visualization"
    assert answer["sections"][0]["groups"][0]["label"] == "Volume"
    assert answer["sections"][0]["groups"][0]["fields"] == [
        {"name": "mode", "label": "Display volume with", "control": "select",
         "hasCondition": False, "default": 0, "choices": ["slices", "chimera"]},
        {"name": "threshold", "label": "Threshold", "control": "number",
         "hasCondition": False, "default": 0.143},
    ]
    assert answer["sections"][0]["fields"][0]["default"] is True
    assert answer["fieldsDiscovered"] == 3
    assert answer["renderable"] is False
    assert answer["actionExecutionAllowed"] is False


def test_hidden_fields_never_appear_even_if_literal():
    src = '''def _defineParams(self, form):
    form.addSection(label="Options")
    form.addHidden("secretKey", params.StringParam, default="SENSITIVE_PLACEHOLDER")
    form.addParam("public", params.IntParam, default=1, label="Public")
'''
    answer = forms().parseProtocolViewerStaticFormSource(src)
    assert answer["hiddenFields"] == 1
    assert answer["fieldsDiscovered"] == 1
    assert "secretKey" not in str(answer)
    assert "SENSITIVE_PLACEHOLDER" not in str(answer)


def test_plugin_conditions_and_loops_are_not_executed_or_assumed_unconditional():
    src = '''def _defineParams(self, form):
    form.addSection(label="Plots")
    if self.protocol.IS_3D:
        form.addParam("dynamic", params.IntParam, label="Dynamic")
    for _ in self.other:
        form.addParam("repeated", params.IntParam, label="Repeat")
    form.addParam("safe", params.IntParam, label="Safe")
'''
    out = forms().parseProtocolViewerStaticFormSource(src)
    assert out["fieldsDiscovered"] == 1
    assert out["dynamicDefinitionsSkipped"] == 2
    assert "dynamic\"" not in str(out)
    assert "repeated\"" not in str(out)
    assert out["requiresRuntimeEvaluation"] is True


def test_computed_defaults_cannot_execute_code_or_leak_source():
    src = '''def _defineParams(self, form):
    form.addSection(label="Safety")
    form.addParam("x", params.IntParam, label="X", default=__import__("os").system("exit 99"))
'''
    answer = forms().parseProtocolViewerStaticFormSource(src)
    field = answer["sections"][0]["fields"][0]
    assert field["name"] == "x"
    assert field["unresolvedDefault"] is True
    assert "__import__" not in str(answer)
    assert answer["renderable"] is False


def test_invalid_enum_choices_are_omitted_without_eval():
    src = '''def _defineParams(self, form):
    form.addSection(label="Modes")
    form.addParam("mode", params.EnumParam, choices=self.dynamicOptions(), label="Mode")
    form.addParam("other", params.StringParam, label="Other")
'''
    answer = forms().parseProtocolViewerStaticFormSource(src)
    assert answer["fieldsDiscovered"] == 1
    assert answer["dynamicDefinitionsSkipped"] == 1
    assert "mode\"" not in str(answer)


def test_conditions_are_only_marked_not_interpreted():
    src = '''def _defineParams(self, form):
    form.addSection(label="Variables")
    form.addParam("range", params.NumericRangeParam, label="Range", condition="mode == 1")
'''
    field = forms().parseProtocolViewerStaticFormSource(src)["sections"][0]["fields"][0]
    assert field["hasCondition"] is True
    assert "condition" not in field


def test_unknown_types_and_duplicate_fields_fail_closed():
    src = '''def _defineParams(self, form):
    form.addSection(label="Options")
    form.addParam("external", EvilParam, label="Unsafe")
    form.addParam("x", params.StringParam, label="X")
    form.addParam("x", params.StringParam, label="X duplicated")
'''
    answer = forms().parseProtocolViewerStaticFormSource(src)
    assert answer["fieldsDiscovered"] == 1
    assert answer["dynamicDefinitionsSkipped"] == 2


def test_invalid_source_too_large_or_missing_definition_is_unavailable():
    fn = forms().parseProtocolViewerStaticFormSource
    assert fn("not valid python:")["status"] == "unavailable"
    assert fn("x" * 140000)["status"] == "unavailable"
    assert fn("def other(self, form): pass")["status"] == "unavailable"


def test_scans_registered_protocolviewer_only_without_invoking_code():
    _, _, _, registry, candidates = fake_setup()
    answer = forms().describeProtocolViewerStaticForms(candidates, registry)
    assert answer["formSchemaSummary"] == {
        "protocolViewerCount": 1, "staticPreviewCount": 1,
        "executableFormCount": 0,
    }
    assert get_candidate(answer, "SimpleViewer")["formSchema"] is None
    schema = get_candidate(answer, "FormViewer")["formSchema"]
    assert schema["fieldsDiscovered"] == 5
    assert schema["hiddenFields"] == 1
    assert schema["sections"][0]["groups"][0]["fields"][0]["choices"] == ["slices", "chimera"]
    assert answer["autoLaunchAllowed"] is False


def test_aliases_do_not_duplicate_form_descriptors():
    _, _, cls, registry, candidates = fake_setup()
    registry["AliasForForm"] = cls
    answer = forms().describeProtocolViewerStaticForms(candidates, registry)
    assert answer["formSchemaSummary"]["protocolViewerCount"] == 1


def test_forged_candidate_identity_is_rejected():
    _, _, _, registry, candidates = fake_setup()
    candidates["viewers"][0]["id"] = "other.viewers.UntrustedViewer"
    with pytest.raises(forms().ProtocolViewerFormSchemaError) as exc:
        forms().describeProtocolViewerStaticForms(candidates, registry)
    assert exc.value.code == "unregistered_viewer"


def test_source_not_available_is_safe_and_does_not_modify_candidates():
    _, _, _, registry, candidates = fake_setup()
    original = deepcopy(candidates)
    answer = forms().describeProtocolViewerStaticForms(
        candidates, registry, source_loader=lambda f: (_ for _ in ()).throw(OSError("missing"))
    )
    assert answer["formSchemaSummary"]["staticPreviewCount"] == 0
    assert get_candidate(answer, "FormViewer")["formSchema"]["status"] == "unavailable"
    assert candidates == original


def test_viewer_source_is_not_a_web_execution_permission():
    _, _, _, registry, candidates = fake_setup()
    candidates["autoLaunchAllowed"] = True
    candidates["selectedViewerId"] = candidates["viewers"][0]["id"]
    answer = forms().describeProtocolViewerStaticForms(candidates, registry)
    assert answer["autoLaunchAllowed"] is False
    assert answer["selectedViewerId"] is None
    assert get_candidate(answer, "FormViewer")["formSchema"]["renderable"] is False
    assert get_candidate(answer, "FormViewer")["formSchema"]["actionExecutionAllowed"] is False


def test_persisted_endpoint_adds_static_preview_without_reading_protocol_params():
    from app.backend.api.services.protocol_viewer_persisted_resolution_service import (
        resolvePersistedProtocolViewerCandidates,
    )
    prot, _, form_viewer, registry, _ = fake_setup()
    calls = []

    class Mapper:
        def getProjectProtocolByProtocolId(self, *, projectId, protocolId):
            calls.append((projectId, protocolId))
            return {"id": 41, "projectId": projectId, "protocolId": str(protocolId),
                    "protocolClassName": "FakeProt", "status": "finished",
                    "params": {"secret": "SECRET_NOT_FOR_CLIENT"}}

        def getProjectProtocolByDbId(self, **kwargs):
            raise AssertionError("Must never fall back to DB ID")

    result = resolvePersistedProtocolViewerCandidates(
        mapper=Mapper(), project_id=22, protocol_id=543,
        snapshot={"protocols": {"FakeProt": prot}, "viewers": registry,
                  "preferredViewers": {}, "webAdapters": {}},
    )
    assert calls == [(22, 543)]
    schema = get_candidate(result, "FormViewer")["formSchema"]
    assert schema["status"] == "static-preview"
    assert schema["renderable"] is False
    assert result["formSchemaSummary"]["protocolViewerCount"] == 1
    assert result["autoLaunchAllowed"] is False
    assert "SECRET_NOT_FOR_CLIENT" not in str(result)
