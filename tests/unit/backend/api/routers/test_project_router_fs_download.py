"""Downloads of the file browser: a signed link, then a plain streamed download that can resume."""
import importlib
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


class Mapper:
    def getProjectProtocolByProtocolId(self, projectId, protocolId):
        return {"protocolId": "12", "protocolClassName": "ProtImportMovies"}


class Service:
    def __init__(self, projectPath):
        self.projectPath = projectPath

    def getProjectDbRow(self, mapper, projectId, currentUser):
        return {"id": projectId, "name": str(self.projectPath)}


@pytest.fixture
def router(authTestEnv):
    return importlib.import_module("app.backend.api.routers.project_router")


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "Proj" / "Runs" / "000012_ProtImportMovies" / "extra"
    folder.mkdir(parents=True)
    (folder / "movie.tif").write_bytes(bytes(range(256)) * 40)
    return tmp_path / "Proj"


def _link(router, project, path, scope="project"):
    return router.createFsDownloadLink(projectId=7, protocolId="12",
                                       payload=router.FsDownloadLinkRequest(path=path, scope=scope),
                                       currentUser={"id": 3}, mapper=Mapper(), service=Service(project))


def test_a_link_downloads_the_file_in_chunks_and_resumes_with_ranges(router, project):
    link = _link(router, project, "Runs/000012_ProtImportMovies/extra/movie.tif")
    assert link["name"] == "movie.tif" and link["size"] == 10240
    assert link["url"].startswith("/projects/7/protocols/12/fs/download-file?token=fd.")
    token = parse_qs(urlparse(link["url"]).query)["token"][0]

    app = FastAPI()
    app.add_api_route("/projects/{projectId}/protocols/{protocolId}/fs/download-file", router.downloadFsFile)
    client = TestClient(app)
    whole = client.get(link["url"])
    assert whole.status_code == 200 and len(whole.content) == 10240
    assert 'attachment; filename="movie.tif"' in whole.headers["content-disposition"]
    assert whole.headers["accept-ranges"] == "bytes"
    part = client.get(link["url"], headers={"Range": "bytes=10000-"})
    assert part.status_code == 206 and part.content == (bytes(range(256)) * 40)[10000:]
    # The link is bound to its project.
    assert client.get(f"/projects/8/protocols/12/fs/download-file?token={token}").status_code == 403
    assert client.get("/projects/7/protocols/12/fs/download-file?token=fd.forged.x").status_code == 403


def test_links_follow_the_browsing_boundary(router, project, tmp_path):
    with pytest.raises(HTTPException) as error:
        _link(router, project, "Runs")
    assert error.value.status_code == 404
    outside = tmp_path / "disk" / "data.mrc"
    outside.parent.mkdir()
    outside.write_bytes(b"x")
    # Outside the project only with the filesystem scope (read only for protocol forms).
    with pytest.raises(HTTPException):
        _link(router, project, str(outside))
    assert _link(router, project, str(outside).lstrip("/"), scope="filesystem")["size"] == 1
