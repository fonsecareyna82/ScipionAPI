"""#123: live polling must not use the full set-integrity output loader."""
import importlib


def test_123_RuntimePollingUsesOutputSummariesInsteadOfSetIntegrityScan(authTestEnv, monkeypatch):
    module = importlib.import_module('app.backend.api.services.project_service')
    service = object.__new__(module.ProjectService)
    calls = []

    class FakeMapper:
        db = None

        def getProjectProtocolRuntimeRows(self, projectId, protocolIds):
            assert projectId == 15
            assert protocolIds == [25]
            return [{
                'protocolId': '25',
                'status': 'finished',
                'params': {
                    '_scipionWebRuntime': {
                        'elapsedTimeSeconds': 15.0,
                        'elapsedSessionId': 'current-session',
                    },
                },
            }]

        def getProjectProtocolStepSummaryByProtocolId(self, projectId):
            assert projectId == 15
            return {'25': {'stepsDone': 2, 'numberOfSteps': 2}}

    class OutputService:
        def loadPersistedOutputsByProtocolId(self, mapper, projectId):
            raise AssertionError(
                'Live runtime polling must not compute MD5/JSONB item integrity signatures'
            )

        def loadPersistedOutputSummariesByProtocolId(self, mapper, projectId):
            calls.append((mapper, projectId))
            return {'25': {'outputParticles': {
                'className': 'SetOfParticles',
                'itemClassName': 'Particle',
                'info': '13,428 particles',
            }}}

    monkeypatch.setattr(module, 'RuntimeProtocolOutputPersistenceService', OutputService)
    monkeypatch.setattr(
        module.ScipionClassHierarchyResolver,
        'loadScipionObjectClasses',
        lambda: {},
    )

    mapper = FakeMapper()
    result = service.getProtocolRuntimeSummaries(
        mapper=mapper, projectId=15, protocolIds=[25],
    )

    assert calls == [(mapper, 15)]
    assert len(result) == 1
    assert result[0]['protocolId'] == '25'
    assert result[0]['status'] == 'finished'
    assert result[0]['elapsedTimeSeconds'] == 15.0
    assert result[0]['elapsedSessionId'] == 'current-session'
    assert result[0]['stepsDone'] == 2
    assert result[0]['outputs'][0]['outputName'] == 'outputParticles'
    assert result[0]['outputs'][0]['pointerClass'] == 'SetOfParticles'
    assert result[0]['outputs'][0]['info'] == '13,428 particles'
