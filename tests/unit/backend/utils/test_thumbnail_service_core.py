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
import json
from pathlib import Path

import pytest


class FakeOutput:
    # fakeOutput
    def __init__(self, className="SetOfParticles", size=5):
        self._className = className
        self._size = size

    def getClassName(self):
        return self._className

    def getSize(self):
        return self._size


class FakeProtocol:
    # fakeProtocol
    def __init__(self, objId, label="Protocol", status="finished", outputs=None):
        self._objId = objId
        self._label = label
        self._status = status
        self._outputs = outputs or []

    def getObjId(self):
        return self._objId

    def getObjLabel(self):
        return self._label

    def getStatus(self):
        return self._status

    def iterOutputAttributes(self):
        for item in self._outputs:
            yield item


class FakeNode:
    # fakeNode
    def __init__(self, run=None):
        self.run = run


class FakeGraph:
    # fakeGraph
    def __init__(self, nodesDict):
        self._nodesDict = nodesDict


class FakeCurrentProject:
    # fakeCurrentProject
    def __init__(
            self,
            projectPath,
            protocols=None,
            graph=None,
            mapper=None,
    ):
        self._projectPath = projectPath
        self._protocols = protocols or {}
        self._graph = graph
        self.mapper = mapper

    def getPath(self):
        return self._projectPath

    def getProtocol(self, protocolId):
        return self._protocols.get(int(protocolId))

    def getRunsGraph(self, refresh=False, checkPids=False):
        return self._graph

class FakePersistedOutput(FakeOutput):
    def __init__(
            self,
            className,
            size,
            parentId,
            objectName,
    ):
        super().__init__(
            className=className,
            size=size,
        )

        self._parentId = parentId
        self._objectName = objectName

    def getObjParentId(self):
        return self._parentId

    def getObjName(self):
        return self._objectName


class FakePostgresqlRuntimeMapper:
    isPostgresqlRuntimeMapper = True

    def __init__(
            self,
            sets=None,
            objects=None,
    ):
        self.sets = list(
            sets or []
        )

        self.objects = list(
            objects or []
        )

    def selectByClass(
            self,
            objectClass,
            includeSubclasses=True,
            iterate=False,
            objectFilter=None,
    ):
        className = getattr(
            objectClass,
            "__name__",
            "",
        )

        if className == "Set":
            result = list(
                self.sets
            )

        elif className == "Object":
            result = list(
                self.objects
            )

        else:
            result = []

        if callable(objectFilter):
            result = [
                item
                for item in result
                if objectFilter(item)
            ]

        return (
            iter(result)
            if iterate
            else result
        )


@pytest.fixture
def thumbnailServiceModule(authTestEnv):
    # thumbnailServiceModule
    return importlib.import_module("app.backend.utils.thumbnail_service")


@pytest.fixture
def service(thumbnailServiceModule, tmp_path):
    # service
    projectPath = tmp_path / "DemoProject"
    projectPath.mkdir(parents=True, exist_ok=True)

    currentProject = FakeCurrentProject(projectPath=str(projectPath))
    return thumbnailServiceModule.ThumbnailService(currentProject)


def test_CacheSafeTokenSanitizesAndAddsDigest(service):
    token = service._cacheSafeToken("output particles / avg")

    assert token.startswith("output_particles_avg_")
    assert len(token.split("_")[-1]) == 10


def test_SlugOutputNameReturnsBestForEmpty(service):
    assert service._slugOutputName(None) == "best"
    assert service._slugOutputName("") == "best"


def test_SlugOutputNameSanitizesValue(service):
    assert service._slugOutputName("output particles / avg") == "output_particles_avg"


def test_GetProtocolCachePathUsesExpectedPattern(service):
    path = service._getProtocolCachePath(protocolId=10, size=320, outputName="outputAvg")

    assert path.name == "protocol_10_outputAvg_320_v2.png"
    assert path.parent.name == ".thumbnail_cache"


def test_GetProjectCachePathUsesExpectedPattern(service):
    path = service._getProjectCachePath(size=720, maxProtocols=6)

    assert path.name == "project_720_6_v2.png"
    assert path.parent.name == ".thumbnail_cache"


