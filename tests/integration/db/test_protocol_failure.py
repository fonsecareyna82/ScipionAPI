"""Why a protocol failed, against the migrated database: its status, its failed steps and its logs."""
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.backend.api.services import protocol_failure
from app.backend.mapper.postgresql import PostgresqlFlatMapper


@pytest.fixture
def project(postgresqlIntegrationDb, postgresqlMigratedEnv):
    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    userId = flat.insertUser(email="fail-%s@example.com" % uuid4().hex, hashedPassword="test", firstName="Ana",
                             lastName="Test", institution=None, role="user", isActive=True, isVerified=True,
                             verificationCode="")
    projectId = flat.insertProject(ownerId=userId, name="/tmp/fail-%s/P" % uuid4().hex, description="",
                                   status="active")

    def protocol(protocolId, status, stepError=None):
        row = db.executeReturningOne(
            'INSERT INTO protocols ("protocolId", "projectId", "protocolClassName", params, status) '
            "VALUES (%s, %s, %s, %s::jsonb, %s) RETURNING id",
            (str(protocolId), projectId, "ProtRefine", json.dumps({}), status))
        if stepError is not None:
            db.execute('INSERT INTO protocol_steps ("projectId", "protocolDbId", "protocolId", "stepIndex", name, '
                       'status, error) VALUES (%s, %s, %s, 1, %s, %s, %s)',
                       (projectId, row["id"], str(protocolId), "refineStep", "failed", stepError))

    try:
        yield SimpleNamespace(db=db), projectId, protocol
    finally:
        db.execute('DELETE FROM protocols WHERE "projectId" = %s', (projectId,))
        db.execute('DELETE FROM projects WHERE id = %s', (projectId,))
        db.execute('DELETE FROM users WHERE id = %s', (userId,))


class _Service:
    def _resolveScipionProtocolIdStrict(self, mapper, projectId, protocolId):
        return int(protocolId)

    def _resolvePostgresqlProjectPathForFilesystem(self, *args, **kwargs):
        return None


def test_AFailedProtocolIsExplainedFromItsLogsAndSteps(project, tmp_path, monkeypatch):
    mapper, projectId, protocol = project
    protocol(5, "failed", stepError="Command 'refine' returned non-zero exit status 1.")
    protocol(6, "finished")
    (tmp_path / "run.stderr").write_text("std::bad_alloc\n")
    monkeypatch.setattr(protocol_failure.RuntimeProtocolLogService, "resolvePostgresqlProtocolLogPaths",
                        lambda self, **kwargs: {"paths": {"stdout": None, "stderr": str(tmp_path / "run.stderr")}})

    explained = protocol_failure.explainProtocolFailure(mapper, _Service(), projectId, 5)
    assert explained["failed"] and explained["cause"]["id"] == "machine-out-of-memory"
    assert explained["error"] == {"text": "std::bad_alloc", "line": 1, "channel": "stderr"}
    assert explained["stepErrors"] == ["Command 'refine' returned non-zero exit status 1."]

    assert protocol_failure.explainProtocolFailure(mapper, _Service(), projectId, 6) == {"failed": False}
    assert protocol_failure.explainProtocolFailure(mapper, _Service(), projectId, 99) == {"failed": False}
