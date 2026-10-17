"""RED 165: AST evidence must never become scientific association/execution."""
from __future__ import annotations

import copy
import importlib

import pytest
from pyworkflow.viewer import ProtocolViewer
from app.backend.api.services.protocol_viewer_inventory_service import _class_identity

MODULE = "app.backend.api.services.protocol_viewer_static_action_reference_service"


def service():
    return importlib.import_module(MODULE)


VISUALIZE = '''
def _getVisualizeDict(self):
    return {"displayVolume": self._viewVolume, "showPlot": self._viewPlot}
'''
HANDLERS = {
    "_viewVolume": '''
def _viewVolume(self):
    result = self.protocol.outputVolumes
    return result
''',
    "_viewPlot": '''
def _viewPlot(self):
    return self.protocol._getExtraPath("plot.svg")
''',
}


def parse(vis=VISUALIZE, handlers=None, action="displayVolume"):
    return service().parseProtocolViewerActionResourceReferences(vis, HANDLERS if handlers is None else handlers, action)


class FixtureViewer(ProtocolViewer):
    def _getVisualizeDict(self):
        return {"displayVolume": self._viewVolume, "showPlot": self._viewPlot}

    def _viewVolume(self):
        result = self.protocol.outputVolumes
        return result

    def _viewPlot(self):
        return self.protocol._getExtraPath("plot.svg")


def snapshot():
    actions = [{"id": id_, "fieldName": id_, "label": label, "control": "label", "kind": "visualize",
                "previewOnly": True, "requiresRuntimeEvaluation": True, "executionAllowed": False}
               for id_, label in (("displayVolume", "Display volume"), ("showPlot", "Show plot"))]
    web = [{"id": item["id"], "fieldName": item["id"], "label": item["label"], "control": "label",
            "intent": "visualize", "source": "static-ast", "adapter": None, "adapterStatus": "missing",
            "availability": "blocked", "blockers": ["action_adapter_missing", "runtime_instance_not_verified", "web_action_not_implemented"],
            "requiresRuntimeVerification": True, "renderable": False, "executionAllowed": False} for item in actions]
    return {"autoLaunchAllowed": False, "viewers": [{"id": _class_identity(FixtureViewer),
        "formSchema": {"status": "static-preview", "sections": [{"fields": [
            {"name": a["id"], "label": a["label"], "control": "label"} for a in actions]}]},
        "actionSchema": {"status": "static-preview", "source": "static-ast", "actions": actions,
                         "renderable": False, "executionAllowed": False},
        "webActionContracts": {"status": "advisory-only", "source": "static-ast", "actions": web, "actionCount": len(web),
                               "readyCount": 0, "renderable": False, "executionAllowed": False},
        "webReady": False, "executionAllowed": False, "renderable": False}]}


DEFAULT = object()

def run(snap=DEFAULT, reg=None, **kwargs):
    return service().describeProtocolViewerStaticResourceReferences(
        snapshot() if snap is DEFAULT else snap,
        {"fixture": FixtureViewer} if reg is None else reg, **kwargs)


def test_parse_recognizes_only_direct_output_reference():
    result = parse()
    assert result["status"] == "source-reference-observed"
    assert result["candidateOutputNames"] == ["outputVolumes"]
    assert result["bindingVerified"] is False
    assert result["scientificSemanticsVerified"] is False
    assert result["availability"] == "blocked"
    assert result["renderable"] is False and result["executionAllowed"] is False


def test_plot_path_must_not_count_as_output_or_be_disclosed():
    result = parse(action="showPlot")
    assert result["status"] == "no-direct-reference-observed"
    assert result["candidateOutputNames"] == []
    assert "plot.svg" not in str(result)


