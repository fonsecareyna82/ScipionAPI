"""The file browser routes: the protocol comes from the database, the project is never loaded."""
import importlib
import json

import pytest
from fastapi import HTTPException

from app.backend.api.schemas.protocols_schema import RemoteFileWriteRequest


class Mapper:
    def getProjectProtocolByProtocolId(self, projectId, protocolId):
        return {"protocolId": "12", "protocolClassName": "ProtImportMovies"} if str(protocolId) == "12" else None


class Service:
    def __init__(self, projectPath, allowed=True):
        self.projectPath = projectPath
        self.allowed = allowed

    def getProjectDbRow(self, mapper, projectId, currentUser):
        return {"id": projectId, "name": str(self.projectPath)} if self.allowed else None

    def loadPostgresqlRuntimeProjectForMutation(self, **kwargs):
        raise AssertionError("browsing must not load the project")

    @staticmethod
    def _inspectScipionSqliteDatabase(*args, **kwargs):
        return None


@pytest.fixture
def router(authTestEnv):
    return importlib.import_module("app.backend.api.routers.project_router")


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "Proj" / "Runs" / "000012_ProtImportMovies"
    folder.mkdir(parents=True)
    (folder / "run.star").write_text("data_\nloop_\n_a\n_b\n1 2\n3 4\n")
    return tmp_path / "Proj"


def test_listing_and_start_path_of_a_protocol(router, project):
    service, user = Service(project), {"id": 1}
    start = router.getProtocolPath(projectId=7, protocolId="12", scope="project", currentUser=user,
                                   mapper=Mapper(), service=service)
    assert start["startPath"] == "Runs/000012_ProtImportMovies"
    listed = router.listProtocolDir(projectId=7, protocolId="12", path=start["startPath"], scope="project",
                                    currentUser=user, mapper=Mapper(), service=service)
    assert [entry["name"] for entry in listed] == ["run.star"]
    # The whole filesystem for the files a protocol form points to.
    anywhere = router.getProtocolPath(projectId=7, protocolId="12", scope="filesystem", currentUser=user,
                                      mapper=Mapper(), service=service)
    assert anywhere["rootAbs"] == "/" and anywhere["projectRootAbs"] == str(project.resolve())


def test_star_files_preview_as_tables(router, project):
    response = router.previewRemoteEntry(projectId=7, protocolId="12", path="Runs/000012_ProtImportMovies/run.star",
                                         scope="project", currentUser={"id": 1}, mapper=Mapper(),
                                         service=Service(project))
    assert response.headers["X-Preview-Kind"] == "table"
    assert json.loads(response.body)["blocks"][0]["rows"] == [["1", "2"], ["3", "4"]]


def test_access_to_the_project_is_checked(router, project):
    with pytest.raises(HTTPException) as error:
        router.listProtocolDir(projectId=7, protocolId="12", path="", scope="project", currentUser={"id": 2},
                               mapper=Mapper(), service=Service(project, allowed=False))
    assert error.value.status_code == 404


def test_writes_go_inside_the_project(router, project):
    service = Service(project)
    written = router.writeRemoteFile(projectId=7, protocolId="12",
                                     payload=RemoteFileWriteRequest(path="exports/wf.json", content="{}"),
                                     currentUser={"id": 1}, mapper=Mapper(), service=service)
    assert written["success"] and (project / "exports" / "wf.json").read_text() == "{}"
    with pytest.raises(HTTPException) as error:
        router.writeRemoteFile(projectId=7, protocolId="12",
                               payload=RemoteFileWriteRequest(path="../../outside.json", content="{}"),
                               currentUser={"id": 1}, mapper=Mapper(), service=service)
    assert error.value.status_code == 403
