"""The resources page's queries against the migrated database: the runs going on and the protocols waiting."""
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.backend.mapper.compute_usage_mapper import ComputeUsagePostgresqlMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.mapper.resources_mapper import ResourcesPostgresqlMapper


@pytest.fixture
def lab(postgresqlIntegrationDb, postgresqlMigratedEnv):
    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    users = [flat.insertUser(email="res-%s-%s@example.com" % (name, uuid4().hex), hashedPassword="test",
                             firstName=name, lastName="Test", institution=None, role="user", isActive=True,
                             isVerified=True, verificationCode="") for name in ("Ana", "Luis")]
    projectId = flat.insertProject(ownerId=users[0], name="/tmp/res-%s/Apoferritin" % uuid4().hex,
                                   description="", status="active")

    def protocol(protocolId, status, runtime=None):
        db.execute('INSERT INTO protocols ("protocolId", "projectId", "protocolClassName", params, status) '
                   "VALUES (%s, %s, %s, %s::jsonb, %s)",
                   (str(protocolId), projectId, "ProtRelionClassify3D",
                    json.dumps({"_scipionWebRuntime": runtime} if runtime else {}), status))

    try:
        yield db, users, projectId, protocol
    finally:
        db.execute('DELETE FROM protocol_runs WHERE "projectId" = %s', (projectId,))
        db.execute('DELETE FROM projects WHERE id = %s', (projectId,))
        db.execute('DELETE FROM users WHERE id = ANY(%s)', (users,))


def test_TheRunsGoingOnComeWithTheirWorkerProcess(lab):
    db, users, projectId, protocol = lab
    runs = ComputeUsagePostgresqlMapper(db)
    values = {"projectId": projectId, "projectPath": "/x", "protocolClassName": "ProtRelionClassify3D",
              "protocolLabel": None, "userId": users[0], "executionId": None, "coordinatorRunId": None,
              "host": "gpu1", "queueName": None, "queueJobId": None, "gpus": 1, "gpuIds": "0", "threads": 1,
              "mpi": 1, "streaming": False}
    going = runs.startRun(dict(values, protocolId="1", pid=4321))
    ended = runs.startRun(dict(values, protocolId="2", pid=4322))
    runs.endRun(ended, "finished")
    stale = runs.startRun(dict(values, protocolId="3"))
    db.execute('UPDATE protocol_runs SET "lastSeenAt" = %s WHERE id = %s',
               (datetime.now(timezone.utc) - timedelta(hours=1), stale))

    open_ = {row["id"]: row for row in ResourcesPostgresqlMapper(db).openRuns(300.0)}
    assert going in open_ and ended not in open_ and stale not in open_
    assert (open_[going]["pid"], open_[going]["userFirstName"]) == (4321, "Ana")
    assert open_[going]["projectPath"].endswith("/Apoferritin")


def test_TheProtocolsWaitingAreWhoseLaunchedThem(lab):
    db, users, projectId, protocol = lab
    protocol(5, "launched", {"launchedByUserId": users[1], "waitingForSlot": {"inUse": 2, "limit": 2}})
    protocol(6, "scheduled")
    protocol(7, "launched", {"launchedByUserId": "not a number"})
    protocol(8, "running")

    waiting = {row["protocolId"]: row for row in ResourcesPostgresqlMapper(db).waitingProtocols()
               if row["projectId"] == projectId}
    assert sorted(waiting) == ["5", "6", "7"]
    assert (waiting["5"]["userId"], waiting["5"]["userFirstName"]) == (users[1], "Luis")
    assert waiting["5"]["waitingForSlot"] == {"inUse": 2, "limit": 2}
    assert waiting["6"]["userId"] == users[0] and waiting["7"]["userId"] == users[0]
    assert waiting["6"]["status"] == "scheduled"
