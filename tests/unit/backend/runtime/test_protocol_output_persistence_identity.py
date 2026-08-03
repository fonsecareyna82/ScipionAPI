# ******************************************************************************
# *
# * Authors:     Yunior C. Fonseca Reyna
# *
# * Unidad de  Bioinformatica of Centro Nacional de Biotecnologia , CSIC
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 3 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************
from app.backend.runtime.protocol_output_persistence_service import (
    RuntimeProtocolOutputPersistenceService,
)

class FakeRuntimeObject:
    def __init__(
            self,
            objectId,
            attributes=None,
    ):
        self._objId = objectId
        self._objParentId = None
        self._attributes = list(
            attributes or []
        )

    def getObjId(self):
        return self._objId

    def setObjId(
            self,
            objectId,
    ):
        self._objId = (
            None
            if objectId is None
            else int(objectId)
        )

    def setObjParentId(
            self,
            parentObjectId,
    ):
        self._objParentId = (
            None
            if parentObjectId is None
            else int(parentObjectId)
        )

    def getAttributesToStore(self):
        return list(
            self._attributes
        )


class FakeMapper:
    def __init__(
            self,
            objectIds,
    ):
        self.objectIds = list(
            objectIds
        )
        self.allocateCalls = []

    def allocateProjectObjectId(
            self,
            projectId,
    ):
        self.allocateCalls.append(
            projectId
        )

        if not self.objectIds:
            raise AssertionError(
                "Unexpected object id allocation"
            )

        return self.objectIds.pop(
            0
        )


class FakeObjectMapper:
    def __init__(
            self,
            storedRows=None,
    ):
        self.storedRows = list(
            storedRows or []
        )
        self.calls = []

    def getStoredObjectTree(
            self,
            projectId,
            protocolDbId,
            outputName,
    ):
        self.calls.append({
            "projectId": projectId,
            "protocolDbId": protocolDbId,
            "outputName": outputName,
        })

        return list(
            self.storedRows
        )


def test_PrepareOutputObjectIdsAllocatesCanonicalIdForRunDbSetRoot():
    service = (
        RuntimeProtocolOutputPersistenceService()
    )

    outputSet = FakeRuntimeObject(
        objectId=3_000_000_050,
        attributes=[
            (
                "_mapperPath",
                FakeRuntimeObject(
                    3_000_000_051
                ),
            ),
        ],
    )

    mapper = FakeMapper([
        1_000_100,
    ])

    objectMapper = FakeObjectMapper()

    report = (
        service
        ._prepareOutputObjectIdsForPersistence(
            mapper=mapper,
            objectMapper=objectMapper,
            projectId=341,
            protocolDbId=700,
            protocolId=3,
            outputName="TiltSeries",
            outputObj=outputSet,
            includeNestedProperties=False,
        )
    )

    assert outputSet.getObjId() == 1_000_100
    assert outputSet._objParentId == 3

    assert mapper.allocateCalls == [
        341,
    ]

    assert report["rootObjectId"] == 1_000_100
    assert report["prepared"] == 1
    assert report["allocated"] == 1
    assert report["reused"] == 0


def test_PrepareOutputObjectIdsAllocatesCanonicalIdsForRunDbObjectTree():
    service = (
        RuntimeProtocolOutputPersistenceService()
    )

    childObject = FakeRuntimeObject(
        objectId=3_000_000_061
    )

    outputObject = FakeRuntimeObject(
        objectId=3_000_000_060,
        attributes=[
            (
                "_child",
                childObject,
            ),
        ],
    )

    mapper = FakeMapper([
        1_000_110,
        1_000_111,
    ])

    objectMapper = FakeObjectMapper()

    report = (
        service
        ._prepareOutputObjectIdsForPersistence(
            mapper=mapper,
            objectMapper=objectMapper,
            projectId=341,
            protocolDbId=700,
            protocolId=3,
            outputName="outputVolume",
            outputObj=outputObject,
            includeNestedProperties=True,
        )
    )

    assert outputObject.getObjId() == 1_000_110
    assert outputObject._objParentId == 3

    assert childObject.getObjId() == 1_000_111
    assert childObject._objParentId == 1_000_110

    assert mapper.allocateCalls == [
        341,
        341,
    ]

    assert report["prepared"] == 2
    assert report["allocated"] == 2
    assert report["reused"] == 0


