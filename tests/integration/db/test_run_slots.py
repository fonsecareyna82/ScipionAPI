"""A user's run slots, against the migrated database: what counts, and the runtime values the worker writes."""
import json
from uuid import uuid4

import pytest

from app.backend.mapper.postgresql import PostgresqlFlatMapper


@pytest.fixture
def runs(postgresqlIntegrationDb, postgresqlMigratedEnv):
    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    userId = flat.insertUser(email="slots-%s@example.com" % uuid4().hex, hashedPassword="test", firstName="Ana",
                             lastName="Test", institution=None, role="user", isActive=True, isVerified=True,
                             verificationCode="")
    projectId = flat.insertProject(ownerId=userId, name="/tmp/slots-%s" % uuid4().hex, description="",
                                   status="active")

    def protocol(protocolId, status, **runtime):
        metadata = dict({"launchedByUserId": str(userId), "executionId": "execution-%s" % protocolId}, **runtime)
        db.execute('INSERT INTO protocols ("protocolId", "projectId", "protocolClassName", params, status) '
                   "VALUES (%s, %s, %s, %s::jsonb, %s)",
                   (str(protocolId), projectId, "ProtMotionCorr", json.dumps({"_scipionWebRuntime": metadata,
                                                                              "gpuList": "0"}), status))

    try:
        yield db, flat, userId, projectId, protocol
    finally:
        db.execute('DELETE FROM projects WHERE id = %s', (projectId,))
        db.execute('DELETE FROM users WHERE id = %s', (userId,))


def test_StreamingRunsTakeNoSlot(runs):
    db, flat, userId, projectId, protocol = runs
    protocol(2, "running")
    protocol(3, "running", slotExempt=True)
    protocol(4, "running", slotExempt=False)
    protocol(5, "launched")

    assert flat.getRunningExecutionSlotUsageForUser(userId, "execution-9")["count"] == 2


def test_TheWorkerWritesOneRuntimeValueAndKeepsTheRest(runs):
    db, flat, userId, projectId, protocol = runs
    protocol(7, "launched")

    flat.setProtocolRuntimeValue(projectId, 7, "waitingForSlot", {"inUse": 4, "limit": 4})
    flat.setProtocolRuntimeValue(projectId, 7, "slotExempt", False)

    row = db.fetchOne('SELECT params FROM protocols WHERE "projectId" = %s AND "protocolId" = %s', (projectId, "7"))
    runtime = row["params"]["_scipionWebRuntime"]
    assert runtime["waitingForSlot"] == {"inUse": 4, "limit": 4} and runtime["slotExempt"] is False
    assert runtime["launchedByUserId"] == str(userId) and row["params"]["gpuList"] == "0"

    flat.setProtocolRuntimeValue(projectId, 7, "waitingForSlot", None)
    row = db.fetchOne('SELECT params FROM protocols WHERE "projectId" = %s AND "protocolId" = %s', (projectId, "7"))
    assert "waitingForSlot" not in row["params"]["_scipionWebRuntime"]
    assert row["params"]["_scipionWebRuntime"]["executionId"] == "execution-7"
