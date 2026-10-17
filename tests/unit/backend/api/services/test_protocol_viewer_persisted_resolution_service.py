"""RED 115: read-only viewer selection bound to a persisted PostgreSQL run."""
import importlib
from pathlib import Path
from types import SimpleNamespace
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[5]


def mod():
    return importlib.import_module(
        "app.backend.api.services.protocol_viewer_persisted_resolution_service"
    )


def sample():
    from pyworkflow.protocol import Protocol
    from pyworkflow.viewer import Viewer

    class Base(Protocol):
        pass
    class Derived(Base):
        pass
    Base.__module__ = "sample.protocols"
    Derived.__module__ = "sample.protocols"

    class ABaseViewer(Viewer):
        _targets = [Base]
        _environments = ["tkinter"]
        def __init__(self, *args, **kwargs):
            raise AssertionError("viewer construction is forbidden")
        def _visualize(self, obj):
            raise AssertionError("viewer execution is forbidden")

    class BDerivedViewer(Viewer):
        _targets = [Derived]
        _environments = ["tkinter"]
        @classmethod
        def can_handle_this_instance(cls, instance):
            raise AssertionError("instance condition must not execute in HTTP discovery")

    ABaseViewer.__module__ = "pluginone.viewers"
    BDerivedViewer.__module__ = "plugintwo.viewers"
    registry = {"Base": Base, "Derived": Derived}
    viewers = {"ABaseViewer": ABaseViewer, "BDerivedViewer": BDerivedViewer}
    snapshot = {"protocols": registry, "viewers": viewers, "preferredViewers": {}}
    row = {"id": 812, "projectId": 7, "protocolId": "142", "protocolClassName": "Derived",
           "status": "finished", "params": {"secret": "must-not-leak"},
           "workingDir": "/secret/path"}
    return snapshot, row


class Reader:
    def __init__(self, row):
        self.row = row
        self.calls = []
    def getProjectProtocolByProtocolId(self, *, projectId, protocolId):
        self.calls.append((projectId, protocolId))
        return self.row
    def getProjectProtocolByDbId(self, **kwargs):
        raise AssertionError("Do not fall back to PostgreSQL DB protocol id")


def resolve(row=None, *, project_id=7, protocol_id=142, snapshot=None):
    default_snapshot, default_row = sample()
    db = Reader(default_row if row is None else row)
    answer = mod().resolvePersistedProtocolViewerCandidates(
        mapper=db, project_id=project_id, protocol_id=protocol_id,
        snapshot=snapshot or default_snapshot,
    )
    return answer, db


def test_uses_real_persisted_identity_and_respects_specific_viewer_priority():
    answer, reader = resolve()
    assert reader.calls == [(7, 142)]
    assert answer["projectId"] == 7
    assert answer["protocolId"] == "142"
    assert answer["protocolDbId"] == 812
    assert answer["protocolStatus"] == "finished"
    assert answer["dataSource"] == "postgresql"
    assert answer["selectionMode"] == "persisted-protocol-class"
    assert [v["name"] for v in answer["viewers"]] == ["BDerivedViewer", "ABaseViewer"]
    assert answer["viewers"][1]["matchReason"] == "inherited"


def test_does_not_call_untrusted_instance_hooks_or_construct_plugin_objects():
    answer, _ = resolve()
    assert answer["instanceMaterialized"] is False
    assert answer["instanceChecksApplied"] is False
    assert answer["autoLaunchAllowed"] is False
    assert answer["selectedViewerId"] is None
    assert answer["viewers"][0]["instanceConditionUnverified"] is True
    assert all(v["runtimeEligibility"] == "unverified" for v in answer["viewers"])
    assert all(v["webSupport"] == "unassessed" for v in answer["viewers"])


def test_no_persisted_parameters_working_paths_or_secrets_are_disclosed():
    answer, _ = resolve()
    assert "must-not-leak" not in str(answer)
    assert "/secret/path" not in str(answer)
    assert "params" not in answer


