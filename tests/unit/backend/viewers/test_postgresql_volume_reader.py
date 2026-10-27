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


def test_PostgresqlVolumeReaderExtractsDimsFromCommaSeparatedString(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_volume_reader")

    reader = module.PostgresqlVolumeReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputVolumes",
    )

    assert reader._extractDims({"_dim": "128,128,64"}) == [128, 128, 64]
    assert reader._extractDims({"dimensions": "128 128 64"}) == [128, 128, 64]
    assert reader._extractDims({"volumeDims": "128x128x64"}) == [128, 128, 64]


def test_PostgresqlVolumeReaderExtractsDimsFromJsonString(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_volume_reader")

    reader = module.PostgresqlVolumeReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputVolumes",
    )

    assert reader._extractDims({"dims": "[32, 48, 64]"}) == [32, 48, 64]
    assert reader._extractDims({"dims": '{"x": 32, "y": 48, "z": 64}'}) == [32, 48, 64]


def test_PostgresqlVolumeReaderExtractsSamplingRateFromFlatStrings(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_volume_reader")

    reader = module.PostgresqlVolumeReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputVolumes",
    )

    assert reader._extractSamplingRate({"samplingRate": "1.25"}) == 1.25
    assert reader._extractSamplingRate({"voxelSize": "1.5,1.5,1.5"}) == 1.5
    assert reader._extractSamplingRate({"pixelSize": "2.0 2.0 2.0"}) == 2.0


