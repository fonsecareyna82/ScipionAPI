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
import importlib


def _makeReader(authTestEnv):
    module = importlib.import_module(
        "app.backend.viewers.postgresql_integrated_context_reader"
    )

    return module.PostgresqlIntegratedContextReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputTomograms",
    )


def test_PostgresqlIntegratedContextReaderReportsMissingStoredSet(authTestEnv, monkeypatch):
    reader = _makeReader(authTestEnv)

    monkeypatch.setattr(reader, "_getRootStoredSet", lambda: None)

    result = reader.getContext()

    assert result is None
    assert reader.lastSkipReason == "stored_set_not_found"


def test_PostgresqlIntegratedContextReaderReportsUnsupportedRootKind(authTestEnv, monkeypatch):
    reader = _makeReader(authTestEnv)

    monkeypatch.setattr(
        reader,
        "_getRootStoredSet",
        lambda: {
            "id": 1,
            "objectId": 10,
            "protocolDbId": 500,
            "outputName": "outputParticles",
            "setClassName": "SetOfParticles",
            "itemClassName": "Particle",
            "items": [],
        },
    )

    result = reader.getContext()

    assert result is None
    assert reader.lastSkipReason == "unsupported_integrated_context_kind"


def test_PostgresqlIntegratedContextReaderBuildsRootTiltSeriesContext(authTestEnv, monkeypatch):
    reader = _makeReader(authTestEnv)

    monkeypatch.setattr(
        reader,
        "_getRootStoredSet",
        lambda: {
            "id": 1,
            "objectId": 10,
            "protocolDbId": 500,
            "outputName": "outputTiltSeries",
            "setClassName": "SetOfTiltSeries",
            "itemClassName": "TiltSeries",
            "properties": {"itemsCount": 1},
            "items": [],
        },
    )

    monkeypatch.setattr(reader, "_mergeRootRelations", lambda **kwargs: None)
    monkeypatch.setattr(reader, "_mergeExactInputRefs", lambda **kwargs: None)
    monkeypatch.setattr(reader, "_mergeRelatedStoredSets", lambda **kwargs: None)

    result = reader.getContext()

    assert result["root"] == {
        "projectId": 1,
        "protocolId": 500,
        "outputName": "outputTomograms",
        "outputClass": "SetOfTiltSeries",
    }

    assert result["links"]["tiltSeries"] == {
        "protocolId": 500,
        "outputName": "outputTomograms",
        "itemId": 10,
        "label": "outputTomograms",
        "status": "available",
    }

    assert result["summaries"]["tiltSeries"]["objectClass"] == "SetOfTiltSeries"
    assert result["summaries"]["tiltSeries"]["objectId"] == 10
    assert result["summaries"]["tiltSeries"]["size"] == 1
    assert result["relations"]["items"] == []


def test_PostgresqlIntegratedContextReaderAddsDerivedTomogramLinkForCoords3dRoot(
    authTestEnv,
    monkeypatch,
):
    reader = _makeReader(authTestEnv)

    storedSet = {
        "id": 1,
        "objectId": 10,
        "protocolDbId": 500,
        "outputName": "outputCoordinates",
        "setClassName": "SetOfCoordinates3D",
        "itemClassName": "Coordinate3D",
        "properties": {"itemsCount": 25},
        "items": [],
    }

    monkeypatch.setattr(reader, "_getRootStoredSet", lambda: storedSet)
    monkeypatch.setattr(reader, "_mergeExactInputRefs", lambda **kwargs: None)
    monkeypatch.setattr(reader, "_mergeRelatedStoredSets", lambda **kwargs: None)

    class FakeCoords3dReader:
        def __init__(self, db, projectId, protocolId, outputName):
            pass

        def listTomograms(self):
            return [
                {
                    "id": "TS_001",
                    "tomoId": "TS_001",
                    "label": "Tomogram TS_001",
                    "name": "Tomogram TS_001",
                    "dims": [64, 128, 256],
                    "nCoords": 25,
                },
            ]

    module = importlib.import_module(
        "app.backend.viewers.postgresql_integrated_context_reader"
    )

    monkeypatch.setattr(module, "PostgresqlCoords3dReader", FakeCoords3dReader)

    result = reader.getContext()

    assert result["links"]["coordinates3d"] == {
        "protocolId": 500,
        "outputName": "outputTomograms",
        "itemId": 10,
        "label": "outputTomograms",
        "status": "available",
    }

    assert result["links"]["tomogram"] == {
        "protocolId": 500,
        "outputName": "outputTomograms",
        "itemId": None,
        "label": "Tomograms",
        "status": "derived",
        "source": "coordinates3d",
    }

    assert result["summaries"]["tomogram"] == {
        "objectClass": "SetOfTomograms",
        "size": 1,
        "source": "coordinates3d",
    }

    assert result["relations"]["items"] == [
        {
            "key": "TS_001",
            "label": "Tomogram TS_001",
            "coordinatesTomogramId": "TS_001",
            "tomogramId": "TS_001",
        },
    ]


