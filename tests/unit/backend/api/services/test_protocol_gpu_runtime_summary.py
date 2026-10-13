"""Running GPU-step summaries must reach lightweight protocol polling."""

import importlib


def test_RuntimeSummariesExposeRunningGpuStepsWithoutStaleActivity(monkeypatch):
    module = importlib.import_module('app.backend.api.services.project_service')
    service = object.__new__(module.ProjectService)

    class FakeMapper:
        def __init__(self):
            self.stepSummaryCalls = []

        def getProjectProtocolRuntimeRows(self, projectId, protocolIds):
            assert projectId == 7
            assert protocolIds == [21, 22, 23]
            return [
                {'protocolId': '21', 'status': 'running', 'params': {}},
                {'protocolId': '22', 'status': 'running', 'params': {}},
                {'protocolId': '23', 'status': 'finished', 'params': {}},
            ]

        def getProjectProtocolStepSummaryByProtocolId(self, projectId):
            self.stepSummaryCalls.append(projectId)
            return {
                '21': {'stepsDone': 1, 'numberOfSteps': 3, 'hasRunningGpuStep': True},
                '22': {'stepsDone': 1, 'numberOfSteps': 3, 'hasRunningGpuStep': False},
                '23': {'stepsDone': 3, 'numberOfSteps': 3, 'hasRunningGpuStep': True},
            }

    class EmptyOutputSummaries:
        def loadPersistedOutputSummariesByProtocolId(self, mapper, projectId):
            assert projectId == 7
            return {}

    monkeypatch.setattr(module, 'RuntimeProtocolOutputPersistenceService', EmptyOutputSummaries)
    monkeypatch.setattr(module.ScipionClassHierarchyResolver, 'loadScipionObjectClasses', lambda: {})

    mapper = FakeMapper()
    summaries = service.getProtocolRuntimeSummaries(mapper=mapper, projectId=7, protocolIds=[21, 22, 23])
    byId = {str(summary['protocolId']): summary for summary in summaries}

    assert byId['21']['hasRunningGpuStep'] is True
    assert byId['22']['hasRunningGpuStep'] is False
    assert byId['23']['hasRunningGpuStep'] is False
    assert mapper.stepSummaryCalls == [7]
