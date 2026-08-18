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
import inspect
from datetime import date, datetime


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


def test_PostgresqlIntegratedContextReaderReturnsAllItemsWhenNoAllowedRelationKeys(
    authTestEnv,
):
    reader = _makeReader(authTestEnv)

    items = [
        {"id": "TS_001", "label": "TiltSeries TS_001"},
        {"id": "TS_002", "label": "TiltSeries TS_002"},
    ]

    assert reader._filterIntegratedItemsByAllowedKeys(items, None) == items
    assert reader._filterIntegratedItemsByAllowedKeys(items, set()) == items


def test_PostgresqlIntegratedContextReaderFiltersItemsByAllowedRelationKeys(
    authTestEnv,
):
    reader = _makeReader(authTestEnv)

    items = [
        {
            "id": "item-1",
            "tiltSeriesId": "TS_001",
            "label": "TiltSeries TS_001",
        },
        {
            "id": "item-2",
            "tiltSeriesId": "TS_002",
            "label": "TiltSeries TS_002",
        },
        {
            "id": "item-3",
            "tomoId": "TOMO_003",
            "label": "Tomogram TOMO_003",
        },
    ]

    result = reader._filterIntegratedItemsByAllowedKeys(
        items,
        {"TS_001", "TOMO_003"},
    )

    assert result == [
        {
            "id": "item-1",
            "tiltSeriesId": "TS_001",
            "label": "TiltSeries TS_001",
        },
        {
            "id": "item-3",
            "tomoId": "TOMO_003",
            "label": "Tomogram TOMO_003",
        },
    ]


def test_PostgresqlIntegratedContextReaderFiltersItemsByAllRelationAliasFields(
    authTestEnv,
):
    reader = _makeReader(authTestEnv)

    items = [
        {"key": "KEY_001"},
        {"name": "NAME_001"},
        {"id": "ID_001"},
        {"tomoId": "TOMO_001"},
        {"tomogramId": "TOMOGRAM_001"},
        {"tiltSeriesId": "TS_001"},
        {"ctfSeriesId": "CTF_001"},
        {"coordinatesTomogramId": "COORD_TOMO_001"},
        {"tsId": "TSID_001"},
        {"sourceTomoId": "SOURCE_TOMO_001"},
        {"label": "LABEL_001"},
        {"unknown": "NO_MATCH"},
    ]

    result = reader._filterIntegratedItemsByAllowedKeys(
        items,
        {
            "KEY_001",
            "NAME_001",
            "ID_001",
            "TOMO_001",
            "TOMOGRAM_001",
            "TS_001",
            "CTF_001",
            "COORD_TOMO_001",
            "TSID_001",
            "SOURCE_TOMO_001",
            "LABEL_001",
        },
    )

    assert result == items[:-1]


def test_PostgresqlIntegratedContextReaderDoesNotMatchEmptyRelationValues(
    authTestEnv,
):
    reader = _makeReader(authTestEnv)

    items = [
        {"id": ""},
        {"label": "   "},
        {"tiltSeriesId": None},
        {"tomoId": "TOMO_001"},
    ]

    result = reader._filterIntegratedItemsByAllowedKeys(
        items,
        {"", "TOMO_001"},
    )

    assert result == [
        {"tomoId": "TOMO_001"},
    ]


def test_PostgresqlIntegratedContextReaderSkipsDependencyCandidatesByRootKind(
    authTestEnv,
):
    reader = _makeReader(authTestEnv)

    assert reader._shouldSkipDependencyCandidate("coordinates3d", "tomogram") is True
    assert reader._shouldSkipDependencyCandidate("coordinates3d", "tiltSeries") is True
    assert reader._shouldSkipDependencyCandidate("coordinates3d", "ctf") is True

    assert reader._shouldSkipDependencyCandidate("tomogram", "tiltSeries") is True

    assert reader._shouldSkipDependencyCandidate("tomogram", "ctf") is False
    assert reader._shouldSkipDependencyCandidate("tomogram", "coordinates3d") is False
    assert reader._shouldSkipDependencyCandidate("ctf", "tiltSeries") is False
    assert reader._shouldSkipDependencyCandidate("tiltSeries", "ctf") is False
    assert reader._shouldSkipDependencyCandidate(None, "ctf") is False


