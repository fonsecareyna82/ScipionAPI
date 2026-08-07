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

from unittest.mock import Mock

from pyworkflow.object import (
    Object,
    Set,
    String,
)

from app.backend.mapper.postgresql_runtime_mapper import (
    PostgresqlRuntimeMapper,
)


class ExampleItem(Object):
    def __init__(
            self,
            **kwargs,
    ):
        super().__init__(
            **kwargs
        )

        self._name = String()


class ExampleSet(Set):
    ITEM_TYPE = ExampleItem


class FakeDb:
    pass


class FakeFlatMapper:
    def __init__(
            self,
    ):
        self.db = FakeDb()

    def getProjectProtocolByProtocolId(
            self,
            projectId,
            protocolId,
    ):
        return None


class FakeProtocolGraphRepository:
    def __init__(
            self,
            outputInfo=None,
            fail=False,
    ):
        self.outputInfo = outputInfo
        self.fail = fail
        self.calls = []

    def getPersistedSetOutputRowByRuntimeObjectId(
            self,
            mapper,
            projectId,
            runtimeObjectId,
    ):
        if self.fail:
            raise AssertionError(
                "Repository must not be called "
                "for a cached runtime set"
            )

        self.calls.append({
            "mapper": mapper,
            "projectId": projectId,
            "runtimeObjectId": runtimeObjectId,
        })

        return self.outputInfo


class FakeRuntimeSetFactory:
    def __init__(
            self,
            runtimeSet=None,
            cachedSet=None,
    ):
        self.runtimeSet = runtimeSet
        self.cachedSet = cachedSet

        self.cacheLookups = []
        self.cacheWrites = []
        self.matchCalls = []
        self.buildCalls = []
        self.pointerCacheClearCalls = []

    def _getCachedRuntimeSet(
            self,
            projectId,
            runtimeObjectId,
    ):
        self.cacheLookups.append(
            (
                projectId,
                runtimeObjectId,
            )
        )

        return self.cachedSet

    def _isMatchingRuntimeSet(
            self,
            runtimeSet,
            runtimeObjectId,
    ):
        self.matchCalls.append(
            (
                runtimeSet,
                runtimeObjectId,
            )
        )

        return (
            runtimeSet is not None
            and runtimeSet is self.cachedSet
        )

    def _cacheRuntimeSet(
            self,
            runtimeSet,
    ):
        self.cacheWrites.append(
            runtimeSet
        )

        self.cachedSet = runtimeSet

    def build(
            self,
            **kwargs,
    ):
        self.buildCalls.append(
            dict(
                kwargs
            )
        )

        existingRuntimeSet = (
            kwargs.get(
                "runtimeSet"
            )
        )

        if existingRuntimeSet is not None:
            existingRuntimeSet.runtimeMarker = (
                "refreshed"
            )

            existingRuntimeSet._mapper = (
                Mock()
            )

            return existingRuntimeSet

        return self.runtimeSet

    def clearRuntimeSetPointerCache(
            self,
            projectId,
            runtimeObjectId,
    ):
        self.pointerCacheClearCalls.append(
            (
                projectId,
                runtimeObjectId,
            )
        )


def buildMapper():
    return PostgresqlRuntimeMapper(
        flatMapper=FakeFlatMapper(),
        projectId=4,
        dictClasses={
            "ExampleSet": ExampleSet,
            "ExampleItem": ExampleItem,
        },
    )


def buildOutputInfo():
    return {
        "setId": 31,
        "projectId": 4,
        "protocolDbId": 20,
        "protocolId": "200",
        "objectId": 401,
        "runtimeObjectId": 300,
        "outputName": "outputParticles",
        "className": "ExampleSet",
        "itemClassName": "ExampleItem",
        "properties": {},
    }


