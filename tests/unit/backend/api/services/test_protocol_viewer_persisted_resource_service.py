"""RED 159: verified PostgreSQL resource identity is not callback authorization."""
from __future__ import annotations

import importlib
from copy import deepcopy

import pytest


MODULE = "app.backend.api.services.protocol_viewer_persisted_resource_service"


def subject():
    return importlib.import_module(MODULE)


class ProtocolMapper:
    def __init__(self, row=None):
        self.row = row if row is not None else {"id": 812, "projectId": 7, "protocolId": "142", "protocolClassName": "PluginProtocol", "params": {"secret": "NEVER_LEAK"}}
        self.calls = []

    def getProjectProtocolByProtocolId(self, *, projectId, protocolId):
        self.calls.append((projectId, protocolId))
        return self.row

    def getProjectProtocolByDbId(self, **kwargs):
        raise AssertionError("Public Scipion ID must never be interpreted as protocol DB ID")


class SetMapper:
    def __init__(self, stored=None):
        self.stored = stored if stored is not None else {"id": 56, "projectId": 7, "protocolDbId": 812, "outputName": "outputParticles", "setClassName": "SetOfParticles", "properties": {"runtimeReserved": False, "fileName": "/private/path"}, "items": [{"secret": "NEVER_SERIALIZE"}], "columns": [{"secret": "SECRET_COLUMN"}]}
        self.calls = []

    def getStoredSet(self, **kwargs):
        self.calls.append(kwargs)
        return self.stored

    def listProjectSetOutputSummaryRows(self, *args, **kwargs):
        raise AssertionError("No project-wide Set scan")


def resolve(*, protocol=None, stored=None, project_id=7, protocol_id=142, output_name="outputParticles"):
    pm = ProtocolMapper(protocol)
    sm = SetMapper(stored)
    result = subject().resolvePersistedProtocolViewerOutputResource(mapper=pm, set_mapper=sm, project_id=project_id, protocol_id=protocol_id, output_name=output_name)
    return result, pm, sm


def error_code(**kwargs):
    with pytest.raises(subject().ProtocolViewerResourceResolutionError) as exc:
        resolve(**kwargs)
    return exc.value.code


def test_exact_identity_only_and_no_set_rows():
    result, pm, sm = resolve()
    assert pm.calls == [(7, 142)]
    assert sm.calls == [{"projectId": 7, "protocolDbId": 812, "outputName": "outputParticles", "limit": 0, "offset": 0}]
    assert result["projectId"] == 7 and result["protocolId"] == "142"
    assert result["outputName"] == "outputParticles" and result["resourceKind"] == "persisted-set"
    assert result["source"] == "postgresql" and result["status"] == "metadata-verified"


@pytest.mark.parametrize("class_name,kind", [
    ("SetOfParticles", "metadata"), ("SetOfMicrographs", "metadata"),
    ("SetOfClasses2D", "metadata"), ("SetOfClasses3D", "metadata"),
    ("SetOfVolumes", "volume"), ("SetOfFSCs", "fsc"), ("SetOfCTF", "ctf"),
    ("SetOfCoordinates", "coords2d"),
    ("SetOfCoordinates3D", "integrated-tomography"),
    ("SetOfTiltSeries", "integrated-tomography"),
    ("SetOfCTFTomoSeries", "integrated-tomography"),
    ("SetOfTomograms", "integrated-tomography"),
])
def test_only_exact_existing_browser_viewers_are_classified(class_name, kind):
    stored = SetMapper().stored.copy()
    stored["setClassName"] = class_name
    result, _, _ = resolve(stored=stored)
    assert result["webViewerKind"] == kind and result["outputClassName"] == class_name
    assert result["availability"] == "blocked"
    assert result["executionAllowed"] is False and result["renderable"] is False
    assert result["instanceVerified"] is False
    assert result["blockers"] == ["action_binding_not_verified", "web_action_not_implemented"]


@pytest.mark.parametrize("name", ["../other", "file.mrc", "/tmp/file", "output/other", "foo bar", "", " a", "output:particles", "x" * 129, "_private"])
def test_refuses_paths_and_arbitrary_output_names_before_lookup(name):
    pm, sm = ProtocolMapper(), SetMapper()
    with pytest.raises(subject().ProtocolViewerResourceResolutionError) as exc:
        subject().resolvePersistedProtocolViewerOutputResource(mapper=pm, set_mapper=sm, project_id=7, protocol_id=142, output_name=name)
    assert exc.value.code == "invalid_output_name"
    assert pm.calls == sm.calls == []


