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
from fastapi import HTTPException, status
from PIL import Image
import pytest
from types import SimpleNamespace

from app.backend.api.services.coords2d_service import Coords2dService


class FakeProjectService:
    pass


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr("app.backend.api.services.coords2d_service.ProjectService", FakeProjectService)
    return Coords2dService()


class FakeReader:
    def __init__(self, micrographs=None, coordinates=None, micrographImageInfo=None):
        self.micrographs = micrographs
        self.coordinates = coordinates
        self.micrographImageInfo = micrographImageInfo
        self.lastSkipReason = None

    def listMicrographs(self):
        return self.micrographs

    def listCoordinatesForMicrograph(self, micId):
        return self.coordinates

    def getMicrographImageInfo(self, micId):
        return self.micrographImageInfo


def test_Coords2dServiceListMicrographsUsesPostgresqlReader(service, monkeypatch):
    expected = {
        "micrographs": [{"id": "10", "particles": 2}],
        "totalMicrographs": 1,
        "totalPicks": 2,
        "boxSize": 128,
    }

    monkeypatch.setattr(
        service,
        "_getPostgresqlCoords2dReaderIfAvailable",
        lambda **kwargs: FakeReader(micrographs=expected),
    )

    payload = service.listMicrographs(
        mapper=object(),
        projectId=1,
        currentUser={"id": 1},
        protocolId=2,
        outputName="coordinates",
    )

    assert payload == expected


def test_Coords2dServiceListCoordinatesUsesPostgresqlReader(service, monkeypatch):
    expected = {
        "coordinates": [
            {"id": 1, "micId": "10", "x": 11.5, "y": 22.5}
        ]
    }

    monkeypatch.setattr(
        service,
        "_getPostgresqlCoords2dReaderIfAvailable",
        lambda **kwargs: FakeReader(coordinates=expected),
    )

    payload = service.listCoordinatesForMicrograph(
        mapper=object(),
        projectId=1,
        currentUser={"id": 1},
        protocolId=2,
        outputName="coordinates",
        micId="10",
    )

    assert payload == expected


def test_Coords2dServiceRaisesWhenPostgresqlReaderMissing(service, monkeypatch):

    monkeypatch.setattr(
        service,
        "_getPostgresqlCoords2dReaderIfAvailable",
        lambda **kwargs: None,
    )

    with pytest.raises(HTTPException) as exc:
        service.listMicrographs(
            mapper=object(),
            projectId=1,
            currentUser={"id": 1},
            protocolId=2,
            outputName="coordinates",
        )

    assert exc.value.status_code == 404
    assert "Coordinates2D output is not available in PostgreSQL metadata" in str(exc.value.detail)


class FakePathResolver:
    def __init__(self, resolvedPath, projectPath=None):
        self._resolvedPath = resolvedPath
        self._projectPath = projectPath

    def resolveExistingPath(self, storedImagePath):
        return self._resolvedPath

    def getProjectPath(self):
        return self._projectPath


class FakeImageStack:
    def __init__(self, image):
        self._image = image

    def getImage(self, index=None, pilImage=True):
        return self._image


def _setUpRenderMicrographImageMocks(monkeypatch, service, tmp_path, openCalls):
    micrographFile = tmp_path / "micrograph_10.mrc"
    micrographFile.write_bytes(b"fake-mrc-bytes")

    projectPath = tmp_path / "project"
    projectPath.mkdir()

    reader = FakeReader(
        micrographImageInfo={
            "id": "10",
            "fileName": "Runs/000001_Import/extra/micrograph_10.mrc",
            "locationIndex": None,
            "label": "micrograph_10",
        }
    )

    monkeypatch.setattr(service, "_getPostgresqlCoords2dReaderIfAvailable", lambda **kwargs: reader)

    monkeypatch.setattr(
        "app.backend.api.services.coords2d_service.PostgresqlProjectPathResolver",
        lambda db, projectId: FakePathResolver(str(micrographFile), projectPath=projectPath),
    )

    def fakeOpen(path):
        openCalls.append(path)
        return FakeImageStack(Image.new("L", (20, 16)))

    monkeypatch.setattr(
        "app.backend.api.services.coords2d_service.ImageReadersRegistry.open",
        fakeOpen,
    )

    return reader, str(micrographFile), projectPath


