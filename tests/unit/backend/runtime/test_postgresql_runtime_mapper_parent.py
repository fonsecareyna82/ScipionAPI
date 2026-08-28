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
# ******************************************************************************
import pytest

from app.backend.mapper.postgresql_runtime_mapper import (
    PostgresqlRuntimeMapper,
)


class FakeObject:
    def __init__(self, parentId=None):
        self._objParentId = parentId

    def getObjParentId(self):
        return self._objParentId


class FakeObjectWithoutGetter:
    def __init__(self, parentId=None):
        self._objParentId = parentId


def buildRuntimeMapper():
    mapper = PostgresqlRuntimeMapper.__new__(
        PostgresqlRuntimeMapper
    )

    resolvedIds = []
    resolvedParent = object()

    def selectRelationObjectById(objId):
        resolvedIds.append(
            objId
        )

        return resolvedParent

    mapper._selectRelationObjectById = (
        selectRelationObjectById
    )

    def failIfGeneralSelectorIsUsed(objId):
        raise AssertionError(
            "getParent must use the read-only resolver"
        )

    mapper.selectById = (
        failIfGeneralSelectorIsUsed
    )

    def failIfRuntimeContextIsAttached(obj):
        raise AssertionError(
            "getParent must not mutate or reattach the parent"
        )

    mapper._attachRuntimeContext = (
        failIfRuntimeContextIsAttached
    )

    return (
        mapper,
        resolvedParent,
        resolvedIds,
    )


def test_GetParentUsesReadOnlyResolver():
    (
        mapper,
        resolvedParent,
        resolvedIds,
    ) = buildRuntimeMapper()

    child = FakeObject(
        parentId="401",
    )

    result = mapper.getParent(
        child
    )

    assert result is resolvedParent

    assert resolvedIds == [
        401,
    ]


def test_GetParentReturnsAttachedParentUnchanged():
    (
        mapper,
        resolvedParent,
        resolvedIds,
    ) = buildRuntimeMapper()

    attachedParent = object()

    child = FakeObject(
        parentId=401,
    )
    child._objParent = (
        attachedParent
    )

    result = mapper.getParent(
        child
    )

    assert result is attachedParent
    assert resolvedIds == []


def test_GetParentSupportsRawParentAttribute():
    (
        mapper,
        resolvedParent,
        resolvedIds,
    ) = buildRuntimeMapper()

    child = FakeObjectWithoutGetter(
        parentId=501,
    )

    result = mapper.getParent(
        child
    )

    assert result is resolvedParent

    assert resolvedIds == [
        501,
    ]


def test_GetParentReturnsNoneWithoutParentId():
    (
        mapper,
        resolvedParent,
        resolvedIds,
    ) = buildRuntimeMapper()

    result = mapper.getParent(
        FakeObject()
    )

    assert result is None
    assert resolvedIds == []


def test_GetParentReturnsNoneForInvalidParentId():
    (
        mapper,
        resolvedParent,
        resolvedIds,
    ) = buildRuntimeMapper()

    result = mapper.getParent(
        FakeObject(
            parentId="invalid",
        )
    )

    assert result is None
    assert resolvedIds == []


def test_GetParentReturnsNoneForMissingObject():
    (
        mapper,
        resolvedParent,
        resolvedIds,
    ) = buildRuntimeMapper()

    result = mapper.getParent(
        None
    )

    assert result is None
    assert resolvedIds == []


class FakePostgresqlRuntimeSet:
    def __init__(
            self,
            parentId,
    ):
        self._objParent = None
        self._objParentId = parentId

    def getObjParentId(self):
        return self._objParentId

    def isPostgresqlRuntimeOutput(self):
        return True


class FakeParentProtocol:
    def __init__(
            self,
            protocolId,
    ):
        self._protocolId = protocolId

    def getObjId(self):
        return self._protocolId


class FakeRuntimeSetFactory:
    def __init__(self):
        self.calls = []

    def build(
            self,
            **kwargs,
    ):
        self.calls.append(
            kwargs
        )

        return {
            "outputName": kwargs[
                "outputName"
            ],
        }


def test_GetParentRestoresPersistedSetOutputs():
    mapper = PostgresqlRuntimeMapper.__new__(
        PostgresqlRuntimeMapper
    )

    mapper.projectId = 4
    mapper.db = object()
    mapper.dictClasses = {}

    parentProtocol = FakeParentProtocol(
        protocolId=100,
    )

    class FakeFlatMapper:
        def getProjectProtocolByProtocolId(
                self,
                projectId,
                protocolId,
        ):
            assert projectId == 4
            assert protocolId == 100

            return {
                "protocolId": 100,
                "protocolClassName": (
                    "FakeProducer"
                ),
            }

    class FakeRepository:
        def listPersistedSetOutputRows(
                self,
                mapper,
                projectId,
                protocolId=None,
                className=None,
        ):
            assert projectId == 4
            assert protocolId == 100

            return [
                {
                    "runtimeObjectId": 501,
                    "outputName": (
                        "outputMovies"
                    ),
                    "className": (
                        "SetOfMovies"
                    ),
                    "itemClassName": (
                        "Movie"
                    ),
                    "setId": 10,
                    "properties": {},
                },
                {
                    "runtimeObjectId": 502,
                    "outputName": (
                        "outputMicrographsDoseWeighted"
                    ),
                    "className": (
                        "SetOfMicrographs"
                    ),
                    "itemClassName": (
                        "Micrograph"
                    ),
                    "setId": 11,
                    "properties": {},
                },
            ]

    mapper.flatMapper = FakeFlatMapper()
    mapper.protocolGraphRepository = (
        FakeRepository()
    )

    mapper.runtimeSetFactory = (
        FakeRuntimeSetFactory()
    )

    mapper._buildProtocolFromPostgresqlRow = (
        lambda row: parentProtocol
    )

    mapper._selectRelationObjectById = (
        lambda objId: (
            pytest.fail(
                "PostgreSQL runtime Set parent "
                "must use detached protocol view"
            )
        )
    )

    child = FakePostgresqlRuntimeSet(
        parentId=100,
    )

    result = mapper.getParent(
        child
    )

    assert result is parentProtocol

    assert hasattr(
        result,
        "outputMovies",
    )

    assert hasattr(
        result,
        "outputMicrographsDoseWeighted",
    )

    assert (
        result
        .outputMicrographsDoseWeighted[
            "outputName"
        ]
        == "outputMicrographsDoseWeighted"
    )

    assert len(
        mapper.runtimeSetFactory.calls
    ) == 2

    assert all(
        call["cache"] is False
        for call
        in mapper.runtimeSetFactory.calls
    )


