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
from datetime import datetime, timezone

import pytest

from pyworkflow.object import String
from pyworkflow.project.project import PROJECT_CREATION_TIME

from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.mapper.postgresql_runtime_mapper import (
    PostgresqlRuntimeMapper,
)


class FakeDb:
    def __init__(self, projectRow=None):
        self.projectRow = projectRow
        self.calls = []
        self.fetchAllCalls = []

    def fetchOne(self, query, params=None):
        normalizedQuery = " ".join(str(query).split())

        self.calls.append({
            "query": normalizedQuery,
            "params": params,
        })

        if "FROM projects" in normalizedQuery:
            return self.projectRow

        return None

    def fetchAll(
            self,
            query,
            params=None,
    ):
        self.fetchAllCalls.append({
            "query": " ".join(
                str(
                    query
                ).split()
            ),
            "params": params,
        })

        return []


class FakeFallbackMapper:
    def __init__(self, values=None):
        self.values = list(values or [])
        self.calls = []

    def selectBy(
            self,
            iterate=False,
            objectFilter=None,
            **args,
    ):
        self.calls.append({
            "iterate": iterate,
            "objectFilter": objectFilter,
            "args": args,
        })

        result = list(self.values)

        if callable(objectFilter):
            result = [obj for obj in result if objectFilter(obj)]

        return iter(result) if iterate else result


def buildMapper(projectRow=None, fallback=None):
    db = FakeDb(projectRow)
    flatMapper = PostgresqlFlatMapper(db)

    mapper = PostgresqlRuntimeMapper(
        flatMapper=flatMapper,
        projectId=4,
        dictClasses={},
        readFallbackMapper=fallback,
    )

    return mapper, db


def buildCreationTime(value):
    creationTime = String(value)
    creationTime.setName(PROJECT_CREATION_TIME)
    return creationTime


def test_GetProjectRuntimeMetadataNormalizesColumnNames():
    createdAt = datetime(2026, 7, 14, 16, 30, 5)
    updatedAt = datetime(2026, 7, 14, 17, 30, 5)

    db = FakeDb({
        "id": 4,
        "createdat": createdAt,
        "updatedat": updatedAt,
    })

    flatMapper = PostgresqlFlatMapper(db)
    result = flatMapper.getProjectRuntimeMetadata(4)

    assert result["createdAt"] == createdAt
    assert result["updatedAt"] == updatedAt

    assert db.calls == [{
        "query": "SELECT * FROM projects WHERE id = %s",
        "params": (4,),
    }]


def test_SelectByNormalizesTimezoneAwareCreationTime():
    createdAt = datetime(
        2026,
        7,
        14,
        16,
        30,
        5,
        tzinfo=timezone.utc,
    )

    mapper, _ = buildMapper({
        "id": 4,
        "createdAt": createdAt,
    })

    result = mapper.selectBy(
        name=PROJECT_CREATION_TIME
    )

    assert result[0].datetime() == datetime(
        2026,
        7,
        14,
        16,
        30,
        5,
    )


def test_SelectByAppliesCreationTimeObjectFilter():
    mapper, _ = buildMapper({
        "id": 4,
        "createdAt": datetime(2026, 7, 14, 16, 30, 5),
    })

    result = mapper.selectBy(
        name=PROJECT_CREATION_TIME,
        objectFilter=lambda obj: False,
    )

    assert result == []


def test_SelectByDoesNotUseFallbackWhenProjectMetadataIsMissing():
    legacyCreationTime = buildCreationTime(
        "2025-06-18 10:20:30.000000"
    )

    fallback = FakeFallbackMapper([
        legacyCreationTime,
    ])

    mapper, _ = buildMapper(
        projectRow=None,
        fallback=fallback,
    )

    result = mapper.selectBy(
        name=PROJECT_CREATION_TIME
    )

    assert result == []
    assert fallback.calls == []


def test_SelectByReturnsEmptyCreationTimeWithoutFallback():
    mapper, _ = buildMapper(projectRow=None)

    result = mapper.selectBy(
        name=PROJECT_CREATION_TIME
    )

    assert result == []


def test_SelectByDoesNotUseFallbackWhenPostgresqlHasNoMatchingObject():
    legacyObject = String("legacy")
    fallback = FakeFallbackMapper([legacyObject])

    mapper, db = buildMapper(
        projectRow={
            "id": 4,
            "createdAt": datetime(2026, 7, 14, 16, 30, 5),
        },
        fallback=fallback,
    )

    result = mapper.selectBy(
        name="OtherRootObject"
    )

    assert result == []
    assert db.fetchAllCalls
    assert fallback.calls == []


def test_SelectByRejectsInvalidFilterWithoutUsingFallback():
    fallback = FakeFallbackMapper()
    mapper, _ = buildMapper(fallback=fallback)

    with pytest.raises(
            TypeError,
            match="objectFilter must be callable or None",
    ):
        mapper.selectBy(
            name=PROJECT_CREATION_TIME,
            objectFilter="invalid",
        )

    assert fallback.calls == []


def test_SelectByRejectsUnsupportedFieldsWithoutUsingFallback():
    fallback = FakeFallbackMapper()
    mapper, _ = buildMapper(fallback=fallback)

    with pytest.raises(
            NotImplementedError,
            match="PostgreSQL selectBy does not support query fields",
    ):
        mapper.selectBy(
            unsupportedField="value"
        )

    assert fallback.calls == []