def test_PostgresqlIntegratedContextReaderShouldReplaceEmptyOrDerivedLinks(
    authTestEnv,
):
    reader = _makeReader(authTestEnv)

    assert reader._shouldReplaceLink(None) is True

    assert reader._shouldReplaceLink({
        "protocolId": None,
        "outputName": None,
    }) is True

    assert reader._shouldReplaceLink({
        "protocolId": 500,
        "outputName": "outputCoordinates",
        "status": "derived",
        "source": "coordinates3d",
    }) is True

    assert reader._shouldReplaceLink({
        "protocolId": None,
        "outputName": "outputTomograms",
        "status": "inferred",
    }) is True


def test_PostgresqlIntegratedContextReaderKeepsConcreteLinks(authTestEnv):
    reader = _makeReader(authTestEnv)

    assert reader._shouldReplaceLink({
        "protocolId": 500,
        "outputName": "outputTomograms",
        "status": "available",
    }) is False

    assert reader._shouldReplaceLink({
        "protocolId": 501,
        "outputName": "outputCTF",
        "status": "related",
    }) is False

    assert reader._shouldReplaceLink({
        "protocolId": 502,
        "outputName": "outputTiltSeries",
        "status": "inferred",
    }) is False


def test_PostgresqlIntegratedContextReaderDetectsSameStoredSet(authTestEnv):
    reader = _makeReader(authTestEnv)

    assert reader._isSameStoredSet(
        {
            "protocolDbId": 500,
            "outputName": "outputTomograms",
        },
        {
            "protocolDbId": "500",
            "outputName": "outputTomograms",
        },
    ) is True

    assert reader._isSameStoredSet(
        {
            "protocolDbId": 500,
            "outputName": "outputTomograms",
        },
        {
            "protocolDbId": 501,
            "outputName": "outputTomograms",
        },
    ) is False

    assert reader._isSameStoredSet(
        {
            "protocolDbId": 500,
            "outputName": "outputTomograms",
        },
        {
            "protocolDbId": 500,
            "outputName": "outputCTF",
        },
    ) is False


def test_PostgresqlIntegratedContextReaderGetsCandidateProtocolId(authTestEnv):
    reader = _makeReader(authTestEnv)

    assert reader._getCandidateProtocolId({
        "protocolDbId": 700,
        "publicProtocolId": 120,
    }) == 700

    assert reader._getCandidateProtocolId({
        "protocolDbId": None,
        "publicProtocolId": 120,
    }) == 120


def test_PostgresqlIntegratedContextReaderBuildsTomogramItemsFromStoredSetValues(
    authTestEnv,
):
    reader = _makeReader(authTestEnv)
    storedSet = {
        "items": [
            {
                "scipionItemId": 101,
                "values": {
                    "_tsId": "TS_001",
                    "_tomoId": "TOMO_001",
                    "_objLabel": "Tomogram 001",
                },
            },
            {
                "scipionItemId": 102,
                "values": {
                    "tiltSeriesId": "TS_002",
                    "tomogramId": "TOMO_002",
                    "label": "Tomogram 002",
                },
            },
        ],
    }
    result = reader._buildTomogramItemsFromStoredSet(storedSet)

    assert result == [
        {
            "id": "TS_001",
            "tomoId": "TOMO_001",
            "tomogramId": "TOMO_001",
            "label": "TS_001",
            "volumeId": 0,
            "tomogramVolumeId": 0,
            "tsId": "TS_001",
            "tiltSeriesId": "TS_001",
            "ctfSeriesId": "TS_001",
            "sourceTomoId": "TOMO_001",
        },
        {
            "id": "TS_002",
            "tomoId": "TOMO_002",
            "tomogramId": "TOMO_002",
            "label": "Tomogram 002",
            "volumeId": 1,
            "tomogramVolumeId": 1,
            "tsId": "TS_002",
            "tiltSeriesId": "TS_002",
            "ctfSeriesId": "TS_002",
            "sourceTomoId": "TOMO_002",
        },
    ]


