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

from app.backend.mapper.postgresql_runtime_mapper import (
    PostgresqlRuntimeMapper,
)


class FakeObject:
    def __init__(
            self,
            objId,
            parentId=None,
            name=None,
    ):
        self._objId = objId
        self._objParentId = parentId
        self._objName = name

    def getObjId(self):
        return self._objId


def buildRuntimeMapper(
        batchResult,
        creationTime=None,
):
    mapper = PostgresqlRuntimeMapper.__new__(
        PostgresqlRuntimeMapper
    )

    batchCalls = []
    creationTimeCalls = []

    def selectAllBatch(objectFilter=None):
        batchCalls.append(
            objectFilter
        )

        return [
            obj
            for obj in batchResult
            if (
                    objectFilter is None
                    or objectFilter(obj)
            )
        ]

    def selectProjectCreationTime():
        creationTimeCalls.append(
            True
        )

        return creationTime

    mapper.selectAllBatch = (
        selectAllBatch
    )

    mapper._selectProjectCreationTimeFromPostgresql = (
        selectProjectCreationTime
    )

    return (
        mapper,
        batchCalls,
        creationTimeCalls,
    )


def test_SelectAllCombinesRootAndUserFilters():
    acceptedRoot = FakeObject(
        101
    )
    rejectedRoot = FakeObject(
        99
    )
    childObject = FakeObject(
        102,
        parentId=101,
    )

    (
        mapper,
        batchCalls,
        creationTimeCalls,
    ) = buildRuntimeMapper(
        [
            acceptedRoot,
            rejectedRoot,
            childObject,
        ],
        creationTime=None,
    )

    objectFilter = lambda obj: (
        obj.getObjId() >= 100
    )

    result = mapper.selectAll(
        iterate=False,
        objectFilter=objectFilter,
    )

    assert result == [
        acceptedRoot,
    ]

    assert len(
        batchCalls
    ) == 1

    rootFilter = batchCalls[0]

    assert callable(
        rootFilter
    )
    assert rootFilter(
        acceptedRoot
    )
    assert not rootFilter(
        rejectedRoot
    )
    assert not rootFilter(
        childObject
    )

    assert creationTimeCalls == [
        True,
    ]


def test_SelectAllAddsPostgresqlCreationTime():
    protocol = FakeObject(
        201
    )
    creationTime = FakeObject(
        None,
        name="CreationTime",
    )

    (
        mapper,
        batchCalls,
        creationTimeCalls,
    ) = buildRuntimeMapper(
        [
            protocol,
        ],
        creationTime=creationTime,
    )

    result = mapper.selectAll()

    assert result == [
        creationTime,
        protocol,
    ]

    assert len(
        batchCalls
    ) == 1

    assert creationTimeCalls == [
        True,
    ]


def test_SelectAllDoesNotDuplicateExistingCreationTime():
    protocol = FakeObject(
        201
    )
    existingCreationTime = FakeObject(
        1,
        name="CreationTime",
    )
    postgresqlCreationTime = FakeObject(
        None,
        name="CreationTime",
    )

    (
        mapper,
        batchCalls,
        creationTimeCalls,
    ) = buildRuntimeMapper(
        [
            protocol,
            existingCreationTime,
        ],
        creationTime=postgresqlCreationTime,
    )

    result = mapper.selectAll()

    assert result == [
        existingCreationTime,
        protocol,
    ]

    assert len(
        batchCalls
    ) == 1

    assert creationTimeCalls == []


def test_SelectAllAppliesFilterToPostgresqlCreationTime():
    protocol = FakeObject(
        301
    )
    creationTime = FakeObject(
        None,
        name="CreationTime",
    )

    (
        mapper,
        batchCalls,
        creationTimeCalls,
    ) = buildRuntimeMapper(
        [
            protocol,
        ],
        creationTime=creationTime,
    )

    result = mapper.selectAll(
        objectFilter=lambda obj: (
            obj.getObjId() is not None
        ),
    )

    assert result == [
        protocol,
    ]

    assert len(
        batchCalls
    ) == 1

    assert creationTimeCalls == [
        True,
    ]


def test_SelectAllReturnsIteratorWhenRequested():
    creationTime = FakeObject(
        1,
        name="CreationTime",
    )
    protocol = FakeObject(
        401
    )

    (
        mapper,
        batchCalls,
        creationTimeCalls,
    ) = buildRuntimeMapper(
        [
            creationTime,
            protocol,
        ],
    )

    result = mapper.selectAll(
        iterate=True,
    )

    assert iter(result) is result

    assert list(result) == [
        creationTime,
        protocol,
    ]

    assert len(
        batchCalls
    ) == 1

    assert creationTimeCalls == []


def test_SelectAllRejectsInvalidFilter():
    mapper = PostgresqlRuntimeMapper.__new__(
        PostgresqlRuntimeMapper
    )

    with pytest.raises(
        TypeError,
        match="objectFilter must be callable or None",
    ):
        mapper.selectAll(
            objectFilter="not-callable",
        )