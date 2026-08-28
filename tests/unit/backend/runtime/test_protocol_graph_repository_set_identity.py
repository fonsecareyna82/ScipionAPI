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


def test_ListPersistedSetOutputRows():
    firstRow = buildSetRow()

    secondRow = {
        **buildSetRow(),
        "setId": 32,
        "protocolDbId": 11,
        "protocolId": "101",
        "objectId": 402,
        "runtimeObjectId": "301",
        "outputName": "outputVolumes",
        "className": "SetOfVolumes",
        "itemClassName": "Volume",
    }

    mapper = FakeMapper(
        rows=[
            firstRow,
            secondRow,
        ]
    )

    result = (
        ProtocolGraphRepository()
        .listPersistedSetOutputRows(
            mapper=mapper,
            projectId=4,
        )
    )

    assert result == [
        firstRow,
        {
            **secondRow,
            "runtimeObjectId": 301,
        },
    ]

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
        'o."scipionObjId" IS NOT NULL'
        in call["query"]
    )

    assert (
        's."setClassName" = %s'
        not in call["query"]
    )

    assert (
        'ORDER BY s."protocolDbId" ASC'
        in call["query"]
    )

    assert call["params"] == (
        4,
    )


def test_ListPersistedSetOutputRowsFiltersExactClass():
    mapper = FakeMapper(
        rows=[
            buildSetRow(),
        ]
    )

    result = (
        ProtocolGraphRepository()
        .listPersistedSetOutputRows(
            mapper=mapper,
            projectId=4,
            className="SetOfParticles",
        )
    )

    assert result == [
        buildSetRow(),
    ]

    call = mapper.db.calls[0]

    assert (
        's."setClassName" = %s'
        in call["query"]
    )

    assert call["params"] == (
        4,
        "SetOfParticles",
    )


def test_ListPersistedSetOutputRowsFiltersProtocol():
    mapper = FakeMapper(
        rows=[
            buildSetRow(),
        ]
    )

    result = (
        ProtocolGraphRepository()
        .listPersistedSetOutputRows(
            mapper=mapper,
            projectId=4,
            protocolId=100,
        )
    )

    assert result == [
        buildSetRow(),
    ]

    call = mapper.db.calls[0]

    assert (
        'p."protocolId" = %s'
        in call["query"]
    )

    assert call["params"] == (
        4,
        100,
    )


def test_ListPersistedSetOutputRowsSkipsMissingRuntimeIdentity():
    mapper = FakeMapper(
        rows=[
            {
                **buildSetRow(),
                "runtimeObjectId": None,
                "properties": {},
            },
            buildSetRow(),
        ]
    )

    result = (
        ProtocolGraphRepository()
        .listPersistedSetOutputRows(
            mapper=mapper,
            projectId=4,
        )
    )

    assert result == [
        buildSetRow(),
    ]


def test_ListPersistedSetOutputRowsRejectsDuplicateRuntimeIdentity():
    mapper = FakeMapper(
        rows=[
            buildSetRow(),
            {
                **buildSetRow(),
                "setId": 32,
                "outputName": "duplicatedOutput",
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
            .listPersistedSetOutputRows(
                mapper=mapper,
                projectId=4,
            )
        )


def test_ListPersistedSetOutputRowsValidatesProject():
    mapper = FakeMapper()

    with pytest.raises(
            ValueError,
            match="projectId is required",
    ):
        (
            ProtocolGraphRepository()
            .listPersistedSetOutputRows(
                mapper=mapper,
                projectId=None,
            )
        )


def test_LegacyRuntimeOutputRelationWriterIsRemoved():
    repository = ProtocolGraphRepository()

    assert not hasattr(
        repository,
        "replaceRuntimeOutputRelation",
    )


def test_LoadRuntimeOutputRelationsUsesRuntimeObjectIdentity():
    relationRow = {
        "relationId": 71,
        "relationName": "set_of_tilt_series",
        "sourceOutputName": "outputCtf",
        "targetOutputName": "outputTiltSeries",
        "metadata": {
            "getterName": "getSetOfTiltSeries",
            "setterName": "setSetOfTiltSeries",
        },
        "sourceSetId": 31,
        "sourceProtocolDbId": 10,
        "sourceProtocolId": "100",
        "sourceClassName": "SetOfCTFTomoSeries",
        "sourceItemClassName": "CTFTomoSeries",
        "targetSetId": 32,
        "targetProtocolDbId": 11,
        "targetProtocolId": "101",
        "targetClassName": "SetOfTiltSeries",
        "targetItemClassName": "TiltSeries",
    }

    mapper = FakeMapper(
        rows=[
            relationRow,
        ]
    )

    result = (
        ProtocolGraphRepository()
        .loadRuntimeOutputRelations(
            mapper=mapper,
            projectId=4,
            sourceProtocolDbId=10,
            sourceOutputName="outputCtf",
        )
    )

    assert result == [
        relationRow,
    ]

    query = mapper.db.calls[0][
        "query"
    ]

    assert (
        "FROM scipion_relations r"
        in query
    )

    assert (
        'source_object."scipionObjId" = r."parentObjId"'
        in query
    )

    assert (
        'target_object."scipionObjId" = r."childObjId"'
        in query
    )

    assert (
        "scipion_object_relations"
        not in query
    )

    assert mapper.db.calls[0][
        "params"
    ] == (
        4,
        10,
        "outputCtf",
    )


