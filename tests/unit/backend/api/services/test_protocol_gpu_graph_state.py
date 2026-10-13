"""Initial graph GPU state must agree with lightweight runtime polling."""

import importlib


def test_GraphGpuEligibilityTracksActiveConfiguredGpuSteps(authTestEnv, monkeypatch):
    module = importlib.import_module('app.backend.api.services.project_service')
    service = object.__new__(module.ProjectService)
    service.currentProject = None
    service._tryGetScipionProtocolByRuntimeId = lambda protocolId: (_ for _ in ()).throw(
        AssertionError('Graph GPU state must not load runtime protocols')
    )
    monkeypatch.setattr(module.ScipionClassHierarchyResolver, 'loadScipionObjectClasses', lambda: {})
    monkeypatch.setattr(module.ScipionClassHierarchyResolver, 'loadScipionProtocolClasses', lambda: {})

    cases = [
        ('21', 'running', {'gpuList': '0', 'useGpu': True}, True, True),
        ('22', 'running', {'gpuList': '0', 'useGpu': True}, False, False),
        ('23', 'running', {'gpuList': '0', 'useGpu': False}, True, False),
        ('24', 'running', {'gpuList': ''}, True, False),
        ('25', 'finished', {'gpuList': '0', 'useGpu': True}, True, False),
        ('26', 'running', {'gpuList': {'value': '0,1'}, 'useGpu': {'value': True}}, True, True),
        ('27', 'running', {}, True, False),
    ]
    protocolRows = [
        {'protocolId': protocolId, 'protocolClassName': 'ProtImportMovies', 'status': status, 'params': params}
        for protocolId, status, params, _, _ in cases
    ]
    stepSummaryById = {
        protocolId: {'stepsDone': 0, 'numberOfSteps': 1, 'hasRunningGpuStep': hasGpuStep}
        for protocolId, _, _, hasGpuStep, _ in cases
    }

    graph = service.buildProtocolsGraph(
        projectId=7,
        protocolRows=protocolRows,
        tags={},
        dependencyMap={},
        runMap={},
        protocolStepSummaryByProtocolId=stepSummaryById,
        allowRuntimeFallback=False,
    )

    assert set(graph) == {'PROJECT', *(case[0] for case in cases)}
    for protocolId, _, _, _, expected in cases:
        assert graph[protocolId]['gpuIndicatorEligible'] is expected, protocolId
    assert graph['PROJECT'].get('gpuIndicatorEligible', False) is False
