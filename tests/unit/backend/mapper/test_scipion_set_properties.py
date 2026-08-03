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
from contextlib import contextmanager
from pyworkflow.object import (
    Float,
    Integer,
    Object,
    Set as ScipionSet,
)

from app.backend.mapper.scipion_set_mapper import (
    NESTED_LOGICAL_TABLES_VERSION,
    SET_PROPERTIES_VERSION,
    ScipionSetPostgresqlMapper,
)


class ExampleAcquisition(Object):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._voltage = Float()
        self._magnification = Float()


class FakeSetLifecycleDb:
    def __init__(self, storedSets=None):
        self.storedSets = list(storedSets or [])
        self.fetchAllCalls = []
        self.executeCalls = []
        self.transactionCalls = 0

    @contextmanager
    def transaction(self):
        self.transactionCalls += 1
        yield

    def fetchAll(
            self,
            query,
            params=None,
    ):
        self.fetchAllCalls.append({
            "query": query,
            "params": params,
        })

        return list(self.storedSets)

    def execute(
            self,
            query,
            params=None,
            commit=True,
    ):
        self.executeCalls.append({
            "query": query,
            "params": params,
            "commit": commit,
        })


class ExampleSet(Object):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._size = Integer(3)
        self._streamState = Integer(2)
        self._acquisition = ExampleAcquisition()

        self._acquisition._voltage.set(300.0)
        self._acquisition._magnification.set(50000.0)

    def getFileName(self):
        return None

    def getStreamState(self):
        return self._streamState.get()


class ExampleTomogram(Object):
    def __init__(
            self,
            objectId=7,
            tsId="TS_01",
    ):
        super().__init__()

        self.setObjId(
            objectId
        )

        self.tsId = tsId

    def getTsId(self):
        return self.tsId

    def getObjLabel(self):
        return (
            "Tomogram %s"
            % self.tsId
        )

    def getDim(self):
        return (
            64,
            64,
            32,
        )

    def getSamplingRate(self):
        return 2.5

    def getFileName(self):
        return (
            "/tmp/%s.mrc"
            % self.tsId
        )


class DeferredLinkedTomogramsSet(
        ExampleSet
):
    def __init__(
            self,
            **kwargs,
    ):
        super().__init__(
            **kwargs
        )

        self.linkedTomograms = None

    def iterVolumes(self):
        return self.linkedTomograms


def test_GetSetPropertiesIncludesNestedAttributes():
    scipionSet = ExampleSet()
    scipionSet.setObjId(41)

    mapper = ScipionSetPostgresqlMapper(
        db=None,
    )

    properties = mapper._getSetProperties(
        scipionSet
    )

    assert properties["scipionObjId"] == 41
    assert properties["_size"] == 3
    assert properties["_streamState"] == 2
    assert properties["_acquisition._voltage"] == 300.0
    assert properties["_acquisition._magnification"] == 50000.0

    # Complex parent objects normally have value None and should not be
    # persisted as a scalar property.
    assert "_acquisition" not in properties


def test_OldSetPropertiesVersionForcesSynchronization():
    mapper = ScipionSetPostgresqlMapper(
        db=None,
    )

    existingProperties = {
        "incremental": True,
        "nestedTablesVersion": NESTED_LOGICAL_TABLES_VERSION,
        "setPropertiesVersion": SET_PROPERTIES_VERSION - 1,
        "itemsCount": 3,
        "maxItemId": 3,
        "sourceMTime": 10.0,
    }

    assert mapper._shouldSkipSetSync(
        existingProperties=existingProperties,
        itemsCountHint=3,
        maxItemIdHint=3,
        sourceMTime=10.0,
    ) is False


def test_CurrentSetPropertiesVersionAllowsUnchangedSetSkip():
    mapper = ScipionSetPostgresqlMapper(
        db=None,
    )

    existingProperties = {
        "incremental": True,
        "nestedTablesVersion": NESTED_LOGICAL_TABLES_VERSION,
        "setPropertiesVersion": SET_PROPERTIES_VERSION,
        "itemsCount": 3,
        "maxItemId": 3,
        "sourceMTime": 10.0,
    }

    assert mapper._shouldSkipSetSync(
        existingProperties=existingProperties,
        itemsCountHint=3,
        maxItemIdHint=3,
        sourceMTime=10.0,
    ) is True


