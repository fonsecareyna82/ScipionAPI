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

    mapper.readFallbackMapper = None

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