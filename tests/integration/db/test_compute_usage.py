"""The protocol runs record against the migrated database: what the worker writes and what a period adds up."""
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.backend.api.services import compute_usage
from app.backend.mapper.compute_usage_mapper import ComputeUsagePostgresqlMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper


@pytest.fixture
def lab(postgresqlIntegrationDb, postgresqlMigratedEnv):
    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    userId = flat.insertUser(email="usage-%s@example.com" % uuid4().hex, hashedPassword="test", firstName="Ana",
                             lastName="Test", institution=None, role="user", isActive=True, isVerified=True,
                             verificationCode="")
    projectId = flat.insertProject(ownerId=userId, name="/tmp/usage-%s/Apoferritin" % uuid4().hex,
                                   description="", status="active")

    def protocol(protocolId, status):
        db.execute('INSERT INTO protocols ("protocolId", "projectId", "protocolClassName", params, status) '
                   "VALUES (%s, %s, %s, %s::jsonb, %s)",
                   (str(protocolId), projectId, "ProtRelionClassify3D", json.dumps({}), status))

    def run(protocolId, **values):
        return ComputeUsagePostgresqlMapper(db).startRun(dict(
            {"projectId": projectId, "projectPath": "/old/path", "protocolId": str(protocolId),
             "protocolClassName": "ProtRelionClassify3D", "protocolLabel": "3D classes", "userId": userId,
             "executionId": "e", "coordinatorRunId": None, "host": "gpu1", "queueName": None, "queueJobId": None,
             "gpus": 2, "gpuIds": "0,1", "threads": 4, "mpi": 1, "streaming": False}, **values))

    def move(runId, **times):
        sets = ", ".join('"%s" = %%s' % name for name in times)
        db.execute("UPDATE protocol_runs SET %s WHERE id = %%s" % sets, (*times.values(), runId))

    try:
        yield db, userId, projectId, protocol, run, move
    finally:
        db.execute('DELETE FROM protocol_runs WHERE "userId" = %s', (userId,))
        db.execute('DELETE FROM projects WHERE id = %s', (projectId,))
        db.execute('DELETE FROM users WHERE id = %s', (userId,))


def test_APeriodCountsTheHoursOfEachRunInsideIt(lab):
    db, userId, projectId, protocol, run, move = lab
    now = datetime.now(timezone.utc)
    since, until = now - timedelta(hours=10), now - timedelta(hours=2)
    mapper = ComputeUsagePostgresqlMapper(db)

    protocol(1, "finished")
    finished = run(1)
    mapper.endRun(finished, "finished")
    # Started before the period and ended inside it: only the part inside counts
    move(finished, startedAt=now - timedelta(hours=12), endedAt=now - timedelta(hours=6),
         lastSeenAt=now - timedelta(hours=6))

    protocol(2, "running")
    running = run(2)
    move(running, startedAt=now - timedelta(hours=3))

    report = compute_usage.summarize([compute_usage.runOut(row) for row in
                                      mapper.runsInPeriod(since, until, 300, userId=userId)], [], since, until)
    byId = {run["id"]: run for run in report["running"]}
    assert report["total"]["runs"] == 2
    assert report["total"]["hours"] == pytest.approx(4 + 1, abs=0.01)
    assert report["total"]["gpuHours"] == pytest.approx(10, abs=0.02)
    assert list(byId) == [running]


def test_ARunWhoseWorkerDiedEndsAtItsLastHeartbeat(lab):
    db, userId, projectId, protocol, run, move = lab
    now = datetime.now(timezone.utc)
    mapper = ComputeUsagePostgresqlMapper(db)

    protocol(3, "running")
    dead = run(3)
    move(dead, startedAt=now - timedelta(hours=5), lastSeenAt=now - timedelta(hours=4))

    rows = mapper.runsInPeriod(now - timedelta(days=1), now, 300, userId=userId)
    assert [(row["status"], row["running"]) for row in rows] == [("interrupted", False)]
    assert rows[0]["seconds"] == pytest.approx(3600, abs=5)
    # The project's current path is shown, not the one recorded
    assert rows[0]["projectPath"].endswith("/Apoferritin")

    # Launching the protocol again closes what the dead worker left open
    again = run(3)
    closed = db.fetchOne('SELECT "endedAt", status FROM protocol_runs WHERE id = %s', (dead,))
    assert closed["status"] == "interrupted" and closed["endedAt"] is not None
    assert again != dead


def test_EachUserSeesTheirOwnTotals(lab):
    db, userId, projectId, protocol, run, move = lab
    protocol(4, "finished")
    runId = run(4)
    ComputeUsagePostgresqlMapper(db).endRun(runId, "failed")

    own = compute_usage.ownUsage(db, userId)
    assert (own["runs"], own["failed"]) == (1, 1)
    runs = compute_usage.userRuns(db, userId)["runs"]
    assert [(run["id"], run["status"], run["projectName"]) for run in runs] == [(runId, "failed", "Apoferritin")]


def test_TheGpuUseOfARunIsSavedAndReadBack(lab):
    db, userId, projectId, protocol, run, move = lab
    now = datetime.now(timezone.utc)
    mapper = ComputeUsagePostgresqlMapper(db)
    protocol(7, "finished")
    runId = run(7)
    mapper.saveGpuUse(runId, 3, 120.0, 4 * 1024 ** 3)
    mapper.saveGpuUse(runId, 4, 180.0, 6 * 1024 ** 3)
    mapper.endRun(runId, "finished")
    move(runId, startedAt=now - timedelta(hours=5), endedAt=now - timedelta(hours=1), lastSeenAt=now - timedelta(hours=1))

    rows = [row for row in mapper.runsInPeriod(now - timedelta(hours=6), now, 300.0, userId=userId) if row["id"] == runId]
    assert (rows[0]["gpuSamples"], rows[0]["gpuBusySum"], rows[0]["gpuMemoryPeakBytes"]) == (4, 180.0, 6 * 1024 ** 3)
    usage = compute_usage.ownUsage(db, userId, since=now - timedelta(hours=6), until=now)
    assert usage["gpuMeasuredHours"] == pytest.approx(8.0) and usage["gpuUsedHours"] == pytest.approx(3.6)
