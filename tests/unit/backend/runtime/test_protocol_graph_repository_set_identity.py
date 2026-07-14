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

from app.backend.runtime.protocol_graph_repository import (
    ProtocolGraphRepository,
)


class FakeDb:
    def __init__(
            self,
            rows=None,
    ):
        self.rows = list(
            rows or []
        )

        self.calls = []

    def fetchAll(
            self,
            query,
            params=None,
    ):
        self.calls.append({
            "query": " ".join(
                str(query).split()
            ),
            "params": params,
        })

        return [
            dict(row)
            for row in self.rows
        ]


class FakeMapper:
    def __init__(
            self,
            rows=None,
    ):
        self.db = FakeDb(
            rows=rows
        )


def buildSetRow():
    return {
        "setId": 31,
        "projectId": 4,
        "protocolDbId": 10,
        "protocolId": "100",
        "objectId": 401,
        "runtimeObjectId": 300,
        "outputName": "outputParticles",
        "className": "SetOfParticles",
        "itemClassName": "Particle",
        "properties": {
            "_samplingRate": 1.5,
        },
    }


def test_GetPersistedSetOutputRowByRuntimeObjectId():
    mapper = FakeMapper(
        rows=[
            buildSetRow(),
        ]
    )

    repository = (
        ProtocolGraphRepository()
    )

    result = (
        repository
        .getPersistedSetOutputRowByRuntimeObjectId(
            mapper=mapper,
            projectId=4,
            runtimeObjectId=300,
        )
    )

    assert result == buildSetRow()

    assert len(
        mapper.db.calls
    ) == 1

    call = mapper.db.calls[0]

    assert (
        "FROM scipion_sets s"
        in call["query"]
    )

    assert (
        "JOIN scipion_objects o"
        in call["query"]
    )

    assert (
        'o."scipionObjId" = %s'
        in call["query"]
    )

    assert (
        's."objectId" = %s'
        not in call["query"]
    )

    assert call["params"] == (
        4,
        300,
    )


def test_GetPersistedSetOutputRowByRuntimeObjectIdReturnsNone():
    mapper = FakeMapper(
        rows=[]
    )

    result = (
        ProtocolGraphRepository()
        .getPersistedSetOutputRowByRuntimeObjectId(
            mapper=mapper,
            projectId=4,
            runtimeObjectId=999,
        )
    )

    assert result is None


def test_GetPersistedSetOutputRowByRuntimeObjectIdRejectsAmbiguity():
    mapper = FakeMapper(
        rows=[
            buildSetRow(),
            {
                **buildSetRow(),
                "setId": 32,
                "outputName": (
                    "duplicatedOutput"
                ),
            },
        ]
    )

    with pytest.raises(
            ValueError,
            match=(
                "More than one PostgreSQL set"
            ),
    ):
        (
            ProtocolGraphRepository()
            .getPersistedSetOutputRowByRuntimeObjectId(
                mapper=mapper,
                projectId=4,
                runtimeObjectId=300,
            )
        )


@pytest.mark.parametrize(
    (
        "projectId",
        "runtimeObjectId",
        "expectedMessage",
    ),
    [
        (
            None,
            300,
            "projectId is required",
        ),
        (
            4,
            None,
            "runtimeObjectId is required",
        ),
    ],
)
def test_GetPersistedSetOutputRowByRuntimeObjectIdValidatesIdentity(
        projectId,
        runtimeObjectId,
        expectedMessage,
):
    mapper = FakeMapper()

    with pytest.raises(
            ValueError,
            match=expectedMessage,
    ):
        (
            ProtocolGraphRepository()
            .getPersistedSetOutputRowByRuntimeObjectId(
                mapper=mapper,
                projectId=projectId,
                runtimeObjectId=runtimeObjectId,
            )
        )