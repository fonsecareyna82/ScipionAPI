"""Regression contracts for step GPU activity in project summaries."""

from app.backend.mapper.postgresql import PostgresqlFlatMapper


class StepSummaryDb:
    def __init__(self):
        self.calls = []

    def fetchAll(self, query, params):
        self.calls.append((query, params))
        return [
            {"protocolId": "21", "numberOfSteps": 3, "stepsDone": 1, "elapsedSeconds": 5.0, "isInteractive": False, "updatedAt": None, "hasRunningGpuStep": True},
            {"protocolId": "22", "numberOfSteps": 3, "stepsDone": 1, "elapsedSeconds": 5.0, "isInteractive": False, "updatedAt": None, "hasRunningGpuStep": False},
            {"protocolId": "23", "numberOfSteps": 3, "stepsDone": 3, "elapsedSeconds": 5.0, "isInteractive": False, "updatedAt": None, "hasRunningGpuStep": False},
        ]


def test_StepSummaryReportsOnlyCurrentlyRunningGpuSteps():
    mapper = object.__new__(PostgresqlFlatMapper)
    mapper.db = StepSummaryDb()

    summaries = mapper.getProjectProtocolStepSummaryByProtocolId(projectId=7)

    assert summaries["21"]["hasRunningGpuStep"] is True
    assert summaries["22"]["hasRunningGpuStep"] is False
    assert summaries["23"]["hasRunningGpuStep"] is False

    assert len(mapper.db.calls) == 1
    sql, params = mapper.db.calls[0]
    sql = " ".join(sql.split()).lower()
    assert params == (7,)
    assert '"needsgpu"' in sql
    assert '"hasrunninggpustep"' in sql
    assert "'running'" in sql
    assert "bool_or(" in sql