def test_UniqueIntsDeduplicatesAndSkipsNegatives(service):
    assert service._uniqueInts([3, "3", -1, 5, 5, "bad", 0]) == [3, 5, 0]


def test_IsLikelyPreviewFileRecognizesRelevantNames(service):
    assert service._isLikelyPreviewFile("thumb_protocol.png") is True
    assert service._isLikelyPreviewFile("class_average.mrc") is True
    assert service._isLikelyPreviewFile("notes.txt") is False


def test_ProjectProtocolSizeScalesByMaxProtocols(service):
    assert service._projectProtocolSize(size=900, maxProtocols=1) >= 400
    assert service._projectProtocolSize(size=900, maxProtocols=2) >= 340
    assert service._projectProtocolSize(size=900, maxProtocols=6) >= 300


def test_ScoreProtocolStatusMapsKnownStates(service):
    protocolFinished = FakeProtocol(1, status="finished")
    protocolRunning = FakeProtocol(2, status="running")
    protocolFailed = FakeProtocol(3, status="failed")
    protocolUnknown = FakeProtocol(4, status="whatever")

    assert service._scoreProtocolStatus(protocolFinished) == 120
    assert service._scoreProtocolStatus(protocolRunning) == 70
    assert service._scoreProtocolStatus(protocolFailed) == -200
    assert service._scoreProtocolStatus(protocolUnknown) == 10


def test_ScoreOutputRewardsUsefulOutputs(service):
    particles = FakeOutput(className="SetOfParticles", size=5)
    mask = FakeOutput(className="VolumeMask", size=2)
    ctf = FakeOutput(className="SetOfCTF", size=4)
    movie = FakeOutput(className="SetOfMovies", size=3)
    flex = FakeOutput(className="SetOfParticlesFlex", size=6)
    sequence = FakeOutput(className="SetOfSequences", size=2)
    normalModes = FakeOutput(className="SetOfNormalModes", size=8)
    atomStruct = FakeOutput(className="SetOfAtomStructs", size=1)
    generic = FakeOutput(className="SomethingRenderable", size=1)

    assert service._scoreOutput("outputParticles", particles) > 0
    assert service._scoreOutput("outputMask", mask) > 0
    assert service._scoreOutput("outputCtf", ctf) > 0
    assert service._scoreOutput("outputMovies", movie) > 0
    assert service._scoreOutput("outputFlex", flex) > 0
    assert service._scoreOutput("outputSequences", sequence) > 0
    assert service._scoreOutput("outputModes", normalModes) > 0
    assert service._scoreOutput("outputAtomStructs", atomStruct) > 0
    assert service._scoreOutput("tmpDebug", generic) == 0


def test_IterProtocolsSkipsProjectAndSortsByStatus(thumbnailServiceModule, tmp_path):
    projectPath = tmp_path / "DemoProject"
    projectPath.mkdir(parents=True, exist_ok=True)

    protocol1 = FakeProtocol(1, label="One", status="running")
    protocol2 = FakeProtocol(2, label="Two", status="finished")

    graph = FakeGraph(
        {
            "PROJECT": FakeNode(run=None),
            "1": FakeNode(run=protocol1),
            "2": FakeNode(run=protocol2),
        }
    )
    currentProject = FakeCurrentProject(
        projectPath=str(projectPath),
        protocols={1: protocol1, 2: protocol2},
        graph=graph,
    )
    service = thumbnailServiceModule.ThumbnailService(currentProject)

    protocols = service._iterProtocols()

    assert [p.getObjId() for p in protocols] == [2, 1]