def test_PostgresqlIntegratedContextReaderBuildsTomogramItemsWithFallbackIds(
    authTestEnv,
):
    reader = _makeReader(authTestEnv)

    storedSet = {
        "items": [
            {
                "scipionItemId": 555,
                "values": {},
            },
            {
                "values": {
                    "name": "Named tomogram",
                },
            },
        ],
    }

    result = reader._buildTomogramItemsFromStoredSet(storedSet)

    assert result == [
        {
            "id": 555,
            "tomoId": 555,
            "tomogramId": 555,
            "label": 555,
            "volumeId": 0,
            "tomogramVolumeId": 0,
        },
        {
            "id": 1,
            "tomoId": 1,
            "tomogramId": 1,
            "label": "Named tomogram",
            "volumeId": 1,
            "tomogramVolumeId": 1,
        },
    ]


def test_PostgresqlIntegratedContextReaderBuildsTomogramItemsFromNormalizedNames(
    authTestEnv,
):
    reader = _makeReader(authTestEnv)

    storedSet = {
        "items": [
            {
                "values": {
                    "tilt_series_id": "TS_A",
                    "tomogram_id": "TOMO_A",
                    "name": "Tomogram A",
                },
            },
        ],
    }

    result = reader._buildTomogramItemsFromStoredSet(storedSet)

    assert result == [
        {
            "id": "TS_A",
            "tomoId": "TOMO_A",
            "tomogramId": "TOMO_A",
            "label": "Tomogram A",
            "volumeId": 0,
            "tomogramVolumeId": 0,
            "tsId": "TS_A",
            "tiltSeriesId": "TS_A",
            "ctfSeriesId": "TS_A",
            "sourceTomoId": "TOMO_A",
        },
    ]


class FakeScalarValue:
    def __init__(self, value):
        self.value = value

    def item(self):
        return self.value


def test_PostgresqlIntegratedContextReaderSafeValueSerializesDatesAndScalars(
    authTestEnv,
):
    reader = _makeReader(authTestEnv)

    value = {
        "createdAt": datetime(2026, 7, 1, 10, 30, 45),
        "runDate": date(2026, 7, 1),
        "count": FakeScalarValue(25),
        "nested": [
            {
                "score": FakeScalarValue(0.95),
            },
        ],
    }

    assert reader._safeValue(value) == {
        "createdAt": "2026-07-01T10:30:45",
        "runDate": "2026-07-01",
        "count": 25,
        "nested": [
            {
                "score": 0.95,
            },
        ],
    }


def test_PostgresqlIntegratedContextReaderSafeValueLeavesPlainValuesUntouched(
    authTestEnv,
):
    reader = _makeReader(authTestEnv)

    value = {
        "text": "TS_001",
        "number": 7,
        "float": 1.25,
        "flag": True,
        "none": None,
    }

    assert reader._safeValue(value) == value


def test_PostgresqlIntegratedContextReaderSafeValueHandlesTuplesAsLists(
    authTestEnv,
):
    reader = _makeReader(authTestEnv)

    assert reader._safeValue(("TS_001", FakeScalarValue(3))) == [
        "TS_001",
        3,
    ]


def test_PostgresqlIntegratedContextReaderBuildsRelationKeySetFromAliases(
    authTestEnv,
):
    reader = _makeReader(authTestEnv)

    relationsByKey = {
        "TS_001": {
            "key": "TS_001",
            "label": "TiltSeries TS_001",
            "tiltSeriesId": "TS_001",
            "tsId": "TS_ALIAS_001",
            "ctfSeriesId": "CTF_001",
            "tomogramId": "TOMO_001",
            "sourceTomoId": "SOURCE_TOMO_001",
            "coordinatesTomogramId": "COORD_TOMO_001",
        },
        "TS_002": {
            "key": "TS_002",
            "label": "",
            "tiltSeriesId": "TS_002",
            "tomogramId": None,
        },
    }

    result = reader._getRelationKeySet(relationsByKey)

    assert result == {
        "TS_001",
        "TiltSeries TS_001",
        "TS_ALIAS_001",
        "CTF_001",
        "TOMO_001",
        "SOURCE_TOMO_001",
        "COORD_TOMO_001",
        "TS_002",
    }