def test_PrepareOutputObjectIdsReusesPersistedIdsByPath():
    service = (
        RuntimeProtocolOutputPersistenceService()
    )

    childObject = FakeRuntimeObject(
        objectId=3_000_000_071
    )

    outputObject = FakeRuntimeObject(
        objectId=3_000_000_070,
        attributes=[
            (
                "_child",
                childObject,
            ),
        ],
    )

    mapper = FakeMapper([])

    objectMapper = FakeObjectMapper([
        {
            "path": "outputVolume",
            "scipionObjId": 1_000_120,
        },
        {
            "path": "outputVolume._child",
            "scipionObjId": 1_000_121,
        },
    ])

    report = (
        service
        ._prepareOutputObjectIdsForPersistence(
            mapper=mapper,
            objectMapper=objectMapper,
            projectId=341,
            protocolDbId=700,
            protocolId=3,
            outputName="outputVolume",
            outputObj=outputObject,
            includeNestedProperties=True,
        )
    )

    assert outputObject.getObjId() == 1_000_120
    assert childObject.getObjId() == 1_000_121

    assert mapper.allocateCalls == []

    assert report["allocated"] == 0
    assert report["reused"] == 2


def test_RestoreOutputObjectIdsRestoresRunDbIdentity():
    service = (
        RuntimeProtocolOutputPersistenceService()
    )

    childObject = FakeRuntimeObject(
        objectId=3_000_000_151
    )

    outputObject = FakeRuntimeObject(
        objectId=3_000_000_150,
        attributes=[
            (
                "_child",
                childObject,
            ),
        ],
    )

    outputObject._objParentId = 4
    childObject._objParentId = (
        3_000_000_150
    )

    mapper = FakeMapper([
        1_000_150,
        1_000_151,
    ])

    objectMapper = FakeObjectMapper()

    preparation = (
        service
        ._prepareOutputObjectIdsForPersistence(
            mapper=mapper,
            objectMapper=objectMapper,
            projectId=341,
            protocolDbId=700,
            protocolId=4,
            outputName="TiltSeries",
            outputObj=outputObject,
            includeNestedProperties=True,
        )
    )

    assert outputObject.getObjId() == (
        1_000_150
    )

    assert childObject.getObjId() == (
        1_000_151
    )

    service._restoreOutputObjectIdsAfterPersistence(
        preparation
    )

    assert outputObject.getObjId() == (
        3_000_000_150
    )

    assert outputObject._objParentId == 4

    assert childObject.getObjId() == (
        3_000_000_151
    )

    assert childObject._objParentId == (
        3_000_000_150
    )


class FakePostgresqlRuntimeMapper:
    isPostgresqlRuntimeMapper = True


class FakeSqliteRuntimeMapper:
    isPostgresqlRuntimeMapper = False


class FakeTerminalProtocol:
    def __init__(
            self,
            mapper,
            outputs=None,
    ):
        self.mapper = mapper
        self.outputs = list(
            outputs or []
        )

    def iterOutputAttributes(self):
        return list(
            self.outputs
        )

    def isFinished(self):
        return True

    def isFailed(self):
        return False

    def isAborted(self):
        return False

    def getStatus(self):
        return "finished"


class FakeSetOutput:
    def iterItems(self):
        return iter(())

    def getSize(self):
        return 0

    def getFileName(self):
        return "output.sqlite"


def test_PostgresqlRuntimeProjectionDoesNotReconcileEmptyTerminalOutputs():
    service = (
        RuntimeProtocolOutputPersistenceService()
    )

    protocol = FakeTerminalProtocol(
        mapper=FakePostgresqlRuntimeMapper(),
        outputs=[],
    )

    assert (
        service
        .shouldReconcileMissingProtocolOutputs(
            protocol
        )
        is False
    )

    assert (
        service
        .shouldSyncProtocolOutputs(
            protocol
        )
        is False
    )


def test_RunDbProtocolReconcilesEmptyTerminalOutputs():
    service = (
        RuntimeProtocolOutputPersistenceService()
    )

    protocol = FakeTerminalProtocol(
        mapper=FakeSqliteRuntimeMapper(),
        outputs=[],
    )

    assert (
        service
        .shouldReconcileMissingProtocolOutputs(
            protocol
        )
        is True
    )

    assert (
        service
        .shouldSyncProtocolOutputs(
            protocol
        )
        is True
    )


def test_PostgresqlRuntimeProjectionStillRegistersAvailableOutputs():
    service = (
        RuntimeProtocolOutputPersistenceService()
    )

    protocol = FakeTerminalProtocol(
        mapper=FakePostgresqlRuntimeMapper(),
        outputs=[
            (
                "TiltSeries",
                FakeSetOutput(),
            ),
        ],
    )

    assert (
        service
        .shouldRegisterProtocolOutputs(
            protocol
        )
        is True
    )

    assert (
        service
        .shouldReconcileMissingProtocolOutputs(
            protocol
        )
        is False
    )

    assert (
        service
        .shouldSyncProtocolOutputs(
            protocol
        )
        is True
    )