@pytest.mark.parametrize("project_id,protocol_id", [(0, 142), (True, 142), (7, -1), (7, True), (7.0, 142), (7, "142")])
def test_invalid_public_identity_never_queries_database(project_id, protocol_id):
    pm, sm = ProtocolMapper(), SetMapper()
    with pytest.raises(subject().ProtocolViewerResourceResolutionError) as exc:
        subject().resolvePersistedProtocolViewerOutputResource(mapper=pm, set_mapper=sm, project_id=project_id, protocol_id=protocol_id, output_name="outputParticles")
    assert exc.value.code == "invalid_identity" and pm.calls == sm.calls == []


def test_missing_protocol_fails_without_set_access():
    pm, sm = ProtocolMapper({}), SetMapper()
    with pytest.raises(subject().ProtocolViewerResourceResolutionError) as exc:
        subject().resolvePersistedProtocolViewerOutputResource(mapper=pm, set_mapper=sm, project_id=7, protocol_id=142, output_name="outputParticles")
    assert exc.value.code == "invalid_persisted_identity"
    assert sm.calls == []


@pytest.mark.parametrize("patch", [{"projectId": 8}, {"protocolId": "143"}, {"id": 0}, {"id": True}, {"protocolId": None}])
def test_cannot_mix_protocol_identities(patch):
    protocol = deepcopy(ProtocolMapper().row)
    protocol.update(patch)
    assert error_code(protocol=protocol) in {"invalid_persisted_identity", "protocol_identity_mismatch"}


@pytest.mark.parametrize("patch", [{"projectId": 8}, {"protocolDbId": 142}, {"outputName": "otherOutput"}, {"id": 0}, {"id": True}])
def test_cannot_rebind_other_persisted_set(patch):
    stored = deepcopy(SetMapper().stored)
    stored.update(patch)
    assert error_code(stored=stored) in {"invalid_persisted_identity", "output_identity_mismatch"}


@pytest.mark.parametrize("reserved", [True, "true", "1", 1, {}, [], "not-known"])
def test_unpublished_or_malformed_reservation_is_rejected(reserved):
    stored = deepcopy(SetMapper().stored)
    stored["properties"] = {"runtimeReserved": reserved}
    assert error_code(stored=stored) == "output_not_published"


def test_absent_set_never_falls_back_to_files_or_sqlite():
    pm, sm = ProtocolMapper(), SetMapper()
    sm.stored = None
    with pytest.raises(subject().ProtocolViewerResourceResolutionError) as exc:
        subject().resolvePersistedProtocolViewerOutputResource(mapper=pm, set_mapper=sm, project_id=7, protocol_id=142, output_name="outputParticles")
    assert exc.value.code == "output_not_found"
    assert sm.calls[0]["limit"] == 0


@pytest.mark.parametrize("kind", ["UntrustedPluginThing", "Volume", "SetOfFSCs/../../secret", "SetOfVolumesExtra", None, 1])
def test_unknown_types_are_not_inferred_by_name(kind):
    stored = deepcopy(SetMapper().stored)
    stored["setClassName"] = kind
    assert error_code(stored=stored) == "unsupported_output_class"


def test_does_not_leak_any_persisted_data_except_checked_identity_and_type():
    result, _, _ = resolve()
    text = str(result)
    for secret in ["NEVER_LEAK", "NEVER_SERIALIZE", "SECRET_COLUMN", "/private/path", "scipionItemId", "fileName", "secret"]:
        assert secret not in text
    assert "setId" not in result and "protocolDbId" not in result
    assert set(result) == {"status", "source", "projectId", "protocolId", "outputName", "resourceKind", "outputClassName", "webViewerKind", "availability", "blockers", "instanceVerified", "renderable", "executionAllowed"}


def test_input_rows_remain_unmodified_and_spoofed_execution_ignored():
    row, stored = deepcopy(ProtocolMapper().row), deepcopy(SetMapper().stored)
    stored.update({"executionAllowed": True, "renderable": True, "url": "https://attacker.invalid", "handler": "run"})
    source_row, source_set = deepcopy(row), deepcopy(stored)
    result, _, _ = resolve(protocol=row, stored=stored)
    assert row == source_row and stored == source_set
    assert result["executionAllowed"] is False and result["renderable"] is False
    assert "attacker" not in str(result) and "handler" not in str(result)


def test_no_plugin_actions_or_runtime_materialization_ever_called():
    result, _, _ = resolve()
    assert result["availability"] == "blocked"
    assert result["instanceVerified"] is False
    assert "callback" not in str(result)
