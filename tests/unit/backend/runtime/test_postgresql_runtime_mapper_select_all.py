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
# ******************************************************************************
# *
# * Authors:     Yunior C. Fonseca Reyna
# *
# * Unidad de Bioinformatica of Centro Nacional de Biotecnologia, CSIC
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
    def __init__(self, objId):
        self._objId = objId

    def getObjId(self):
        return self._objId


def buildRuntimeMapper(batchResult):
    mapper = PostgresqlRuntimeMapper.__new__(
        PostgresqlRuntimeMapper
    )

    batchCalls = []

    def selectAllBatch(objectFilter=None):
        batchCalls.append(
            objectFilter
        )

        return list(
            batchResult
        )

    mapper.selectAllBatch = (
        selectAllBatch
    )

    return mapper, batchCalls


def test_SelectAllUsesPostgresqlBatchPath():
    objects = [
        FakeObject(101),
        FakeObject(102),
    ]

    mapper, batchCalls = buildRuntimeMapper(
        objects
    )

    objectFilter = lambda obj: (
        obj.getObjId() > 100
    )

    result = mapper.selectAll(
        iterate=False,
        objectFilter=objectFilter,
    )

    assert result == objects

    assert batchCalls == [
        objectFilter,
    ]


def test_SelectAllReturnsIteratorWhenRequested():
    objects = [
        FakeObject(201),
        FakeObject(202),
    ]

    mapper, batchCalls = buildRuntimeMapper(
        objects
    )

    result = mapper.selectAll(
        iterate=True,
    )

    assert iter(result) is result

    assert list(result) == objects

    assert batchCalls == [
        None,
    ]


def test_SelectAllPropagatesBatchFilterValidation():
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