def test_PostgresqlIntegratedContextReaderRelationKeySetReturnsNoneWhenEmpty(
    authTestEnv,
):
    reader = _makeReader(authTestEnv)

    assert reader._getRelationKeySet({}) is None
    assert reader._getRelationKeySet(None) is None


def test_PostgresqlIntegratedContextReaderIterRelationMatchValuesDeduplicatesAliases(
    authTestEnv,
):
    reader = _makeReader(authTestEnv)

    result = reader._iterRelationMatchValues(
        "TS_001",
        {
            "key": "TS_001",
            "tiltSeriesId": "TS_001",
            "tsId": "TS_ALIAS_001",
            "ctfSeriesId": "CTF_001",
            "tomogramId": "TOMO_001",
            "sourceTomoId": "TOMO_001",
            "coordinatesTomogramId": "COORD_TOMO_001",
        },
    )

    assert result == [
        "TS_001",
        "TS_ALIAS_001",
        "CTF_001",
        "TOMO_001",
        "COORD_TOMO_001",
    ]


def test_PostgresqlIntegratedContextReaderFindsExistingRelationKeysByAliases(
    authTestEnv,
):
    reader = _makeReader(authTestEnv)

    relationsByKey = {
        "TS_001": {
            "key": "TS_001",
            "tiltSeriesId": "TS_001",
            "ctfSeriesId": "TS_001",
        },
        "TOMO_002": {
            "key": "TOMO_002",
            "tomogramId": "TOMO_002",
            "sourceTomoId": "SOURCE_TOMO_002",
        },
        "UNRELATED": {
            "key": "UNRELATED",
        },
    }

    assert reader._findExistingRelationKeys(
        relationsByKey,
        ["TS_001"],
    ) == ["TS_001"]

    assert reader._findExistingRelationKeys(
        relationsByKey,
        ["SOURCE_TOMO_002"],
    ) == ["TOMO_002"]

    assert reader._findExistingRelationKeys(
        relationsByKey,
        ["NO_MATCH"],
    ) == []


def test_PostgresqlIntegratedContextReaderMergeRelationsForCandidateIgnoresIncompleteCandidate(
    authTestEnv,
):
    reader = _makeReader(authTestEnv)

    class FakeSetMapper:
        def getStoredSet(self, **kwargs):
            raise AssertionError("getStoredSet should not be called for incomplete candidates")

    reader.setMapper = FakeSetMapper()

    relationsByKey = {}

    reader._mergeRelationsForCandidate(
        candidate={
            "protocolDbId": None,
            "outputName": "outputTiltSeries",
        },
        candidateKind="tiltSeries",
        relationsByKey=relationsByKey,
    )

    reader._mergeRelationsForCandidate(
        candidate={
            "protocolDbId": 700,
            "outputName": "",
        },
        candidateKind="tiltSeries",
        relationsByKey=relationsByKey,
    )

    assert relationsByKey == {}


def test_PostgresqlIntegratedContextReaderMergeRelationsForTiltSeriesCandidateUsesAllowedKeys(
    authTestEnv,
    monkeypatch,
):
    module = importlib.import_module(
        "app.backend.viewers.postgresql_integrated_context_reader"
    )
    reader = _makeReader(authTestEnv)

    class FakeTiltSeriesReader:
        def __init__(self, db, projectId, protocolId, outputName):
            assert projectId == 1
            assert protocolId == 700
            assert outputName == "outputTiltSeries"

        def listTiltSeries(self):
            return [
                {
                    "tiltSeriesId": "TS_001",
                    "label": "TiltSeries TS_001",
                },
                {
                    "tiltSeriesId": "TS_002",
                    "label": "TiltSeries TS_002",
                },
            ]

    monkeypatch.setattr(module, "PostgresqlTiltSeriesReader", FakeTiltSeriesReader)

    relationsByKey = {}

    reader._mergeRelationsForCandidate(
        candidate={
            "protocolDbId": 700,
            "outputName": "outputTiltSeries",
        },
        candidateKind="tiltSeries",
        relationsByKey=relationsByKey,
        allowedRelationKeys={"TS_002"},
    )

    assert relationsByKey == {
        "TS_002": {
            "key": "TS_002",
            "label": "TiltSeries TS_002",
            "tiltSeriesId": "TS_002",
            "tsId": "TS_002",
        },
    }


