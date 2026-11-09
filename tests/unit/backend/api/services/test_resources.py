"""The resources page: whose run holds each GPU, and what each user may see of the others."""
from datetime import datetime, timezone

from app.backend.api.services import resources

STARTED = datetime(2026, 11, 9, 10, tzinfo=timezone.utc)


def _run(runId, userId, pid, gpuIds="0", host="gpu1", queueName=None):
    return {"id": runId, "projectId": 5, "projectPath": "/data/projects/ana/Apoferritin", "protocolId": str(runId),
            "protocolClassName": "ProtRelionClassify3D", "protocolLabel": "3D classes", "userId": userId,
            "userEmail": "u%s@cnb.csic.es" % userId, "userFirstName": {1: "Ana", 2: "Marta"}[userId],
            "userLastName": "Test", "host": host, "pid": pid, "gpus": len(gpuIds.split(",")), "gpuIds": gpuIds,
            "queueName": queueName, "queueJobId": None, "streaming": False, "startedAt": STARTED}


REPORT = {"hostname": "gpu1", "cpuCount": 64, "load1": 12.0, "load5": 10.0, "memoryTotalBytes": 512,
          "memoryAvailableBytes": 256, "disks": [{"label": "projects", "path": "/data", "totalBytes": 10,
                                                   "freeBytes": 4}], "gpuError": None,
          "gpus": [
              # Ana's run (worker 100) has a program on GPU 0; GPU 1 holds a program of no run
              {"index": "0", "name": "A100", "busy": 90.0, "memoryUsedBytes": 30, "memoryTotalBytes": 40,
               "temperature": 60.0, "processes": [{"pid": 130, "memoryBytes": 20, "ancestors": [120, 100, 1]},
                                                  {"pid": 131, "memoryBytes": 5, "ancestors": [120, 100, 1]}]},
              {"index": "1", "name": "A100", "busy": 50.0, "memoryUsedBytes": 10, "memoryTotalBytes": 40,
               "temperature": 50.0, "processes": [{"pid": 999, "memoryBytes": 10, "ancestors": [1]}]},
              # Given to Marta's run, which does not use it now
              {"index": "2", "name": "A100", "busy": 0.0, "memoryUsedBytes": 0, "memoryTotalBytes": 40,
               "temperature": 35.0, "processes": []},
              {"index": "3", "name": "A100", "busy": 0.0, "memoryUsedBytes": 0, "memoryTotalBytes": 40,
               "temperature": 30.0, "processes": []},
          ]}


class _Mapper:
    def __init__(self, db):
        pass

    def openRuns(self, staleSeconds):
        return [_run(1, 1, 100, "0"), _run(2, 2, 200, "2"), _run(3, 2, 300, "3", host="node7", queueName="gpu")]

    def waitingProtocols(self):
        return [
            {"projectId": 5, "protocolId": "1", "status": "launched", "userId": 1, "projectPath": "/p/A"},
            {"projectId": 5, "protocolId": "8", "status": "launched", "userId": 1, "projectPath": "/p/A",
             "protocolClassName": "ProtCTFFind", "waitingForSlot": {"inUse": 2, "limit": 2}, "since": STARTED,
             "userFirstName": "Ana", "userLastName": "Test"},
            {"projectId": 6, "protocolId": "9", "status": "scheduled", "userId": 2, "projectPath": "/p/B",
             "protocolClassName": "ProtRelionRefine3D", "since": STARTED},
            {"projectId": 6, "protocolId": "10", "status": "launched", "userId": 2, "projectPath": "/p/B"},
        ]


def _view(monkeypatch, user):
    monkeypatch.setattr(resources, "ResourcesPostgresqlMapper", _Mapper)
    return resources.resourcesView(object(), user, [REPORT])


def test_EachGpuSaysWhoseRunHoldsIt(monkeypatch):
    view = _view(monkeypatch, {"id": 1, "permissions": ["storage.view"]})
    gpus = view["machines"][0]["gpus"]
    assert [gpu["state"] for gpu in gpus] == ["busy", "busy", "reserved", "free"]
    (ana,) = gpus[0]["uses"]
    assert (ana["kind"], ana["memoryBytes"], ana["run"]["userName"]) == ("run", 25, "Ana Test")
    assert gpus[1]["uses"] == [{"kind": "other", "memoryBytes": 10, "pid": 999}]
    assert (gpus[2]["uses"][0]["kind"], gpus[2]["uses"][0]["run"]["userName"]) == ("reserved", "Marta Test")
    # A queued run's GPU ids are its job's: they hold no GPU of the machine that sent it
    assert gpus[3]["uses"] == []
    assert view["machines"][0]["runs"] == 2


def test_AUserSeesTheirOwnRunsAndOnlyThatOthersRunSomething(monkeypatch):
    view = _view(monkeypatch, {"id": 1, "permissions": []})
    assert not view["seeAll"]
    gpus = view["machines"][0]["gpus"]
    assert gpus[0]["uses"][0]["run"]["mine"] and gpus[0]["uses"][0]["run"]["projectName"] == "Apoferritin"
    marta = gpus[2]["uses"][0]["run"]
    assert not marta["mine"] and "userName" not in marta and "projectName" not in marta
    assert gpus[1]["uses"] == [{"kind": "other", "memoryBytes": 10}]
    others = [run for run in view["runs"] if not run["mine"]]
    assert len(others) == 2 and all("protocolClassName" not in run for run in others)


def test_WaitingProtocolsSayWhyAndEachUserSeesOnlyTheirs(monkeypatch):
    mine = _view(monkeypatch, {"id": 1, "permissions": []})["waiting"]
    # Protocol 1 runs already: not waiting
    assert [(row["protocolId"], row["reason"]) for row in mine] == [("8", "Waits for a free run slot: 2 of 2 in use")]
    everyone = _view(monkeypatch, {"id": 1, "permissions": ["storage.view"]})["waiting"]
    assert [row["reason"] for row in everyone] == ["Waits for a free run slot: 2 of 2 in use", "Waits for its inputs",
                                                   "Waits for a free worker"]


def test_OneReportPerMachine():
    replies = [{"w1@gpu1": {"hostname": "gpu1", "error": "busy"}},
               {"w2@gpu1": {"hostname": "gpu1", "cpuCount": 8}},
               {"w3@gpu2": {"cpuCount": 4}}, {"w4@gpu1": {"hostname": "gpu1", "cpuCount": 99}}, "noise"]
    reports = resources.collectReports(replies)
    assert [(report["hostname"], report.get("cpuCount")) for report in reports] == [("gpu1", 8), ("gpu2", 4)]
