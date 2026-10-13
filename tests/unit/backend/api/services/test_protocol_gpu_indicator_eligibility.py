"""A running GPU step alone is not sufficient for a GPU indicator."""

import importlib


def test_RuntimeGpuIndicatorRespectsProtocolGpuConfiguration(monkeypatch):
    module = importlib.import_module('app.backend.api.services.project_service')
    service = object.__new__(module.ProjectService)

    configurations = [
        ('21', 'running', {'gpuList': '0', 'useGpu': True}, True, True),
        ('22', 'running', {'gpuList': '0', 'useGpu': False}, True, False),
        ('23', 'running', {'gpuList': '', 'useGpu': True}, True, False),
        ('24', 'running', {'gpuList': '0', 'useGpu': True}, False, False),
        ('25', 'finished', {'gpuList': '0', 'useGpu': True}, True, False),
        ('26', 'running', {'gpuList': '0'}, True, True),
        ('27', 'running', {'gpuList': {'value': '0,1'}, 'useGpu': {'value': False}}, True, False),
        ('28', 'running', {}, True, False),
    ]

    class FakeMapper:
        def __init__(self):
            self.summaryCalls = []

        def getProjectProtocolRuntimeRows(self, projectId, protocolIds):
            assert projectId == 7
            assert protocolIds == [int(item[0]) for item in configurations]
            return [{'protocolId': protocolId, 'status': status, 'params': params}
                    for protocolId, status, params, _, _ in configurations]

        def getProjectProtocolStepSummaryByProtocolId(self, projectId):
            self.summaryCalls.append(projectId)
            return {protocolId: {'stepsDone': 1, 'numberOfSteps': 3, 'hasRunningGpuStep': hasStep}
                    for protocolId, _, _, hasStep, _ in configurations}

    class EmptyOutputSummaries:
        def loadPersistedOutputSummariesByProtocolId(self, mapper, projectId):
            assert projectId == 7
            return {}

    monkeypatch.setattr(module, 'RuntimeProtocolOutputPersistenceService', EmptyOutputSummaries)
    monkeypatch.setattr(module.ScipionClassHierarchyResolver, 'loadScipionObjectClasses', lambda: {})

    mapper = FakeMapper()
    result = service.getProtocolRuntimeSummaries(mapper=mapper, projectId=7, protocolIds=[int(item[0]) for item in configurations])
    byId = {str(summary['protocolId']): summary for summary in result}

    assert len(result) == len(configurations)
    assert mapper.summaryCalls == [7]
    for protocolId, _, _, hasStep, expected in configurations:
        assert byId[protocolId]['hasRunningGpuStep'] is bool(hasStep and byId[protocolId]['status'] == 'running')
        assert byId[protocolId]['gpuIndicatorEligible'] is expected, protocolId