@pytest.mark.parametrize("body,expected", [
    ("result = self.protocol.outputClasses", ["outputClasses"]),
    ("return self.protocol.outputParticles, self.protocol.outputClasses", ["outputClasses", "outputParticles"]),
    ("return self.protocol.outputClasses, self.protocol.outputClasses", ["outputClasses"]),
    ("# self.protocol.outputSecret\nreturn None", []),
    ("return 'self.protocol.outputSecret'", []),
    ("return self.protocol._getExtraPath('outputClasses')", []),
    ("return other.outputClasses", []),
    ("return self.other.outputClasses", []),
    ("self.protocol.outputClasses = object()", []),
    ("return self.protocol.outputClasses()", []),
    ("return self.protocol.outputfoo", []),
    ("return self.protocol.output_foo", ["output_foo"]),
    ("return self.protocol.outputData[0]", ["outputData"]),
    ("return getattr_else(self.protocol, 'outputData')", []),
])
def test_only_exact_direct_ast_reads(body, expected):
    source = "def _viewVolume(self):\n" + "\n".join("    " + line for line in body.splitlines()) + "\n"
    result = parse(handlers={"_viewVolume": source}, action="displayVolume")
    assert result["candidateOutputNames"] == expected
    assert result["bindingVerified"] is False


@pytest.mark.parametrize("body", [
    "return getattr(self.protocol, 'outputData')",
    "return eval('self.protocol.outputData')",
    "return self.protocol.outputData, exec('1')",
    "return self.protocol.outputData, vars(self.protocol)",
    "return self.protocol.outputData, globals()",
    "return self.protocol.outputData, locals()",
    "return self.protocol.outputData, __import__('os')",
    "return self.protocol.outputData, self.__getattribute__('protocol')",
    "import os\nreturn self.protocol.outputData",
    "from os import system\nreturn self.protocol.outputData",
    "global temp\nreturn self.protocol.outputData",
    "del self.protocol.outputData\nreturn self.protocol.outputData",
])
def test_dynamic_constructs_fail_closed(body):
    source = "def _viewVolume(self):\n" + "\n".join("    " + line for line in body.splitlines()) + "\n"
    result = parse(handlers={"_viewVolume": source})
    assert result["status"] == "indeterminate"
    assert result["candidateOutputNames"] == []
    assert result["executionAllowed"] is False


@pytest.mark.parametrize("mapping", [
    "return {'displayVolume': evil}",
    "return {x: self._viewVolume}",
    "return {'displayVolume': lambda: self.protocol.outputData}",
    "return {'displayVolume': self._viewVolume, 'displayVolume': self._viewPlot}",
    "mapping = {'displayVolume': self._viewVolume}\nmapping.update({'showPlot': self._viewPlot})\nreturn mapping",
    "mapping = {'displayVolume': self._viewVolume}\nmapping = evil\nreturn mapping",
    "if condition:\n    return {'displayVolume': self._viewVolume}\nreturn {}",
    "return dict(displayVolume=self._viewVolume)",
    "return {'displayVolume': self._viewVolume}; return {}",
    "return {'displayVolume': other._viewVolume}",
])
def test_dynamic_or_ambiguous_action_map_fails_closed(mapping):
    vis = "def _getVisualizeDict(self):\n" + "\n".join("    " + line for line in mapping.splitlines()) + "\n"
    result = parse(vis=vis)
    assert result["status"] == "indeterminate"
    assert result["candidateOutputNames"] == []


def test_local_dictionary_then_return_supported():
    result = parse(vis="def _getVisualizeDict(self):\n    actions = {'displayVolume': self._viewVolume}\n    return actions\n")
    assert result["candidateOutputNames"] == ["outputVolumes"]


@pytest.mark.parametrize("bad", [
    "def _getVisualizeDict(self):\n  broken???", "", None, 123, "x" * 131073,
    "async def _getVisualizeDict(self):\n    return {'displayVolume': self._viewVolume}",
    "def _getVisualizeDict(p):\n    return {'displayVolume': p._viewVolume}",
    "def _getVisualizeDict(self):\n    return {'displayVolume': self._viewVolume}\ndef _getVisualizeDict(self):\n    return {}",
])
def test_invalid_source_fails_closed(bad):
    result = parse(vis=bad)
    assert result["status"] == "indeterminate"
    assert result["executionAllowed"] is False


@pytest.mark.parametrize("id_", ["../path", "", "___", "displayVolume/../../etc", 5, True, None, "x" * 130])
def test_invalid_action_identity_fails_closed(id_):
    result = parse(action=id_)
    assert result["candidateOutputNames"] == []
    assert result["renderable"] is False and result["executionAllowed"] is False