def test_LinkedTomogramSummaryAllowsDeferredPrecedents():
    scipionSet = (
        DeferredLinkedTomogramsSet()
    )

    scipionSet.setObjId(
        41
    )

    mapper = (
        ScipionSetPostgresqlMapper(
            db=None,
        )
    )

    # Models the PostgreSQL reservation performed inside
    # _createSet(), before setPrecedents() is called.
    reservedProperties = (
        mapper._getSetProperties(
            scipionSet
        )
    )

    assert (
        "linkedTomograms"
        not in reservedProperties
    )

    assert list(
        mapper._iterLinkedTomograms(
            scipionSet
        )
    ) == []

    # Models SetOfCoordinates3D.setPrecedents() after
    # _createSet() returns to the tomo protocol helper.
    tomogram = ExampleTomogram()

    scipionSet.linkedTomograms = [
        tomogram,
    ]

    finalizedProperties = (
        mapper._getSetProperties(
            scipionSet
        )
    )

    assert (
        finalizedProperties[
            "linkedTomograms"
        ]
        == [
            {
                "id": "TS_01",
                "tomoId": "TS_01",
                "label": "TS_01",
                "name": "Tomogram TS_01",
                "objectId": "7",
                "volumeId": "7",
                "tsId": "TS_01",
                "tiltSeriesId": "TS_01",
                "fileName": (
                    "/tmp/TS_01.mrc"
                ),
                "dims": [
                    64,
                    64,
                    32,
                ],
                "voxelSize": [
                    2.5,
                    2.5,
                    2.5,
                ],
            },
        ]
    )


def test_LinkedTomogramSummarySupportsScipionSets():
    tomogram = ExampleTomogram()

    class ExampleTomogramSet:
        def iterItems(
                self,
                iterate=True,
        ):
            return [
                tomogram,
            ]

    mapper = (
        ScipionSetPostgresqlMapper(
            db=None,
        )
    )

    iterator = (
        mapper
        ._coerceLinkedTomogramIterator(
            ExampleTomogramSet()
        )
    )

    assert list(
        iterator
    ) == [
        tomogram,
    ]


def test_CloseProtocolOutputSetsUpdatesJsonAndNormalizedProperties():
    database = FakeSetLifecycleDb([
        {
            "id": 100,
            "outputName": "outputParticles",
        },
        {
            "id": 101,
            "outputName": "outputAverages",
        },
    ])

    mapper = ScipionSetPostgresqlMapper(
        db=database
    )

    result = mapper.closeProtocolOutputSets(
        projectId=7,
        protocolDbId=31,
    )

    closedState = int(
        ScipionSet.STREAM_CLOSED
    )

    assert result == {
        "protocolDbId": 31,
        "setsClosed": 2,
        "outputs": [
            "outputParticles",
            "outputAverages",
        ],
    }

    assert database.transactionCalls == 1
    assert len(database.fetchAllCalls) == 1
    assert database.fetchAllCalls[0]["params"] == (
        7,
        31,
    )

    assert len(database.executeCalls) == 3

    setUpdate = database.executeCalls[0]

    assert "UPDATE scipion_sets" in setUpdate["query"]
    assert "streamState" in setUpdate["query"]
    assert "_streamState" in setUpdate["query"]
    assert setUpdate["params"] == (
        closedState,
        closedState,
        7,
        31,
    )
    assert setUpdate["commit"] is False

    assert database.executeCalls[1]["params"] == (
        "streamState",
        str(closedState),
        7,
        31,
    )

    assert database.executeCalls[2]["params"] == (
        "_streamState",
        str(closedState),
        7,
        31,
    )

    assert all(
        call["commit"] is False
        for call in database.executeCalls
    )


def test_CloseProtocolOutputSetsDoesNothingWithoutStoredSets():
    database = FakeSetLifecycleDb()
    mapper = ScipionSetPostgresqlMapper(
        db=database
    )

    result = mapper.closeProtocolOutputSets(
        projectId=7,
        protocolDbId=31,
    )

    assert result == {
        "protocolDbId": 31,
        "setsClosed": 0,
        "outputs": [],
    }

    assert database.transactionCalls == 0
    assert database.executeCalls == []

