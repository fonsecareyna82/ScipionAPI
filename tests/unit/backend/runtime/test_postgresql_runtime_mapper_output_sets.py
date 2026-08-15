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
import pytest

from pyworkflow.object import (
    Object,
    Set,
    String,
)

from app.backend.mapper.postgresql_runtime_mapper import (
    PostgresqlRuntimeMapper,
)
from app.backend.mapper.postgresql import (
    POSTGRESQL_RUNTIME_OBJECT_ID_START,
)


class SnapshotItem(Object):
    def __init__(
            self,
            **kwargs,
    ):
        super().__init__(
            **kwargs
        )

        self._name = String()


class SnapshotSet(Set):
    ITEM_TYPE = SnapshotItem


CLASSES = {
    "SnapshotItem": SnapshotItem,
    "SnapshotSet": SnapshotSet,
}


def test_NewNativeSetIsReopenedBeforePostgresqlSnapshot(
        tmp_path,
):
    setPath = (
        tmp_path
        / "output.sqlite"
    )

    outputSet = SnapshotSet(
        filename=str(setPath),
        classesDict=CLASSES,
    )

    item = SnapshotItem()
    item.setObjId(1)
    item._name.set(
        "item-1"
    )

    outputSet.append(
        item
    )

    originalMapper = (
        outputSet._mapper
    )

    try:
        assert (
            originalMapper.doCreateTables
            is False
        )

        assert not hasattr(
            originalMapper,
            "_objColumns",
        )

        runtimeMapper = object.__new__(
            PostgresqlRuntimeMapper
        )

        report = (
            runtimeMapper
            ._prepareNativeSetForPostgresqlSnapshot(
                outputSet
            )
        )

        assert report["reopened"] is True

        assert outputSet._mapper is not (
            originalMapper
        )

        assert hasattr(
            outputSet._mapper,
            "_objColumns",
        )

        restoredItem = (
            outputSet.getFirstItem()
        )

        assert restoredItem.getObjId() == 1
        assert restoredItem._name.get() == (
            "item-1"
        )

    finally:
        outputSet.close()


def test_PostgresqlRuntimeSetIsNotReopened():
    outputSet = SnapshotSet()

    outputSet.isPostgresqlRuntimeOutput = (
        lambda: True
    )

    runtimeMapper = object.__new__(
        PostgresqlRuntimeMapper
    )

    report = (
        runtimeMapper
        ._prepareNativeSetForPostgresqlSnapshot(
            outputSet
        )
    )

    assert report == {
        "reopened": False,
        "reason": (
            "postgresql_runtime_set"
        ),
    }


def test_RuntimeMapperRejectsGenericNativeSetPersistence():
    class ProtocolStub:
        def getObjId(self):
            return 17

    class SetMapperStub:
        def __init__(self):
            self.storeCalls = []

        def storeSet(self, **kwargs):
            self.storeCalls.append(kwargs)

    runtimeMapper = object.__new__(
        PostgresqlRuntimeMapper
    )

    runtimeMapper.projectId = 31
    runtimeMapper.setMapper = SetMapperStub()

    runtimeMapper._findOwnerProtocol = (
        lambda obj: ProtocolStub()
    )

    runtimeMapper._resolveProtocolDbIdFromObject = (
        lambda protocol: 700
    )

    runtimeMapper._getObjectName = (
        lambda obj: "outputParticles"
    )

    runtimeMapper._getClassName = (
        lambda obj: "SnapshotSet"
    )

    outputSet = SnapshotSet()

    with pytest.raises(
            RuntimeError,
            match="refuses direct persistence of non-PostgreSQL Sets",
    ):
        runtimeMapper._storeSetObject(
            outputSet
        )

    assert runtimeMapper.setMapper.storeCalls == []