def test_missing_protocol_returns_not_found_without_db_id_fallback():
    snapshot, _ = sample()
    reader = Reader(None)
    with pytest.raises(mod().PersistedProtocolViewerError) as exc:
        mod().resolvePersistedProtocolViewerCandidates(
            mapper=reader, project_id=7, protocol_id=142, snapshot=snapshot
        )
    assert exc.value.code == "not_found"
    assert reader.calls == [(7, 142)]


def test_cross_project_row_or_protocol_id_mismatch_fails_closed():
    snapshot, row = sample()
    for bad in (dict(row, projectId=9), dict(row, protocolId="143")):
        with pytest.raises(mod().PersistedProtocolViewerError) as exc:
            resolve(row=bad, snapshot=snapshot)
        assert exc.value.code == "identity_mismatch"


def test_incomplete_postgresql_row_fails_closed():
    snapshot, row = sample()
    for bad in (dict(row, id=None), dict(row, protocolClassName=""),
                {k: v for k, v in row.items() if k != "projectId"}):
        with pytest.raises(mod().PersistedProtocolViewerError) as exc:
            resolve(row=bad, snapshot=snapshot)
        assert exc.value.code == "invalid_row"


def test_unknown_protocol_class_does_not_trigger_imports_or_guess_other_classes():
    snapshot, row = sample()
    with pytest.raises(mod().PersistedProtocolViewerError) as exc:
        resolve(row=dict(row, protocolClassName="untrusted.pkg.Evil"), snapshot=snapshot)
    assert exc.value.code == "unregistered_class"


def test_ambiguous_class_name_requires_disambiguation():
    snapshot, row = sample()
    from pyworkflow.protocol import Protocol
    a = type("SameName", (Protocol,), {"__module__": "pluginA.protocols"})
    b = type("SameName", (Protocol,), {"__module__": "pluginB.protocols"})
    snapshot["protocols"].update({"a": a, "b": b})
    with pytest.raises(mod().PersistedProtocolViewerError) as exc:
        resolve(row=dict(row, protocolClassName="SameName"), snapshot=snapshot)
    assert exc.value.code == "ambiguous_class"


def test_invalid_numeric_identifiers_and_missing_mapper_fail_before_query():
    snapshot, row = sample()
    for invalid in (0, -1, True):
        with pytest.raises(mod().PersistedProtocolViewerError) as exc:
            resolve(row=row, project_id=invalid, snapshot=snapshot)
        assert exc.value.code == "invalid_identity"
    with pytest.raises(mod().PersistedProtocolViewerError) as exc:
        mod().resolvePersistedProtocolViewerCandidates(
            mapper=None, project_id=7, protocol_id=142, snapshot=snapshot
        )
    assert exc.value.code == "missing_mapper"


def test_project_route_authenticates_and_checks_authorization_before_pg_read():
    source = _REPO_ROOT.joinpath("app/backend/api/routers/project_router.py").read_text(encoding="utf-8")
    start = source.index('@router.get("/{projectId}/protocols/{protocolId}/viewers", response_model=Any)')
    end = source.index('@router.post(', start)
    handler = source[start:end]
    assert "Depends(getCurrentUser)" in handler
    assert "Depends(getMapper)" in handler
    assert "service.getProjectDbRow(mapper, projectId, currentUser)" in handler
    assert "getScipionViewerResolutionSnapshot()" in handler
    assert "resolvePersistedProtocolViewerCandidates(" in handler
    assert handler.index("getProjectDbRow(") < handler.index("getScipionViewerResolutionSnapshot()")
    assert handler.index("getProjectDbRow(") < handler.index("resolvePersistedProtocolViewerCandidates(")
    assert "loadPostgresqlRuntimeProjectForMutation" not in handler
    assert "getProtocolBy" not in handler