def test_PostgresqlIntegratedContextReaderMergesRelationAliases(authTestEnv):
    reader = _makeReader(authTestEnv)

    relationsByKey = {}

    reader._addRelation(
        relationsByKey,
        "TS_001",
        tiltSeriesId="TS_001",
        tsId="TS_001",
        label="TiltSeries TS_001",
    )

    reader._addRelation(
        relationsByKey,
        "TOMO_001",
        tomogramId="TOMO_001",
        sourceTomoId="TOMO_001",
        tiltSeriesId="TS_001",
        label="Tomogram TOMO_001",
    )

    assert list(relationsByKey.keys()) == ["TS_001"]
    assert relationsByKey["TS_001"]["tiltSeriesId"] == "TS_001"
    assert relationsByKey["TS_001"]["tomogramId"] == "TOMO_001"
    assert relationsByKey["TS_001"]["sourceTomoId"] == "TOMO_001"
    assert relationsByKey["TS_001"]["label"] == "Tomogram TOMO_001"


def test_PostgresqlIntegratedContextReaderClassifiesInputRefKinds(authTestEnv):
    reader = _makeReader(authTestEnv)

    assert reader._getInputRefKind({
        "objectClassName": "SetOfCTFTomoSeries",
    }) == "ctf"

    assert reader._getInputRefKind({
        "objectClassName": "SetOfTiltSeries",
    }) == "tiltSeries"

    assert reader._getInputRefKind({
        "objectClassName": "SetOfTiltSeriesM",
    }) == "tiltSeriesM"

    assert reader._getInputRefKind({
        "objectClassName": "SetOfTomograms",
    }) == "tomogram"

    assert reader._getInputRefKind({
        "objectClassName": "SetOfCoordinates3D",
    }) == "coordinates3d"

    assert reader._getInputRefKind({
        "objectClassName": "SetOfParticles",
    }) is None


def test_PostgresqlIntegratedContextReaderExpandsInputRefOutputNames(authTestEnv):
    reader = _makeReader(authTestEnv)

    assert reader._expandInputRefOutputNames("outputTomograms") == [
        "outputTomograms",
    ]

    assert reader._expandInputRefOutputNames("outputTomograms.someNestedOutput") == [
        "outputTomograms.someNestedOutput",
        "outputTomograms",
    ]

    assert reader._expandInputRefOutputNames("") == []
    assert reader._expandInputRefOutputNames(None) == []


def test_PostgresqlIntegratedContextReaderGetsStoredSetFromInputRefUsingExpandedNames(
    authTestEnv,
):
    reader = _makeReader(authTestEnv)

    calls = []

    class FakeSetMapper:
        def getStoredSet(self, projectId, protocolDbId, outputName, limit=None, offset=0):
            calls.append({
                "projectId": projectId,
                "protocolDbId": protocolDbId,
                "outputName": outputName,
                "limit": limit,
                "offset": offset,
            })

            if outputName == "outputTomograms":
                return {
                    "id": 20,
                    "objectId": 200,
                    "protocolDbId": protocolDbId,
                    "outputName": outputName,
                    "setClassName": "SetOfTomograms",
                    "itemClassName": "Tomogram",
                }

            return None

    reader.setMapper = FakeSetMapper()

    result = reader._getStoredSetFromInputRef({
        "parentProtocolDbId": 700,
        "parentOutputName": "outputTomograms.someNestedOutput",
    })

    assert result == {
        "id": 20,
        "objectId": 200,
        "protocolDbId": 700,
        "outputName": "outputTomograms",
        "setClassName": "SetOfTomograms",
        "itemClassName": "Tomogram",
    }

    assert calls == [
        {
            "projectId": 1,
            "protocolDbId": 700,
            "outputName": "outputTomograms.someNestedOutput",
            "limit": None,
            "offset": 0,
        },
        {
            "projectId": 1,
            "protocolDbId": 700,
            "outputName": "outputTomograms",
            "limit": None,
            "offset": 0,
        },
    ]


def test_PostgresqlIntegratedContextReaderReturnsNoneWhenInputRefHasNoParentProtocol(
    authTestEnv,
):
    reader = _makeReader(authTestEnv)

    class FakeSetMapper:
        def getStoredSet(self, **kwargs):
            raise AssertionError("getStoredSet should not be called without parentProtocolDbId")

    reader.setMapper = FakeSetMapper()

    result = reader._getStoredSetFromInputRef({
        "parentProtocolDbId": None,
        "parentOutputName": "outputTomograms",
    })

    assert result is None