def test_PopulatedNativeSetUsesFreshIdentityAfterSnapshotPreparation():
    freshObjectId = (
        POSTGRESQL_RUNTIME_OBJECT_ID_START
        + 481
    )

    class ProtocolStub:
        def getObjId(self):
            return 17

    class FlatMapperStub:
        def __init__(self):
            self.objectAllocationCalls = []

        def allocateProjectObjectId(
                self,
                projectId,
        ):
            self.objectAllocationCalls.append(
                int(projectId)
            )

            return freshObjectId

    class SetMapperStub:
        def __init__(self):
            self.storedRuntimeObjectIds = []

        def storeSet(
                self,
                *,
                projectId,
                protocolDbId,
                outputName,
                scipionSet,
                runtimeReserved,
                reservationToken,
        ):
            runtimeObjectId = (
                scipionSet.getObjId()
            )

            self.storedRuntimeObjectIds.append(
                runtimeObjectId
            )

            return {
                "setId": 501,
                "rootTableId": 601,
                "rootObjectId": 701,
                "runtimeObjectId": runtimeObjectId,
                "projectId": projectId,
                "protocolDbId": protocolDbId,
                "outputName": outputName,
                "setClassName": "SnapshotSet",
                "itemClassName": "SnapshotItem",
                "properties": {},
            }

    class RuntimeSetFactoryStub:
        def __init__(self):
            self.buildCalls = []

        def _promoteRuntimeSetInstance(
                self,
                *,
                runtimeSet,
                nativeSetClass,
        ):
            return runtimeSet

        def build(
                self,
                *,
                db,
                parent,
                outputName,
                outputInfo,
                classes,
                runtimeSet,
                cache,
        ):
            self.buildCalls.append({
                "db": db,
                "parent": parent,
                "outputName": outputName,
                "outputInfo": dict(
                    outputInfo
                ),
                "classes": classes,
                "runtimeSet": runtimeSet,
                "cache": cache,
            })

            return runtimeSet

    runtimeMapper = object.__new__(
        PostgresqlRuntimeMapper
    )

    runtimeMapper.projectId = 31
    runtimeMapper.db = object()
    runtimeMapper.dictClasses = CLASSES
    runtimeMapper.flatMapper = FlatMapperStub()
    runtimeMapper.setMapper = SetMapperStub()
    runtimeMapper.runtimeSetFactory = (
        RuntimeSetFactoryStub()
    )

    outputSet = SnapshotSet()
    outputSet.setObjId(
        3_000_000_050
    )

    originalIdentity = id(
        outputSet
    )

    def prepareNativeSet(runtimeSet):
        # Simulate the SQLite mapper restoring its own
        # internal root id when the Set is reopened.
        runtimeSet.setObjId(
            7
        )

        return {
            "reopened": True,
            "reason": (
                "native_mapper_schema_initialized"
            ),
        }

    runtimeMapper._prepareNativeSetForPostgresqlSnapshot = (
        prepareNativeSet
    )

    outputSet.enablePostgresqlWrite = (
        lambda: outputSet
    )

    result = (
        runtimeMapper
        ._adoptPopulatedPostgresqlOutputSet(
            protocol=ProtocolStub(),
            protocolDbId=700,
            setClass=SnapshotSet,
            provisionalOutputName=(
                "__postgresql_runtime_output_test"
            ),
            reservationToken="test-token",
            runtimeSet=outputSet,
        )
    )

    assert result is outputSet
    assert id(result) == originalIdentity
    assert result.getObjId() == freshObjectId

    assert (
        runtimeMapper
        .flatMapper
        .objectAllocationCalls
        == [
            31,
        ]
    )

    assert (
        runtimeMapper
        .setMapper
        .storedRuntimeObjectIds
        == [
            freshObjectId,
        ]
    )

    buildCall = (
        runtimeMapper
        .runtimeSetFactory
        .buildCalls[0]
    )

    assert (
        buildCall[
            "outputInfo"
        ][
            "runtimeObjectId"
        ]
        == freshObjectId
    )


def test_BindPostgresqlOutputSetAliasPreservesCanonicalStorage():
    class ProtocolStub:
        def getObjId(self):
            return 17

    class RuntimeSetFactoryStub:
        def __init__(self):
            self.promoted = []
            self.built = []

        def _promoteRuntimeSetInstance(
                self,
                runtimeSet,
                nativeSetClass,
        ):
            self.promoted.append({
                "runtimeSet": runtimeSet,
                "nativeSetClass": nativeSetClass,
            })

            runtimeSet.isPostgresqlRuntimeOutput = (
                lambda: True
            )

            runtimeSet._postgresqlNativeSetClass = (
                nativeSetClass
            )

            return runtimeSet

        def build(self, **kwargs):
            self.built.append(
                dict(kwargs)
            )

            return kwargs[
                "runtimeSet"
            ]

    mapper = object.__new__(
        PostgresqlRuntimeMapper
    )

    mapper.projectId = 31
    mapper.db = object()
    mapper.dictClasses = CLASSES
    mapper.runtimeSetFactory = (
        RuntimeSetFactoryStub()
    )

    mapper._resolveProtocolDbIdFromObject = (
        lambda protocol: 700
    )

    canonicalSet = SnapshotSet()
    canonicalSet.setObjId(91)
    canonicalSet.isPostgresqlRuntimeOutput = lambda: True
    canonicalSet._postgresqlNativeSetClass = SnapshotSet
    canonicalSet.getPostgresqlRuntimeInfo = lambda: {
        "setId": 501,
        "rootTableId": 601,
        "runtimeObjectId": 91,
        "outputName": "outputParticles",
        "className": "SnapshotSet",
        "setClassName": "SnapshotSet",
        "itemClassName": "SnapshotItem",
    }
    canonicalSet.getPostgresqlRuntimeProperties = lambda: {
        "itemsCount": 500,
    }

    runtimeAlias = SnapshotSet()
    runtimeAlias.enablePostgresqlWrite = lambda: runtimeAlias

    result = mapper.bindPostgresqlOutputSetAlias(
        protocol=ProtocolStub(),
        runtimeSet=runtimeAlias,
        canonicalSet=canonicalSet,
    )

    assert result is runtimeAlias
    assert runtimeAlias.getObjId() == 91

    buildCall = (
        mapper
        .runtimeSetFactory
        .built[0]
    )

    assert buildCall["runtimeSet"] is runtimeAlias
    assert buildCall["cache"] is False
    assert buildCall["outputInfo"]["setId"] == 501
    assert buildCall["outputInfo"]["runtimeObjectId"] == 91


