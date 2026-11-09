"""The computing of a period summed by user, group, protocol and machine, and what a run is recorded with."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.backend.api.services import compute_usage
from app.backend.runtime import protocol_run_record
from app.backend.runtime.protocol_run_record import describeRun, endStatus

SINCE = datetime(2026, 11, 1, tzinfo=timezone.utc)
UNTIL = datetime(2026, 11, 6, tzinfo=timezone.utc)


def _row(runId, userId, className, hours, gpus=0, gpuIds="", host="gpu1", status="finished", running=False,
         queueJobId=None, email=None):
    return {"id": runId, "projectId": 1, "projectPath": "/data/projects/ana/Apoferritin", "protocolId": str(runId),
            "protocolClassName": className, "protocolLabel": className.lower(), "userId": userId,
            "userEmail": email or ("user%s@cnb.csic.es" % userId if userId else None),
            "userFirstName": {1: "Ana", 2: "Marta"}.get(userId), "userLastName": "Test" if userId else None,
            "host": host, "queueName": None, "queueJobId": queueJobId, "gpus": gpus, "gpuIds": gpuIds or None,
            "threads": 4, "mpi": 1, "streaming": False, "startedAt": SINCE, "endedAt": None if running else UNTIL,
            "running": running, "status": status, "seconds": hours * 3600}


def test_ThePeriodIsSummedByUserGroupProtocolAndMachine():
    runs = [compute_usage.runOut(row) for row in (
        _row(1, 1, "ProtRelionClassify3D", 10, gpus=2, gpuIds="0,1"),
        _row(2, 1, "ProtCTFFind", 4, status="failed"),
        _row(3, 2, "ProtMotionCorr", 6, gpus=1, gpuIds="1", host="gpu2", running=True),
        # On a queue the GPU ids are the job's, not the machine's
        _row(4, 2, "ProtRelionClassify3D", 1, gpus=4, gpuIds="0,1,2,3", host="node7", queueJobId="5512"),
        _row(5, None, "ProtImportMovies", 2),
    )]
    members = [{"id": 10, "name": "Lab A", "userId": 1, "groupRole": "pi"},
               {"id": 10, "name": "Lab A", "userId": 2, "groupRole": "member"},
               {"id": 11, "name": "Lab B", "userId": 2, "groupRole": "pi"},
               {"id": 12, "name": "Empty", "userId": None, "groupRole": None}]

    report = compute_usage.summarize(runs, members, SINCE, UNTIL)

    assert report["total"] == {"runs": 5, "hours": 23.0, "gpuHours": 30.0, "gpuMeasuredHours": 0.0,
                               "gpuUsedHours": 0.0, "failed": 1, "running": 1, "users": 3}
    assert report["periodHours"] == 120.0
    ana, marta, unknown = report["users"]
    assert (ana["name"], ana["gpuHours"], ana["hours"], ana["failed"]) == ("Ana Test", 20.0, 14.0, 1)
    assert ana["mostUsed"] == "ProtRelionClassify3D"
    assert (marta["name"], marta["gpuHours"], marta["running"]) == ("Marta Test", 10.0, 1)
    assert (unknown["userId"], unknown["name"]) == (None, "Unknown user")

    groups = {group["name"]: group for group in report["groups"]}
    # A user in two groups counts in both
    assert groups["Lab A"]["gpuHours"] == 30.0 and groups["Lab B"]["gpuHours"] == 10.0
    assert (groups["Lab A"]["members"], groups["Lab A"]["activeMembers"]) == (2, 2)
    assert groups["Empty"]["runs"] == 0

    protocols = {row["protocolClassName"]: row for row in report["protocols"]}
    assert protocols["ProtRelionClassify3D"]["gpuHours"] == 24.0 and protocols["ProtRelionClassify3D"]["users"] == 2
    assert report["protocols"][0]["protocolClassName"] == "ProtRelionClassify3D"

    machines = {row["host"]: row for row in report["machines"]}
    assert machines["gpu1"]["gpuHoursById"] == {"0": 10.0, "1": 10.0}
    assert machines["node7"]["gpuHoursById"] == {} and machines["node7"]["gpuHours"] == 4.0
    assert [run["id"] for run in report["running"]] == [3]


def test_HowMuchTheGpusWereReallyUsedCountsOnlyTheRunsLookedAt():
    looked = dict(_row(1, 1, "ProtRelionClassify3D", 10, gpus=2, gpuIds="0,1"),
                  gpuSamples=4, gpuBusySum=160.0, gpuMemoryPeakBytes=8 * 1024 ** 3)
    notLooked = _row(2, 1, "ProtMotionCorr", 5, gpus=1, gpuIds="1")
    withoutGpus = dict(_row(3, 1, "ProtCTFFind", 2), gpuSamples=3, gpuBusySum=90.0)
    runs = [compute_usage.runOut(row) for row in (looked, notLooked, withoutGpus)]

    assert (runs[0]["gpuBusy"], runs[0]["gpuUsedHours"], runs[0]["gpuMemoryPeakBytes"]) == (40.0, 8.0, 8 * 1024 ** 3)
    assert (runs[1]["gpuBusy"], runs[1]["gpuUsedHours"]) == (None, None)
    assert runs[2]["gpuBusy"] is None
    total = compute_usage.summarize(runs, [], SINCE, UNTIL)["total"]
    assert (total["gpuHours"], total["gpuMeasuredHours"], total["gpuUsedHours"]) == (25.0, 20.0, 8.0)


def test_ARunsGpusAreLookedAtOnlyWhenItRunsHereWithGpus(monkeypatch):
    started = []
    monkeypatch.setattr(protocol_run_record.GpuSampler, "startFor",
                        classmethod(lambda cls, gpuIds: started.append(list(gpuIds)) or "sampler"))
    start = protocol_run_record.ProtocolRunRecord._startSampler
    assert start({"gpuIds": "0,2", "queueName": None}) == "sampler"
    assert start({"gpuIds": None, "queueName": None}) is None
    assert start({"gpuIds": "0", "queueName": "gpu-long"}) is None
    assert started == [["0", "2"]]


def test_TheGpuUseIsSavedWithEachHeartbeatAndAtTheEnd(monkeypatch):
    from app.backend.runtime.gpu_sampler import GpuUse

    saved, ended = [], []

    class Mapper:
        def __init__(self, db):
            pass

        def touchRun(self, runId):
            pass

        def endRun(self, runId, status):
            ended.append(status)

        def saveGpuUse(self, runId, samples, busySum, memoryPeakBytes):
            saved.append((samples, busySum, memoryPeakBytes))

    class Sampler:
        use = GpuUse(2, 120.0, 1024)

        def snapshot(self):
            return self.use

        def stop(self):
            self.stopped = True
            return GpuUse(3, 150.0, 2048)

    monkeypatch.setattr(protocol_run_record, "ComputeUsagePostgresqlMapper", Mapper)
    monkeypatch.setattr("app.backend.api.services.notify_events.runEnded", lambda *args: None)
    sampler = Sampler()
    record = protocol_run_record.ProtocolRunRecord(object(), 7, sampler=sampler)
    record.touch()
    record.touch()  # nothing new: not saved again
    record.end("finished")
    assert saved == [(2, 120.0, 1024), (3, 150.0, 2048)]
    assert sampler.stopped and ended == ["finished"]


def test_ThePeriodIsThisMonthByDefaultAndMustStartBeforeItEnds():
    now = datetime(2026, 11, 6, 15, 30, tzinfo=timezone.utc)
    assert compute_usage.period(None, None, now=now) == (datetime(2026, 11, 1, tzinfo=timezone.utc), now)
    # A date without a zone is taken as UTC
    since, until = compute_usage.period(datetime(2026, 10, 1), datetime(2026, 11, 1), now=now)
    assert since.tzinfo is not None and until - since == timedelta(days=31)
    with pytest.raises(ValueError):
        compute_usage.period(UNTIL, SINCE)


def test_ARunWithoutAWorkerAliveIsNotLeftOpenForMoreThanAFewHeartbeats(monkeypatch):
    monkeypatch.setenv("SCIPION_POSTGRESQL_COORDINATOR_HEARTBEAT_SECONDS", "60")
    assert compute_usage.staleSeconds() == 300.0
    monkeypatch.setenv("SCIPION_POSTGRESQL_COORDINATOR_HEARTBEAT_SECONDS", "200")
    assert compute_usage.staleSeconds() == 600.0


class _Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class _Protocol:
    def __init__(self, usesGpu=True, gpus=(0, 2), queue=None):
        self._usesGpu, self._gpus, self._queue = usesGpu, list(gpus), queue
        self.numberOfThreads, self.numberOfMpi = _Value(8), _Value(2)

    def usesGpu(self):
        return self._usesGpu

    def getGpuList(self):
        return self._gpus

    def useQueue(self):
        return self._queue is not None

    def getQueueParams(self):
        return self._queue, {}

    def getObjLabel(self):
        return "relion - 3D classification"


def test_ARunIsRecordedWithItsGpusThreadsAndQueueJob(monkeypatch):
    for name in protocol_run_record.QUEUE_JOB_ID_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    described = describeRun(_Protocol())
    assert (described["gpus"], described["gpuIds"], described["threads"], described["mpi"]) == (2, "0,2", 8, 2)
    assert described["queueName"] is None and described["queueJobId"] is None

    monkeypatch.setenv("SLURM_JOB_ID", "77123")
    described = describeRun(_Protocol(usesGpu=False, queue="gpu-long"))
    assert (described["gpus"], described["gpuIds"]) == (0, None)
    assert (described["queueName"], described["queueJobId"]) == ("gpu-long", "77123")
    assert described["protocolClassName"] == "_Protocol"


def test_ARunEndsWithItsProtocolsStatus():
    assert endStatus("finished", raised=False) == "finished"
    assert endStatus("failed", raised=True) == "failed"
    assert endStatus("running", raised=True) == "failed"
    assert endStatus("running", raised=False) == "aborted"
    assert endStatus("interactive", raised=False) == "interactive"


def test_KeepingTheRecordNeverStopsARun(monkeypatch):
    class Broken:
        def __getattr__(self, name):
            raise RuntimeError("database gone")

    record = protocol_run_record.ProtocolRunRecord.start(
        Broken(), projectId=1, projectPath="/p", protocolId=3, protocol=SimpleNamespace(), userId=1,
        executionId="e", coordinatorRunId=None, streaming=False)
    assert record is None
    protocol_run_record.ProtocolRunRecord(Broken(), 5).touch()
    protocol_run_record.ProtocolRunRecord(Broken(), 5).end("finished")