def test_Coords2dServiceRenderMicrographImageSetsEtagInsteadOfNoStore(service, monkeypatch, tmp_path):
    openCalls = []
    _reader, micrographPath, _projectPath = _setUpRenderMicrographImageMocks(monkeypatch, service, tmp_path, openCalls)

    response = service.renderMicrographImage(
        mapper=SimpleNamespace(db=object()),
        projectId=1,
        currentUser={"id": 1},
        protocolId=2,
        outputName="coordinates",
        micId="10",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.headers["ETag"]
    assert response.headers["Cache-Control"] != "no-store"
    assert "no-store" not in response.headers["Cache-Control"]
    assert openCalls == [micrographPath]


def test_Coords2dServiceRenderMicrographImageShortCircuitsOn304(service, monkeypatch, tmp_path):
    openCalls = []
    _setUpRenderMicrographImageMocks(monkeypatch, service, tmp_path, openCalls)

    firstResponse = service.renderMicrographImage(
        mapper=SimpleNamespace(db=object()),
        projectId=1,
        currentUser={"id": 1},
        protocolId=2,
        outputName="coordinates",
        micId="10",
    )
    etag = firstResponse.headers["ETag"]
    assert len(openCalls) == 1

    secondResponse = service.renderMicrographImage(
        mapper=SimpleNamespace(db=object()),
        projectId=1,
        currentUser={"id": 1},
        protocolId=2,
        outputName="coordinates",
        micId="10",
        ifNoneMatch=etag,
    )

    assert secondResponse.status_code == status.HTTP_304_NOT_MODIFIED
    assert secondResponse.headers["ETag"] == etag
    # The whole point: a revalidation hit must not re-decode the image.
    assert len(openCalls) == 1


def test_Coords2dServiceRenderMicrographImageMismatchedEtagStillRenders(service, monkeypatch, tmp_path):
    openCalls = []
    _setUpRenderMicrographImageMocks(monkeypatch, service, tmp_path, openCalls)

    response = service.renderMicrographImage(
        mapper=SimpleNamespace(db=object()),
        projectId=1,
        currentUser={"id": 1},
        protocolId=2,
        outputName="coordinates",
        micId="10",
        ifNoneMatch='"stale-etag-from-a-different-render"',
    )

    assert response.status_code == status.HTTP_200_OK
    assert len(openCalls) == 1


def test_Coords2dServiceRenderMicrographImageReusesOnDiskCacheAcrossRequests(service, monkeypatch, tmp_path):
    # Simulates two independent requests that don't share an in-memory
    # ETag (e.g. two different browsers, or the process having restarted
    # between them) -- the on-disk cache, not the 304 shortcut, must be
    # what avoids the second decode.
    openCalls = []
    _reader, _micrographPath, projectPath = _setUpRenderMicrographImageMocks(
        monkeypatch, service, tmp_path, openCalls
    )

    firstResponse = service.renderMicrographImage(
        mapper=SimpleNamespace(db=object()),
        projectId=1,
        currentUser={"id": 1},
        protocolId=2,
        outputName="coordinates",
        micId="10",
    )

    assert len(openCalls) == 1

    cacheDir = projectPath / ".thumbnail_cache" / "coords2d"
    cachedImages = list(cacheDir.glob("*.png"))
    cachedMeta = list(cacheDir.glob("*.json"))
    assert len(cachedImages) == 1
    assert len(cachedMeta) == 1

    secondResponse = service.renderMicrographImage(
        mapper=SimpleNamespace(db=object()),
        projectId=1,
        currentUser={"id": 1},
        protocolId=2,
        outputName="coordinates",
        micId="10",
    )

    assert secondResponse.status_code == status.HTTP_200_OK
    assert secondResponse.headers["ETag"] == firstResponse.headers["ETag"]
    assert secondResponse.headers["X-Preview-Width"] == firstResponse.headers["X-Preview-Width"]
    assert secondResponse.body == firstResponse.body
    # The actual point of this test: still only one decode, ever.
    assert len(openCalls) == 1


class FakeMultiMicrographReader:
    def __init__(self, infoByMicId):
        self.infoByMicId = infoByMicId
        self.lastSkipReason = "micrograph_not_found"

    def getMicrographImageInfo(self, micId):
        return self.infoByMicId.get(str(micId))


def _setUpBatchMocks(monkeypatch, service, tmp_path, openCalls, micIds):
    projectPath = tmp_path / "project"
    projectPath.mkdir()

    infoByMicId = {}
    for micId in micIds:
        micrographFile = tmp_path / f"micrograph_{micId}.mrc"
        micrographFile.write_bytes(f"fake-mrc-bytes-{micId}".encode("utf-8"))
        infoByMicId[str(micId)] = {
            "id": str(micId),
            "fileName": f"Runs/000001_Import/extra/micrograph_{micId}.mrc",
            "locationIndex": None,
            "label": f"micrograph_{micId}",
        }

    reader = FakeMultiMicrographReader(infoByMicId)
    monkeypatch.setattr(service, "_getPostgresqlCoords2dReaderIfAvailable", lambda **kwargs: reader)

    def fakePathResolverFactory(db, projectId):
        class _Resolver:
            def resolveExistingPath(self, storedImagePath):
                fileName = storedImagePath.rsplit("/", 1)[-1]
                return str(tmp_path / fileName)

            def getProjectPath(self):
                return projectPath

        return _Resolver()

    monkeypatch.setattr(
        "app.backend.api.services.coords2d_service.PostgresqlProjectPathResolver",
        fakePathResolverFactory,
    )

    def fakeOpen(path):
        openCalls.append(path)
        return FakeImageStack(Image.new("L", (20, 16)))

    monkeypatch.setattr(
        "app.backend.api.services.coords2d_service.ImageReadersRegistry.open",
        fakeOpen,
    )

    return projectPath


def test_Coords2dServiceThumbnailBatchRendersAllRequestedMicrographs(service, monkeypatch, tmp_path):
    openCalls = []
    _setUpBatchMocks(monkeypatch, service, tmp_path, openCalls, micIds=["10", "20"])

    result = service.renderCoords2dMicrographsThumbnailBatch(
        mapper=SimpleNamespace(db=object()),
        projectId=1,
        currentUser={"id": 1},
        protocolId=2,
        outputName="coordinates",
        payload={"micIds": ["10", "20"], "size": 96, "format": "png"},
    )

    assert result["errors"] == []
    assert [item["id"] for item in result["items"]] == ["10", "20"]
    assert all(item["dataUrl"].startswith("data:image/png;base64,") for item in result["items"])
    assert all(item["width"] and item["height"] for item in result["items"])
    assert len(openCalls) == 2


def test_Coords2dServiceThumbnailBatchReusesDiskCacheFromSingleImageEndpoint(service, monkeypatch, tmp_path):
    openCalls = []
    _setUpBatchMocks(monkeypatch, service, tmp_path, openCalls, micIds=["10"])

    # Pre-warm the cache exactly like a prior single-image request would.
    service.renderMicrographImage(
        mapper=SimpleNamespace(db=object()),
        projectId=1,
        currentUser={"id": 1},
        protocolId=2,
        outputName="coordinates",
        micId="10",
        size=96,
        fmt="png",
    )
    assert len(openCalls) == 1

    result = service.renderCoords2dMicrographsThumbnailBatch(
        mapper=SimpleNamespace(db=object()),
        projectId=1,
        currentUser={"id": 1},
        protocolId=2,
        outputName="coordinates",
        payload={"micIds": ["10"], "size": 96, "format": "png"},
    )

    assert result["errors"] == []
    assert len(result["items"]) == 1
    # The batch call must hit the same on-disk cache, not decode again.
    assert len(openCalls) == 1


def test_Coords2dServiceThumbnailBatchCollectsPerItemErrors(service, monkeypatch, tmp_path):
    openCalls = []
    _setUpBatchMocks(monkeypatch, service, tmp_path, openCalls, micIds=["10"])

    result = service.renderCoords2dMicrographsThumbnailBatch(
        mapper=SimpleNamespace(db=object()),
        projectId=1,
        currentUser={"id": 1},
        protocolId=2,
        outputName="coordinates",
        payload={"micIds": ["10", "does-not-exist"]},
    )

    assert [item["id"] for item in result["items"]] == ["10"]
    assert len(result["errors"]) == 1
    assert result["errors"][0]["id"] == "does-not-exist"
    assert "not available" in result["errors"][0]["detail"]


def test_Coords2dServiceThumbnailBatchRejectsNonListMicIds(service):
    with pytest.raises(HTTPException) as exc:
        service.renderCoords2dMicrographsThumbnailBatch(
            mapper=SimpleNamespace(db=object()),
            projectId=1,
            currentUser={"id": 1},
            protocolId=2,
            outputName="coordinates",
            payload={"micIds": "10"},
        )

    assert exc.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_Coords2dServiceThumbnailBatchRejectsOversizedBatch(service):
    with pytest.raises(HTTPException) as exc:
        service.renderCoords2dMicrographsThumbnailBatch(
            mapper=SimpleNamespace(db=object()),
            projectId=1,
            currentUser={"id": 1},
            protocolId=2,
            outputName="coordinates",
            payload={"micIds": [str(i) for i in range(201)]},
        )

    assert exc.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY