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
from pyworkflow.object import (
    Object,
    Set,
)

from app.backend.mapper.postgresql_runtime_mapper import (
    PostgresqlRuntimeMapper,
)


class ExampleItem(Object):
    pass


class ExampleSet(Set):
    ITEM_TYPE = ExampleItem


class FakeDb:
    def __init__(
            self,
            protocolExists=False,
    ):
        self.protocolExists = bool(
            protocolExists
        )

        self.calls = []

    def fetchOne(
            self,
            query,
            params=None,
    ):
        normalizedQuery = " ".join(
            str(query).split()
        )

        self.calls.append({
            "query": normalizedQuery,
            "params": params,
        })

        if (
                "FROM protocols"
                in normalizedQuery
                and self.protocolExists
        ):
            return {
                "id": 20,
            }

        return None


class FakeFlatMapper:
    def __init__(
            self,
            db,
    ):
        self.db = db

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
        self.fail = bool(
            fail
        )

        self.calls = []

    def getPersistedSetOutputRowByRuntimeObjectId(
            self,
            mapper,
            projectId,
            runtimeObjectId,
    ):
        if self.fail:
            raise AssertionError(
                "PostgreSQL set repository "
                "must not be called"
            )

        self.calls.append({
            "mapper": mapper,
            "projectId": projectId,
            "runtimeObjectId": (
                runtimeObjectId
            ),
        })

        return self.outputInfo


class FakeRuntimeSetFactory:
    def __init__(
            self,
            cachedSet=None,
            fail=False,
    ):
        self.cachedSet = cachedSet
        self.fail = bool(
            fail
        )

        self.lookups = []

    def _getCachedRuntimeSet(
            self,
            projectId,
            runtimeObjectId,
    ):
        if self.fail:
            raise AssertionError(
                "PostgreSQL set cache "
                "must not be checked"
            )

        self.lookups.append(
            (
                projectId,
                runtimeObjectId,
            )
        )

        return self.cachedSet


class FakeFallbackMapper:
    def __init__(
            self,
            existsResult=False,
            parent=None,
            failExists=False,
            failGetParent=False,
    ):
        self.existsResult = bool(
            existsResult
        )

        self.parent = parent

        self.failExists = bool(
            failExists
        )

        self.failGetParent = bool(
            failGetParent
        )

        self.existsCalls = []
        self.parentCalls = []

    def exists(
            self,
            objId,
    ):
        if self.failExists:
            raise AssertionError(
                "SQLite exists() must not be called"
            )

        self.existsCalls.append(
            objId
        )

        return self.existsResult

    def getParent(
            self,
            obj,
    ):
        if self.failGetParent:
            raise AssertionError(
                "SQLite getParent() must not be called"
            )

        self.parentCalls.append(
            obj
        )

        return self.parent


def buildMapper(
        protocolExists=False,
        fallbackMapper=None,
):
    db = FakeDb(
        protocolExists=protocolExists
    )

    mapper = PostgresqlRuntimeMapper(
        flatMapper=FakeFlatMapper(
            db
        ),
        projectId=4,
        dictClasses={
            "ExampleSet": ExampleSet,
            "ExampleItem": ExampleItem,
        },
        readFallbackMapper=(
            fallbackMapper
        ),
    )

    return mapper, db


def buildSetOutputInfo():
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


def test_ExistsReturnsTrueForPostgresqlProtocol():
    fallback = FakeFallbackMapper(
        failExists=True
    )

    mapper, _ = buildMapper(
        protocolExists=True,
        fallbackMapper=fallback,
    )

    mapper.runtimeSetFactory = (
        FakeRuntimeSetFactory(
            fail=True
        )
    )

    mapper.protocolGraphRepository = (
        FakeProtocolGraphRepository(
            fail=True
        )
    )

    assert mapper.exists(
        200
    ) is True


def test_ExistsReturnsTrueForCachedPostgresqlSet():
    fallback = FakeFallbackMapper(
        failExists=True
    )

    mapper, _ = buildMapper(
        fallbackMapper=fallback
    )

    runtimeSet = ExampleSet()

    runtimeSet.setObjId(
        300
    )

    mapper.runtimeSetFactory = (
        FakeRuntimeSetFactory(
            cachedSet=runtimeSet
        )
    )

    mapper.protocolGraphRepository = (
        FakeProtocolGraphRepository(
            fail=True
        )
    )

    assert mapper.exists(
        300
    ) is True

    assert (
        mapper.runtimeSetFactory.lookups
        == [
            (
                4,
                300,
            )
        ]
    )


def test_ExistsReturnsTrueForPersistedPostgresqlSet():
    fallback = FakeFallbackMapper(
        failExists=True
    )

    mapper, _ = buildMapper(
        fallbackMapper=fallback
    )

    mapper.runtimeSetFactory = (
        FakeRuntimeSetFactory()
    )

    repository = (
        FakeProtocolGraphRepository(
            outputInfo=(
                buildSetOutputInfo()
            )
        )
    )

    mapper.protocolGraphRepository = (
        repository
    )

    assert mapper.exists(
        300
    ) is True

    assert repository.calls == [
        {
            "mapper": mapper,
            "projectId": 4,
            "runtimeObjectId": 300,
        }
    ]


def test_ExistsUsesSqliteFallbackLast():
    fallback = FakeFallbackMapper(
        existsResult=True
    )

    mapper, _ = buildMapper(
        fallbackMapper=fallback
    )

    mapper.runtimeSetFactory = (
        FakeRuntimeSetFactory()
    )

    mapper.protocolGraphRepository = (
        FakeProtocolGraphRepository(
            outputInfo=None
        )
    )

    assert mapper.exists(
        999
    ) is True

    assert fallback.existsCalls == [
        999
    ]


def test_GetParentReturnsNativeHydratedParent():
    fallback = FakeFallbackMapper(
        failGetParent=True
    )

    mapper, _ = buildMapper(
        fallbackMapper=fallback
    )

    parentSet = ExampleSet()

    parentSet.setObjId(
        300
    )

    item = ExampleItem()

    item.setObjId(
        7
    )

    item._objParent = parentSet
    item._objParentId = 300

    assert mapper.getParent(
        item
    ) is parentSet


def test_GetParentResolvesRuntimeParentIdBeforeFallback():
    fallback = FakeFallbackMapper(
        failGetParent=True
    )

    mapper, _ = buildMapper(
        fallbackMapper=fallback
    )

    parentSet = ExampleSet()

    parentSet.setObjId(
        300
    )

    item = ExampleItem()

    item.setObjId(
        7
    )

    item._objParent = None
    item._objParentId = 300

    selectedIds = []

    def selectRelationObjectById(
            objId,
    ):
        selectedIds.append(
            objId
        )

        if int(objId) == 300:
            return parentSet

        return None

    mapper._selectRelationObjectById = (
        selectRelationObjectById
    )

    assert mapper.getParent(
        item
    ) is parentSet

    assert selectedIds == [
        300
    ]


def test_GetParentUsesSqliteFallbackLast():
    fallbackParent = Object()

    fallbackParent.setObjId(
        400
    )

    fallback = FakeFallbackMapper(
        parent=fallbackParent
    )

    mapper, _ = buildMapper(
        fallbackMapper=fallback
    )

    item = ExampleItem()

    item.setObjId(
        7
    )

    item._objParent = None
    item._objParentId = None

    assert mapper.getParent(
        item
    ) is fallbackParent

    assert fallback.parentCalls == [
        item
    ]