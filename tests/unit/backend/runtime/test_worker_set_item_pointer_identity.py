"""RED 64: worker must not accept unresolved Set-member Pointer references.

The real Scipion Pointer.get() traverses a numeric extension using the Set's
__getitem__(scipionItemId). Item identity is deliberately sparse (34 and 90),
never an array index. This suite exercises the actual worker restoration path.
"""
from types import SimpleNamespace

import pytest
from pyworkflow.object import Object
from pyworkflow.protocol import Set

import app.backend.runtime.postgresql_protocol_worker as worker_module
from app.backend.runtime.postgresql_protocol_worker import (
    RuntimePostgresqlProtocolWorker,
)


class _Item(Object):
    def __init__(self, item_id):
        super().__init__()
        self.setObjId(item_id)


class _PersistedSet(Set):
    def __init__(self, members, *, missing_raises=False):
        super().__init__()
        self.setObjId(440)
        self.members = dict(members)
        self.missing_raises = missing_raises
        self.refreshed = 0
        self.lookups = []

    def __getitem__(self, item_id):
        self.lookups.append(item_id)
        if item_id not in self.members and self.missing_raises:
            raise KeyError('Scipion item %s is absent' % item_id)
        return self.members.get(item_id)

    def refreshPostgresqlRuntimeState(self):
        self.refreshed += 1
        return self


class _GraphRepository:
    instances = []

    def __init__(self):
        self.output_queries = []
        self.updated_refs = []
        self.instances.append(self)

    def getPostgresqlRuntimeOutputInfo(self, **kwargs):
        self.output_queries.append(kwargs)
        assert kwargs['projectId'] == 7
        assert kwargs['parentProtocolDbId'] == 20
        # The PostgreSQL output is not called outputVolumes.34.
        assert kwargs['outputName'] == 'outputVolumes'
        return {
            'exists': True,
            'runtimeObjectId': 440,
            'className': 'SetOfVolumes',
        }

    def updateResolvedInputRef(self, **kwargs):
        self.updated_refs.append(kwargs)


class _Protocol:
    def __init__(self, *, multi=False):
        self.multi = multi

    def getParam(self, name):
        assert name in ('inputVolume', 'inputVolumes')
        if self.multi:
            return _MultiPointerParam()
        return SimpleNamespace()


class _MultiPointerParam:
    pass


def _make_worker(monkeypatch, stored_set, *, multi=False):
    _GraphRepository.instances.clear()
    monkeypatch.setattr(worker_module, 'ProtocolGraphRepository', _GraphRepository)
    monkeypatch.setattr(worker_module, 'MultiPointerParam', _MultiPointerParam)

    worker = RuntimePostgresqlProtocolWorker(projectId=7, protocolId=902)
    worker.mapper = SimpleNamespace(db=object())
    worker.runtimeMapper = SimpleNamespace()
    worker.protocol = _Protocol(multi=multi)
    worker.getProtocolDbId = lambda: 91

    calls = []

    def select_output(runtime_id):
        calls.append(runtime_id)
        assert runtime_id == 440
        return stored_set

    worker._getExecutionInputObject = select_output
    return worker, calls


def _ref(extension, *, name='inputVolume', index=0):
    return {
        'inputName': name,
        'itemIndex': index,
        'parentProtocolDbId': 20,
        'parentProtocolId': '2202',
        'parentOutputName': extension,
    }


class TestWorkerSetItemPointerIdentity_RED64:
    def test_RootSetPointerPreservesExistingBehavior_baseline(self, monkeypatch):
        item = _Item(34)
        stored_set = _PersistedSet({34: item})
        worker, calls = _make_worker(monkeypatch, stored_set)
        report = worker.restoreExecutionInputs(
            persistResolvedRefs=False,
            inputRefs=[_ref('outputVolumes')],
        )
        assert report['errors'] == []
        assert report['restored'] == 1
        assert worker.protocol.inputVolume.get() is stored_set
        assert calls == [440]
        assert stored_set.refreshed == 1
        assert stored_set.lookups == []

    def test_SparseMemberIdentityIsReportedAfterNativePointerGet(self, monkeypatch):
        item34 = _Item(34)
        item90 = _Item(90)
        stored_set = _PersistedSet({34: item34, 90: item90})
        worker, _ = _make_worker(monkeypatch, stored_set)
        report = worker.restoreExecutionInputs(
            persistResolvedRefs=False,
            inputRefs=[_ref('outputVolumes.34')],
        )
        assert report['errors'] == []
        assert report['restored'] == 1
        assert worker.protocol.inputVolume.get() is item34
        assert stored_set.lookups and set(stored_set.lookups) == {34}
        assert report['items'][0]['scipionItemId'] == 34
        assert report['items'][0]['parentOutputName'] == 'outputVolumes.34'

    def test_AbsentMemberReturningNoneIsRejectedBeforeInstallation(self, monkeypatch):
        stored_set = _PersistedSet({34: _Item(34)})
        worker, _ = _make_worker(monkeypatch, stored_set)
        report = worker.restoreExecutionInputs(
            persistResolvedRefs=False,
            inputRefs=[_ref('outputVolumes.99')],
        )
        assert report['restored'] == 0
        assert len(report['errors']) == 1
        assert '99' in report['errors'][0]['error']
        assert not hasattr(worker.protocol, 'inputVolume')

    def test_AbsentMemberRaisingKeyErrorIsReportedNotThrown(self, monkeypatch):
        stored_set = _PersistedSet({34: _Item(34)}, missing_raises=True)
        worker, _ = _make_worker(monkeypatch, stored_set)
        report = worker.restoreExecutionInputs(
            persistResolvedRefs=False,
            inputRefs=[_ref('outputVolumes.99')],
        )
        assert report['restored'] == 0
        assert len(report['errors']) == 1
        assert '99' in report['errors'][0]['error']
        assert not hasattr(worker.protocol, 'inputVolume')

    def test_MultiPointerDoesNotAppendAnUnresolvedMember(self, monkeypatch):
        item34 = _Item(34)
        stored_set = _PersistedSet({34: item34})
        worker, _ = _make_worker(monkeypatch, stored_set, multi=True)
        report = worker.restoreExecutionInputs(
            persistResolvedRefs=False,
            inputRefs=[
                _ref('outputVolumes.34', name='inputVolumes', index=0),
                _ref('outputVolumes.99', name='inputVolumes', index=1),
            ],
        )
        assert report['restored'] == 1
        assert len(report['errors']) == 1
        assert len(worker.protocol.inputVolumes) == 1
        assert worker.protocol.inputVolumes[0].get() is item34

    def test_WrongItemIdentityDoesNotPersistAResolvedInputRef(self, monkeypatch):
        # A stale/damaged hydrated Set must never map a requested 34 to item 90.
        wrong_item = _Item(90)
        stored_set = _PersistedSet({34: wrong_item})
        worker, _ = _make_worker(monkeypatch, stored_set)
        report = worker.restoreExecutionInputs(
            persistResolvedRefs=True,
            inputRefs=[_ref('outputVolumes.34')],
        )
        assert report['restored'] == 0
        assert len(report['errors']) == 1
        assert '34' in report['errors'][0]['error']
        assert not hasattr(worker.protocol, 'inputVolume')
        assert _GraphRepository.instances[0].updated_refs == []