def test_SelectSetByIdBuildsSetWithoutMutatingParentOutput():
    mapper = buildMapper()

    parentProtocol = Object()
    parentProtocol.setObjId(200)

    originalOutput = object()
    parentProtocol.outputParticles = originalOutput

    runtimeSet = ExampleSet()
    runtimeSet.setObjId(300)

    repository = FakeProtocolGraphRepository(
        outputInfo=buildOutputInfo()
    )

    factory = FakeRuntimeSetFactory(
        runtimeSet=runtimeSet
    )

    selectedProtocolCalls = []

    def selectRuntimeProtocol(
            protocolId,
            refreshCached=True,
    ):
        selectedProtocolCalls.append(
            (
                protocolId,
                refreshCached,
            )
        )

        if protocolId == 200:
            return parentProtocol

        return None

    mapper.protocolGraphRepository = repository
    mapper.runtimeSetFactory = factory
    mapper.selectRuntimeProtocolById = selectRuntimeProtocol

    firstResult = mapper._selectSetByIdFromPostgresql(300)
    secondResult = mapper._selectSetByIdFromPostgresql(300)

    assert firstResult is runtimeSet
    assert secondResult is runtimeSet

    # Reading the set must not replace the protocol output.
    assert parentProtocol.outputParticles is originalOutput

    assert repository.calls == [{
        "mapper": mapper,
        "projectId": 4,
        "runtimeObjectId": 300,
    }]

    assert selectedProtocolCalls == [
        (
            200,
            True,
        ),
    ]

    assert factory.cacheLookups == [
        (4, 300),
        (4, 300),
    ]

    assert factory.cacheWrites == [runtimeSet]
    assert len(factory.buildCalls) == 1

    buildCall = factory.buildCalls[0]

    assert buildCall["db"] is mapper.db
    assert buildCall["parent"] is parentProtocol
    assert buildCall["outputName"] == "outputParticles"
    assert buildCall["outputInfo"] == buildOutputInfo()
    assert buildCall["classes"] == mapper.dictClasses


def test_SelectSetByIdReturnsCachedRuntimeSet():
    mapper = buildMapper()

    cachedSet = ExampleSet()

    cachedSet.setObjId(
        300
    )

    mapper.protocolGraphRepository = (
        FakeProtocolGraphRepository(
            fail=True
        )
    )

    mapper.runtimeSetFactory = (
        FakeRuntimeSetFactory(
            cachedSet=cachedSet
        )
    )

    result = (
        mapper
        ._selectSetByIdFromPostgresql(
            300
        )
    )

    assert result is cachedSet

    assert (
        mapper.runtimeSetFactory
        .cacheLookups
        == [
            (
                4,
                300,
            )
        ]
    )


def test_SelectByIdUsesPostgresqlSetBeforeGenericObject():
    mapper = buildMapper()

    runtimeSet = ExampleSet()
    runtimeSet.setObjId(300)

    mapper._selectProtocolByIdFromPostgresql = lambda objId: None
    mapper._selectSetByIdFromPostgresql = lambda objId: runtimeSet

    def failGenericObjectLookup(objId):
        raise AssertionError(
            "Generic object lookup must not run when "
            "PostgreSQL already returned the set"
        )

    mapper._selectGenericObjectByIdFromPostgresql = failGenericObjectLookup

    assert mapper.selectById(300) is runtimeSet


def test_SelectByIdKeepsProtocolPrecedence():
    mapper = buildMapper()

    protocol = Object()

    protocol.setObjId(
        200
    )

    mapper._selectProtocolByIdFromPostgresql = (
        lambda objId: protocol
    )

    def failSetLookup(
            objId,
    ):
        raise AssertionError(
            "Set lookup must not run when "
            "PostgreSQL already returned a protocol"
        )

    mapper._selectSetByIdFromPostgresql = (
        failSetLookup
    )

    assert mapper.selectById(
        200
    ) is protocol