def test_PostgresqlIntegratedContextReaderMergeRelationsForCtftomoCandidateUsesAllowedKeys(
    authTestEnv,
    monkeypatch,
):
    module = importlib.import_module(
        "app.backend.viewers.postgresql_integrated_context_reader"
    )
    reader = _makeReader(authTestEnv)

    class FakeCtftomoReader:
        def __init__(self, db, projectId, protocolId, outputName):
            assert projectId == 1
            assert protocolId == 701
            assert outputName == "outputCTF"

        def listCtftomoSeries(self):
            return [
                {
                    "tiltSeriesId": "TS_001",
                    "label": "CTF TS_001",
                },
                {
                    "tiltSeriesId": "TS_002",
                    "label": "CTF TS_002",
                },
            ]

    monkeypatch.setattr(module, "PostgresqlCtftomoReader", FakeCtftomoReader)

    relationsByKey = {}

    reader._mergeRelationsForCandidate(
        candidate={
            "protocolDbId": 701,
            "outputName": "outputCTF",
        },
        candidateKind="ctf",
        relationsByKey=relationsByKey,
        allowedRelationKeys={"TS_001"},
    )

    assert relationsByKey == {
        "TS_001": {
            "key": "TS_001",
            "label": "CTF TS_001",
            "ctfSeriesId": "TS_001",
            "tiltSeriesId": "TS_001",
            "tsId": "TS_001",
        },
    }


def test_PostgresqlIntegratedContextReaderMergeRelationsForCoordinates3dCandidateUsesAllowedKeys(
    authTestEnv,
    monkeypatch,
):
    module = importlib.import_module(
        "app.backend.viewers.postgresql_integrated_context_reader"
    )
    reader = _makeReader(authTestEnv)

    class FakeCoords3dReader:
        def __init__(self, db, projectId, protocolId, outputName):
            assert projectId == 1
            assert protocolId == 702
            assert outputName == "outputCoordinates"

        def listTomograms(self):
            return [
                {
                    "tomoId": "TOMO_001",
                    "label": "Tomogram TOMO_001",
                },
                {
                    "tomoId": "TOMO_002",
                    "label": "Tomogram TOMO_002",
                },
            ]

    monkeypatch.setattr(module, "PostgresqlCoords3dReader", FakeCoords3dReader)

    relationsByKey = {}

    reader._mergeRelationsForCandidate(
        candidate={
            "protocolDbId": 702,
            "outputName": "outputCoordinates",
        },
        candidateKind="coordinates3d",
        relationsByKey=relationsByKey,
        allowedRelationKeys={"TOMO_002"},
    )

    assert relationsByKey == {
        "TOMO_002": {
            "key": "TOMO_002",
            "label": "Tomogram TOMO_002",
            "coordinatesTomogramId": "TOMO_002",
            "tomogramId": "TOMO_002",
        },
    }


def test_PostgresqlIntegratedContextReaderMergeRelationsForTomogramCandidateUsesAllowedKeys(
    authTestEnv,
):
    reader = _makeReader(authTestEnv)

    class FakeSetMapper:
        def getStoredSet(self, projectId, protocolDbId, outputName, limit=None, offset=0):
            assert projectId == 1
            assert protocolDbId == 703
            assert outputName == "outputTomograms"
            assert limit is None
            assert offset == 0

            return {
                "items": [
                    {
                        "values": {
                            "_tsId": "TS_001",
                            "_tomoId": "TOMO_001",
                            "_objLabel": "Tomogram 001",
                        },
                    },
                    {
                        "values": {
                            "_tsId": "TS_002",
                            "_tomoId": "TOMO_002",
                            "_objLabel": "Tomogram 002",
                        },
                    },
                ],
            }

    reader.setMapper = FakeSetMapper()

    relationsByKey = {}

    reader._mergeRelationsForCandidate(
        candidate={
            "protocolDbId": 703,
            "outputName": "outputTomograms",
        },
        candidateKind="tomogram",
        relationsByKey=relationsByKey,
        allowedRelationKeys={"TS_001"},
    )

    assert list(relationsByKey.keys()) == ["TS_001"]

    relation = relationsByKey["TS_001"]

    assert relation["key"] == "TS_001"
    assert relation["tomogramId"] == "TOMO_001"
    assert relation["sourceTomoId"] == "TOMO_001"
    assert relation["tomogramVolumeId"] == 0
    assert relation["tiltSeriesId"] == "TS_001"
    assert relation["tsId"] == "TS_001"
    assert relation["ctfSeriesId"] == "TS_001"