def test_PostgresqlVolumeReaderRejectsInvalidDims(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_volume_reader")

    reader = module.PostgresqlVolumeReader(
        db=object(),
        projectId=1,
        protocolId=500,
        outputName="outputVolumes",
    )

    assert reader._extractDims({"dims": "128,foo,64"}) is None
    assert reader._extractDims({"dims": "128,64"}) is None
    assert reader._extractDims({"dims": "128,0,64"}) is None


def test_PostgresqlVolumeReaderResolvesProjectRelativeVolumePath(
    authTestEnv,
    tmp_path,
):
    module = importlib.import_module("app.backend.viewers.postgresql_volume_reader")

    projectPath = tmp_path / "project"
    volumePath = projectPath / "Runs" / "000134_ProtVolume" / "extra" / "volume.mrc"
    volumePath.parent.mkdir(parents=True)
    volumePath.write_bytes(b"fake")

    class FakeDb:
        def fetchOne(self, query, params):
            if "FROM projects" in query:
                return {"name": str(projectPath)}
            return None

    reader = module.PostgresqlVolumeReader(
        db=FakeDb(),
        projectId=249,
        protocolId=134,
        outputName="outputVolume",
    )

    assert reader._resolveExistingPath(
        "Runs/000134_ProtVolume/extra/volume.mrc"
    ) == str(volumePath.resolve())


def test_PostgresqlVolumeReaderDelegatesProtocolDbIdResolution(authTestEnv, monkeypatch):
    module = importlib.import_module("app.backend.viewers.postgresql_volume_reader")
    resolverCalls = []

    class ForbiddenDb:
        def fetchOne(self, *args, **kwargs):
            raise AssertionError("PostgresqlVolumeReader must not query protocol identity directly")

    class ProtocolIdentityResolverStub:
        def __init__(self, mapper=None, projectId=None, db=None):
            resolverCalls.append({
                "method": "__init__",
                "projectId": projectId,
                "db": db,
            })

        def getProtocolRowByDbId(self, protocolId):
            resolverCalls.append({
                "method": "getProtocolRowByDbId",
                "protocolId": protocolId,
            })

            return {
                "id": 500,
                "protocolId": "10",
            }

        def getProtocolRowByScipionProtocolId(self, protocolId):
            raise AssertionError("Database id lookup must have precedence")

    monkeypatch.setattr(module, "ProtocolIdentityResolver", ProtocolIdentityResolverStub)

    database = ForbiddenDb()

    reader = module.PostgresqlVolumeReader(
        db=database,
        projectId=7,
        protocolId=500,
        outputName="outputVolume",
    )

    assert reader._resolveProtocolDbId() == 500
    assert reader._resolveProtocolDbId() == 500

    assert resolverCalls == [
        {
            "method": "__init__",
            "projectId": 7,
            "db": database,
        },
        {
            "method": "getProtocolRowByDbId",
            "protocolId": 500,
        },
    ]

    source = inspect.getsource(module.PostgresqlVolumeReader._resolveProtocolDbId)

    assert "ProtocolIdentityResolver(" in source
    assert ".fetchOne(" not in source
    assert ".fetchAll(" not in source


def test_PostgresqlVolumeReaderFallsBackToScipionProtocolId(authTestEnv, monkeypatch):
    module = importlib.import_module("app.backend.viewers.postgresql_volume_reader")
    resolverCalls = []

    class ProtocolIdentityResolverStub:
        def __init__(self, mapper=None, projectId=None, db=None):
            pass

        def getProtocolRowByDbId(self, protocolId):
            resolverCalls.append({
                "method": "getProtocolRowByDbId",
                "protocolId": protocolId,
            })

            return None

        def getProtocolRowByScipionProtocolId(self, protocolId):
            resolverCalls.append({
                "method": "getProtocolRowByScipionProtocolId",
                "protocolId": protocolId,
            })

            return {
                "id": 500,
                "protocolId": "10",
            }

    monkeypatch.setattr(module, "ProtocolIdentityResolver", ProtocolIdentityResolverStub)

    reader = module.PostgresqlVolumeReader(
        db=object(),
        projectId=7,
        protocolId=10,
        outputName="outputVolume",
    )

    assert reader._resolveProtocolDbId() == 500

    assert resolverCalls == [
        {
            "method": "getProtocolRowByDbId",
            "protocolId": 10,
        },
        {
            "method": "getProtocolRowByScipionProtocolId",
            "protocolId": 10,
        },
    ]


def test_PostgresqlVolumeReaderDelegatesStoredOutputReads(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_volume_reader")
    mapperCalls = []

    storedSet = {
        "id": 11,
        "projectId": 7,
        "protocolDbId": 500,
        "outputName": "outputVolumes",
        "setClassName": "SetOfVolumes",
        "itemClassName": "Volume",
        "properties": {},
        "items": [
            {
                "scipionItemId": 1,
                "values": {
                    "fileName": "volume.mrc",
                },
            },
        ],
    }

    objectTree = [
        {
            "id": 21,
            "projectId": 7,
            "protocolDbId": 500,
            "scipionObjId": 30,
            "parentObjectId": None,
            "name": "outputVolumes",
            "path": "outputVolumes",
            "className": "Volume",
        },
    ]

    class ForbiddenDb:
        def fetchOne(self, *args, **kwargs):
            raise AssertionError("PostgresqlVolumeReader must not query stored outputs directly")

        def fetchAll(self, *args, **kwargs):
            raise AssertionError("PostgresqlVolumeReader must not query stored outputs directly")

    class SetMapperStub:
        def getStoredSet(self, projectId, protocolDbId, outputName):
            mapperCalls.append({
                "method": "getStoredSet",
                "projectId": projectId,
                "protocolDbId": protocolDbId,
                "outputName": outputName,
            })

            return storedSet

        def getStoredObjectTree(self, projectId, protocolDbId, outputName):
            mapperCalls.append({
                "method": "getStoredObjectTree",
                "projectId": projectId,
                "protocolDbId": protocolDbId,
                "outputName": outputName,
            })

            return objectTree

    reader = module.PostgresqlVolumeReader(
        db=ForbiddenDb(),
        projectId=7,
        protocolId=500,
        outputName="outputVolumes",
    )

    reader.setMapper = SetMapperStub()
    reader._protocolDbId = 500

    assert reader._getStoredSet() == storedSet
    assert reader._getStoredSet() == storedSet

    assert reader._getStoredObjectTree() == objectTree
    assert reader._getStoredObjectTree() == objectTree

    assert mapperCalls == [
        {
            "method": "getStoredSet",
            "projectId": 7,
            "protocolDbId": 500,
            "outputName": "outputVolumes",
        },
        {
            "method": "getStoredObjectTree",
            "projectId": 7,
            "protocolDbId": 500,
            "outputName": "outputVolumes",
        },
    ]

    storedSetSource = inspect.getsource(module.PostgresqlVolumeReader._getStoredSet)
    objectTreeSource = inspect.getsource(module.PostgresqlVolumeReader._getStoredObjectTree)

    assert "setMapper.getStoredSet(" in storedSetSource
    assert ".fetchOne(" not in storedSetSource
    assert ".fetchAll(" not in storedSetSource
    assert ".execute(" not in storedSetSource

    assert "setMapper.getStoredObjectTree(" in objectTreeSource
    assert ".fetchOne(" not in objectTreeSource
    assert ".fetchAll(" not in objectTreeSource
    assert ".execute(" not in objectTreeSource

def _averageWithHalvesReader(module, halfMapFilenames):
    reader = module.PostgresqlVolumeReader(
        db=object(),
        projectId=14,
        protocolId=14,
        outputName="average",
    )
    rows = [
        {"path": "average", "className": "AverageSubTomogram", "scipionObjId": 3, "label": None, "name": "average"},
        {"path": "average._filename", "value": "Runs/000014_Refine/extra/_class001.mrc"},
        {"path": "average._samplingRate", "value": "1.5788"},
    ]
    if halfMapFilenames is not None:
        rows.append({"path": "average._halfMapFilenames", "value": halfMapFilenames})
    reader._getStoredSet = lambda: None
    reader._getStoredObjectTree = lambda: rows
    reader._resolveExistingPath = lambda fileName: "/project/" + str(fileName)
    return reader


def test_PostgresqlVolumeReaderListsTheHalfMapsOfAVolumeAfterItsMap(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_volume_reader")
    reader = _averageWithHalvesReader(
        module,
        "Runs/000014_Refine/extra/_it012_half1_class001.mrc,Runs/000014_Refine/extra/_it012_half2_class001.mrc",
    )

    volumes = reader.listVolumes()

    assert [volume["id"] for volume in volumes] == [0, "half1", "half2"]
    assert [volume["label"] for volume in volumes][1:] == ["Half map 1", "Half map 2"]
    assert volumes[2]["samplingRate"] == volumes[0]["samplingRate"] == 1.5788
    assert reader.getVolumeFile("half2")["fileName"] == (
        "/project/Runs/000014_Refine/extra/_it012_half2_class001.mrc"
    )
    assert reader.getVolumeFile(0)["fileName"] == "/project/Runs/000014_Refine/extra/_class001.mrc"


def test_PostgresqlVolumeReaderListsOnlyTheMapOfAVolumeWithoutHalfMaps(authTestEnv):
    module = importlib.import_module("app.backend.viewers.postgresql_volume_reader")

    for halfMapFilenames in (None, "", "Runs/only_one_half.mrc"):
        volumes = _averageWithHalvesReader(module, halfMapFilenames).listVolumes()
        assert [volume["id"] for volume in volumes] == [0]