def test_UpdateFromRefreshesPostgresqlRuntimeSet():
    mapper = buildMapper()

    parentProtocol = Object()

    parentProtocol.setObjId(
        200
    )

    runtimeSet = ExampleSet()

    runtimeSet.setObjId(
        300
    )

    runtimeSet.runtimeMarker = "stale"
    runtimeSet._objParent = None

    previousMapper = Mock()
    runtimeSet._mapper = previousMapper

    repository = FakeProtocolGraphRepository(
        outputInfo=buildOutputInfo()
    )

    factory = FakeRuntimeSetFactory(
        cachedSet=runtimeSet
    )

    selectedProtocols = []

    def selectRuntimeProtocol(
            protocolId,
            refreshCached=True,
    ):
        selectedProtocols.append(
            (
                protocolId,
                refreshCached,
            )
        )

        return parentProtocol

    mapper.protocolGraphRepository = (
        repository
    )

    mapper.runtimeSetFactory = factory

    mapper.selectRuntimeProtocolById = (
        selectRuntimeProtocol
    )

    result = mapper.updateFrom(
        runtimeSet
    )

    assert result is None

    assert runtimeSet.runtimeMarker == (
        "refreshed"
    )

    assert selectedProtocols == [
        (
            200,
            False,
        ),
    ]

    assert previousMapper.close.call_count == 1

    assert factory.cacheWrites == [
        runtimeSet,
    ]

    assert (
        factory.pointerCacheClearCalls
        == [
            (
                4,
                300,
            )
        ]
    )

    buildCall = factory.buildCalls[0]

    assert buildCall[
        "runtimeSet"
    ] is runtimeSet

    assert buildCall[
        "cache"
    ] is False

    assert buildCall[
        "parent"
    ] is parentProtocol


def test_UpdateFromSetDoesNotRefreshExistingParentProtocol():
    mapper = buildMapper()

    parentProtocol = Object()

    parentProtocol.setObjId(
        200
    )

    runtimeSet = ExampleSet()

    runtimeSet.setObjId(
        300
    )

    runtimeSet._objParent = (
        parentProtocol
    )

    runtimeSet._mapper = Mock()

    mapper.protocolGraphRepository = (
        FakeProtocolGraphRepository(
            outputInfo=buildOutputInfo()
        )
    )

    mapper.runtimeSetFactory = (
        FakeRuntimeSetFactory(
            cachedSet=runtimeSet
        )
    )

    mapper.selectRuntimeProtocolById = Mock(
        side_effect=AssertionError(
            "Existing parent protocol "
            "must not be refreshed"
        )
    )

    mapper.updateFrom(
        runtimeSet
    )

    mapper.selectRuntimeProtocolById.assert_not_called()


def test_UpdateFromSetRestoresStateWhenRefreshFails():
    mapper = buildMapper()

    parentProtocol = Object()

    parentProtocol.setObjId(
        200
    )

    runtimeSet = ExampleSet()

    runtimeSet.setObjId(
        300
    )

    runtimeSet._objParent = (
        parentProtocol
    )

    runtimeSet.runtimeMarker = "before"

    previousMapper = Mock()
    runtimeSet._mapper = previousMapper

    failedMapper = Mock()

    factory = FakeRuntimeSetFactory(
        cachedSet=runtimeSet
    )

    def failBuild(
            **kwargs,
    ):
        runtimeSet.runtimeMarker = (
            "partial"
        )

        runtimeSet._mapper = (
            failedMapper
        )

        raise RuntimeError(
            "forced set refresh failure"
        )

    factory.build = failBuild

    mapper.protocolGraphRepository = (
        FakeProtocolGraphRepository(
            outputInfo=buildOutputInfo()
        )
    )

    mapper.runtimeSetFactory = factory

    with pytest.raises(
            RuntimeError,
            match=(
                "forced set refresh failure"
            ),
    ):
        mapper.updateFrom(
            runtimeSet
        )

    assert runtimeSet.runtimeMarker == (
        "before"
    )

    assert runtimeSet._mapper is (
        previousMapper
    )

    assert failedMapper.close.call_count == 1
    assert previousMapper.close.call_count == 0

    assert factory.cacheWrites == []