def test_wrapper_ties_evidence_to_registered_viewer_and_static_action():
    source = snapshot()
    before = copy.deepcopy(source)
    result = run(source)
    assert source == before
    assert result["viewers"][0]["staticResourceReferences"]["actionCount"] == 2
    actions = result["viewers"][0]["staticResourceReferences"]["actions"]
    assert actions[0]["candidateOutputNames"] == ["outputVolumes"]
    assert actions[1]["candidateOutputNames"] == []
    assert all(x["bindingVerified"] is False and x["executionAllowed"] is False for x in actions)
    assert result["autoLaunchAllowed"] is False
    assert "_viewVolume" not in repr(actions)


@pytest.mark.parametrize("mutator", [
    lambda s: s["viewers"][0]["actionSchema"].update(status="ready"),
    lambda s: s["viewers"][0]["actionSchema"].update(executionAllowed=True),
    lambda s: s["viewers"][0]["webActionContracts"].update(readyCount=1),
    lambda s: s["viewers"][0]["webActionContracts"].update(executionAllowed=True),
    lambda s: s["viewers"][0]["webActionContracts"]["actions"][0].update(executionAllowed=True),
    lambda s: s["viewers"][0]["webActionContracts"]["actions"][0].update(availability="available"),
    lambda s: s["viewers"][0]["webActionContracts"]["actions"][0].update(id="wrongAction"),
    lambda s: s["viewers"][0]["webActionContracts"]["actions"][0].update(label="forged"),
    lambda s: s["viewers"][0]["webActionContracts"]["actions"].append(copy.deepcopy(s["viewers"][0]["webActionContracts"]["actions"][0])),
    lambda s: s["viewers"][0]["actionSchema"]["actions"].append(copy.deepcopy(s["viewers"][0]["actionSchema"]["actions"][0])),
])
def test_forged_or_duplicate_contracts_have_no_evidence(mutator):
    snap = snapshot(); mutator(snap)
    output = run(snap)
    assert output["viewers"][0]["staticResourceReferences"]["actionCount"] == 0
    assert output["viewers"][0]["staticResourceReferences"]["verifiedBindings"] == 0


def test_actions_do_not_expose_opaque_source_text_or_file_paths():
    output = run()
    report = output["viewers"][0]["staticResourceReferences"]
    assert "plot.svg" not in repr(report)
    assert "_getExtraPath" not in repr(report)
    assert "_viewPlot" not in repr(report)
    assert "__dict__" not in repr(report)


def test_unregistered_or_forged_viewer_rejected_before_loading_source():
    calls = []
    snap = snapshot(); snap["viewers"][0]["id"] = "evil.viewers.FakeViewer"
    with pytest.raises(service().ProtocolViewerStaticReferenceError) as error:
        run(snap, source_loader=lambda func: calls.append(func) or VISUALIZE)
    assert error.value.code == "unregistered_viewer"
    assert calls == []


@pytest.mark.parametrize("bad", [None, {}, [], "bad", {"viewers": [None]}, {"viewers": "bad"}])
def test_invalid_candidate_structure_rejected(bad):
    with pytest.raises(service().ProtocolViewerStaticReferenceError):
        run(bad)


def test_non_callable_loader_rejected():
    with pytest.raises(service().ProtocolViewerStaticReferenceError) as err:
        run(source_loader="exec('1')")
    assert err.value.code == "invalid_source_loader"


def test_unavailable_source_keeps_both_actions_indeterminate():
    def unavailable(_func):
        raise OSError("no source")
    result = run(source_loader=unavailable)["viewers"][0]["staticResourceReferences"]
    assert all(a["status"] == "indeterminate" and a["candidateOutputNames"] == [] for a in result["actions"])
    assert result["executionAllowed"] is False


def test_no_file_or_database_or_plugin_callbacks_executed(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("unsafe operation")
    monkeypatch.setattr(FixtureViewer, "_viewVolume", fail)
    monkeypatch.setattr(FixtureViewer, "_viewPlot", fail)
    result = run()
    assert result["viewers"][0]["staticResourceReferences"]["verifiedBindings"] == 0
    assert result["viewers"][0]["staticResourceReferences"]["executionAllowed"] is False