def test_PostgresqlIntegratedContextReaderDelegatesInputRefReads(authTestEnv, monkeypatch):
    module = importlib.import_module(
        "app.backend.viewers.postgresql_integrated_context_reader"
    )

    repositoryCalls = []

    class ForbiddenDb:
        def fetchAll(self, *args, **kwargs):
            raise AssertionError(
                "PostgresqlIntegratedContextReader must not query input refs directly"
            )

    class ProtocolGraphRepositoryStub:
        def loadInputRefsForProtocol(self, mapper, projectId, protocolDbId):
            repositoryCalls.append({
                "mapper": mapper,
                "projectId": projectId,
                "protocolDbId": protocolDbId,
            })

            return [
                {
                    "inputName": "inputTiltSeries",
                    "itemIndex": 0,
                    "parentProtocolDbId": 400,
                    "parentProtocolId": "10",
                    "parentOutputName": "outputTiltSeries",
                    "objectClassName": "SetOfTiltSeries",
                    "objectId": "25",
                },
            ]

    monkeypatch.setattr(
        module,
        "ProtocolGraphRepository",
        ProtocolGraphRepositoryStub,
    )

    database = ForbiddenDb()

    reader = module.PostgresqlIntegratedContextReader(
        db=database,
        projectId=7,
        protocolId=500,
        outputName="outputTomograms",
    )

    result = reader._listProtocolInputRefs(500)

    assert result == [
        {
            "inputName": "inputTiltSeries",
            "itemIndex": 0,
            "parentProtocolDbId": 400,
            "parentProtocolId": "10",
            "parentOutputName": "outputTiltSeries",
            "objectClassName": "SetOfTiltSeries",
            "objectId": "25",
        },
    ]

    assert repositoryCalls == [
        {
            "mapper": reader.setMapper,
            "projectId": 7,
            "protocolDbId": 500,
        },
    ]

    source = inspect.getsource(
        module.PostgresqlIntegratedContextReader._listProtocolInputRefs
    )

    assert "loadInputRefsForProtocol(" in source
    assert ".fetchOne(" not in source
    assert ".fetchAll(" not in source
    assert ".execute(" not in source


def test_PostgresqlIntegratedContextReaderBuildLinkResolvesMissingPublicProtocolId(
    authTestEnv,
    monkeypatch,
):
    module = importlib.import_module(
        "app.backend.viewers.postgresql_integrated_context_reader"
    )
    reader = _makeReader(authTestEnv)

    resolverCalls = []

    class ProtocolIdentityResolverStub:
        def __init__(self, db, projectId):
            assert db is reader.db
            assert projectId == 1

        def getProtocolRowByDbId(self, protocolDbId):
            resolverCalls.append(protocolDbId)
            return {
                "id": 700,
                "protocolId": 120,
            }

    monkeypatch.setattr(
        module,
        "ProtocolIdentityResolver",
        ProtocolIdentityResolverStub,
    )

    link = reader._buildLink(
        protocolId=700,
        outputName="TiltSeries",
        storedSet={
            "id": 20,
            "objectId": 200,
            "protocolDbId": 700,
            "outputName": "TiltSeries",
            "setClassName": "SetOfTiltSeries",
            "itemClassName": "TiltSeries",
        },
        statusValue="inferred",
    )

    assert link == {
        "protocolId": 700,
        "publicProtocolId": 120,
        "outputName": "TiltSeries",
        "itemId": 200,
        "label": "TiltSeries",
        "status": "inferred",
    }
    assert resolverCalls == [700]