def test_ListUsefulProtocolsFiltersAndSortsCandidates(service, monkeypatch):
    protocol1 = FakeProtocol(1, label="Prot 1", status="finished")
    protocol2 = FakeProtocol(2, label="Prot 2", status="running")
    protocol3 = FakeProtocol(3, label="Prot 3", status="failed")

    monkeypatch.setattr(service, "_iterProtocols", lambda: [protocol1, protocol2, protocol3])
    monkeypatch.setattr(
        service,
        "_selectBestOutput",
        lambda protocol: {
            "outputName": "outputA",
            "output": FakeOutput(className="SetOfParticles", size=5),
            "outputClassName": "SetOfParticles",
            "score": {1: 120, 2: 110, 3: 40}[protocol.getObjId()],
        },
    )
    monkeypatch.setattr(
        service,
        "_safeOutputSize",
        lambda output: output.getSize(),
    )
    monkeypatch.setattr(
        service,
        "_scoreProtocolStatus",
        lambda protocol: {1: 120, 2: 70, 3: -200}[protocol.getObjId()],
    )

    result = service.listUsefulProtocols(maxProtocols=5)

    assert [item["protocolId"] for item in result] == [1, 2]
    assert result[0]["protocolLabel"] == "Prot 1"
    assert result[0]["outputName"] == "outputA"
    assert result[0]["itemsCount"] == 5
    assert result[0]["score"] > result[1]["score"]


def test_BuildProtocolThumbnailReturnsCachedEntry(service, monkeypatch, tmp_path):
    protocol = FakeProtocol(10, label="Prot 10", status="finished")
    service.currentProject._protocols = {10: protocol}

    cachePath = tmp_path / "protocol_10_best_320_v1.png"
    cachePath.write_text("cached", encoding="utf-8")

    monkeypatch.setattr(service, "_getProtocolCachePath", lambda protocolId, size, outputName=None: cachePath)
    monkeypatch.setattr(service, "_isValidCachedImage", lambda path: True)

    result = service.buildProtocolThumbnail(protocolId=10, force=False, size=320)

    assert result == {
        "protocolId": 10,
        "protocolLabel": "Prot 10",
        "status": "finished",
        "outputName": None,
        "outputClassName": None,
        "absolutePath": str(cachePath),
        "cached": True,
        "exists": True,
    }


def test_BuildProtocolOutputThumbnailChecksCacheBeforeResolvingOutput(service, monkeypatch, tmp_path):
    protocol = FakeProtocol(10, label="Prot 10", status="finished")
    service.currentProject._protocols = {10: protocol}

    cachePath = tmp_path / "protocol_10_outputVol_128_v1.png"
    cachePath.write_bytes(b"cached")

    monkeypatch.setattr(service, "_getProtocolOutputCachePath", lambda protocolId, outputName, size: cachePath)
    monkeypatch.setattr(service, "_isValidCachedImage", lambda path: True)

    def failFindProtocolOutput(**kwargs):
        raise AssertionError("Cached thumbnails must not resolve PostgreSQL outputs")

    monkeypatch.setattr(service, "_findProtocolOutput", failFindProtocolOutput)

    result = service.buildProtocolOutputThumbnail(protocolId=10, outputName="outputVol", force=False, size=128)

    assert result == {
        "protocolId": 10,
        "protocolLabel": "Prot 10",
        "status": "finished",
        "outputName": "outputVol",
        "outputClassName": None,
        "absolutePath": str(cachePath),
        "cached": True,
        "exists": True,
    }


def test_BuildProtocolThumbnailReturnsMissingWhenRequestedOutputDoesNotExist(service, monkeypatch):
    protocol = FakeProtocol(10, label="Prot 10", status="finished")
    service.currentProject._protocols = {10: protocol}

    monkeypatch.setattr(service, "_collectSortedOutputCandidates", lambda protocolObj: [])

    result = service.buildProtocolThumbnail(
        protocolId=10,
        force=False,
        size=320,
        outputName="missingOutput",
    )

    assert result == {
        "protocolId": 10,
        "protocolLabel": "Prot 10",
        "status": "finished",
        "outputName": "missingOutput",
        "outputClassName": None,
        "absolutePath": None,
        "cached": False,
        "exists": False,
    }


def test_BuildProjectThumbnailReturnsCachedStrip(service, monkeypatch, tmp_path):
    cachePath = tmp_path / "project_720_6_v1.png"
    cachePath.write_text("cached", encoding="utf-8")

    monkeypatch.setattr(service, "_getProjectCachePath", lambda size, maxProtocols: cachePath)
    monkeypatch.setattr(service, "_isValidCachedImage", lambda path: True)

    result = service.buildProjectThumbnail(force=False, size=720, maxProtocols=6)

    assert result == {
        "absolutePath": str(cachePath),
        "cached": True,
        "items": None,
    }


def test_ListProtocolThumbnailItemsBuildsGroups(service, monkeypatch):
    protocol = FakeProtocol(11, label="Prot 11", status="running")

    monkeypatch.setattr(service, "_iterProtocols", lambda: [protocol])
    monkeypatch.setattr(
        service,
        "_collectSortedOutputCandidates",
        lambda protocolObj: [
            {
                "outputName": "outputVol",
                "outputClassName": "SetOfVolumes",
                "score": 100,
                "itemsCount": 3,
            },
            {
                "outputName": "outputParticles",
                "outputClassName": "SetOfParticles",
                "score": 95,
                "itemsCount": 6,
            },
        ],
    )
    monkeypatch.setattr(
        service,
        "buildProtocolOutputThumbnail",
        lambda protocolId, outputName, force, size: {
            "exists": True,
            "absolutePath": f"/tmp/{protocolId}_{outputName}.png",
        },
    )

    result = service.listProtocolThumbnailItems(
        projectId=7,
        force=True,
        size=300,
        maxProtocols=5,
        maxOutputsPerProtocol=2,
    )

    assert result == [
        {
            "protocolId": 11,
            "label": "Prot 11",
            "status": "running",
            "outputs": [
                {
                    "outputName": "outputVol",
                    "outputClassName": "SetOfVolumes",
                    "exists": True,
                    "thumbnailUrl": "/projects/7/protocols/11/outputs/outputVol/thumbnail",
                    "thumbnailDataUrl": None,
                    "thumbnailRebuildUrl": None,
                },
                {
                    "outputName": "outputParticles",
                    "outputClassName": "SetOfParticles",
                    "exists": True,
                    "thumbnailUrl": "/projects/7/protocols/11/outputs/outputParticles/thumbnail",
                    "thumbnailDataUrl": None,
                    "thumbnailRebuildUrl": None,
                },
            ],
        }
    ]


def test_CollectSortedOutputCandidatesUsesDetachedPostgresqlOutputs(
        thumbnailServiceModule,
        tmp_path,
):
    projectPath = (
        tmp_path
        / "PostgresqlProject"
    )

    projectPath.mkdir(
        parents=True,
        exist_ok=True,
    )

    protocol = FakeProtocol(
        objId=10,
        label="Protocol 10",
        status="finished",
        outputs=[],
    )

    persistedOutput = (
        FakePersistedOutput(
            className="SetOfParticles",
            size=8,
            parentId=10,
            objectName=(
                "10.outputParticles"
            ),
        )
    )

    runtimeMapper = (
        FakePostgresqlRuntimeMapper(
            sets=[
                persistedOutput,
            ]
        )
    )

    graph = FakeGraph({
        "PROJECT": FakeNode(
            run=None
        ),
        "10": FakeNode(
            run=protocol
        ),
    })

    currentProject = (
        FakeCurrentProject(
            projectPath=str(
                projectPath
            ),
            protocols={
                10: protocol,
            },
            graph=graph,
            mapper=runtimeMapper,
        )
    )

    service = (
        thumbnailServiceModule
        .ThumbnailService(
            currentProject
        )
    )

    candidates = (
        service
        ._collectSortedOutputCandidates(
            protocol
        )
    )

    assert len(candidates) == 1

    assert (
        candidates[0][
            "outputName"
        ]
        == "outputParticles"
    )

    assert (
        candidates[0][
            "output"
        ]
        is persistedOutput
    )

    assert (
        candidates[0][
            "itemsCount"
        ]
        == 8
    )


def test_NativeProtocolOutputWinsOverPostgresqlFallback(
        thumbnailServiceModule,
        tmp_path,
):
    projectPath = (
        tmp_path
        / "PostgresqlProject"
    )

    projectPath.mkdir(
        parents=True,
        exist_ok=True,
    )

    nativeOutput = FakeOutput(
        className="SetOfParticles",
        size=4,
    )

    persistedOutput = (
        FakePersistedOutput(
            className="SetOfParticles",
            size=8,
            parentId=10,
            objectName=(
                "10.outputParticles"
            ),
        )
    )

    protocol = FakeProtocol(
        objId=10,
        outputs=[
            (
                "outputParticles",
                nativeOutput,
            ),
        ],
    )

    currentProject = (
        FakeCurrentProject(
            projectPath=str(
                projectPath
            ),
            mapper=(
                FakePostgresqlRuntimeMapper(
                    sets=[
                        persistedOutput,
                    ]
                )
            ),
        )
    )

    service = (
        thumbnailServiceModule
        .ThumbnailService(
            currentProject
        )
    )

    outputs = list(
        service
        ._iterOutputAttributes(
            protocol
        )
    )

    assert outputs == [
        (
            "outputParticles",
            nativeOutput,
        ),
    ]


def test_BuildProtocolOutputThumbnailReturnsNegativeCacheWithoutResolvingOutput(service, monkeypatch, tmp_path):
    protocol = FakeProtocol(10, label="Prot 10", status="finished")
    service.currentProject._protocols = {10: protocol}

    pngCachePath = tmp_path / "protocol_10_outputVol_128_v1.png"
    negativeCachePath = tmp_path / "protocol_10_outputVol_128_v1.missing.json"
    negativeCachePath.write_text(json.dumps({"outputClassName": "SetOfParticles", "error": "Thumbnail not available"}), encoding="utf-8")

    monkeypatch.setattr(service, "_getProtocolOutputCachePath", lambda protocolId, outputName, size: pngCachePath)
    monkeypatch.setattr(service, "_getProtocolOutputNegativeCachePath", lambda protocolId, outputName, size: negativeCachePath)
    monkeypatch.setattr(service, "_isValidCachedImage", lambda path: False)

    def failFindProtocolOutput(**kwargs):
        raise AssertionError("Negative cache must avoid output hydration")

    monkeypatch.setattr(service, "_findProtocolOutput", failFindProtocolOutput)

    result = service.buildProtocolOutputThumbnail(protocolId=10, outputName="outputVol", force=False, size=128)

    assert result == {
        "protocolId": 10,
        "protocolLabel": "Prot 10",
        "status": "finished",
        "outputName": "outputVol",
        "outputClassName": "SetOfParticles",
        "absolutePath": None,
        "cached": True,
        "exists": False,
        "error": "Thumbnail not available",
    }


def test_BuildProtocolOutputThumbnailCachesMissingRenderedPreview(service, monkeypatch, tmp_path):
    output = FakeOutput(className="SetOfParticles", size=5)
    protocol = FakeProtocol(10, label="Prot 10", status="finished", outputs=[("outputParticles", output)])
    service.currentProject._protocols = {10: protocol}

    pngCachePath = tmp_path / "protocol_10_outputParticles_128_v1.png"
    negativeCachePath = tmp_path / "protocol_10_outputParticles_128_v1.missing.json"

    monkeypatch.setattr(service, "_getProtocolOutputCachePath", lambda protocolId, outputName, size: pngCachePath)
    monkeypatch.setattr(service, "_getProtocolOutputNegativeCachePath", lambda protocolId, outputName, size: negativeCachePath)
    monkeypatch.setattr(service, "_isValidCachedImage", lambda path: False)
    monkeypatch.setattr(service, "_renderProtocolPreviewImage", lambda *args, **kwargs: None)

    firstResult = service.buildProtocolOutputThumbnail(protocolId=10, outputName="outputParticles", force=False, size=128)

    assert firstResult["exists"] is False
    assert json.loads(negativeCachePath.read_text(encoding="utf-8")) == {
        "outputClassName": "SetOfParticles",
        "error": "Thumbnail not available",
    }

    def failFindProtocolOutput(**kwargs):
        raise AssertionError("The second request must use the negative cache")

    monkeypatch.setattr(service, "_findProtocolOutput", failFindProtocolOutput)

    secondResult = service.buildProtocolOutputThumbnail(protocolId=10, outputName="outputParticles", force=False, size=128)

    assert secondResult == {
        "protocolId": 10,
        "protocolLabel": "Prot 10",
        "status": "finished",
        "outputName": "outputParticles",
        "outputClassName": "SetOfParticles",
        "absolutePath": None,
        "cached": True,
        "exists": False,
        "error": "Thumbnail not available",
    }




