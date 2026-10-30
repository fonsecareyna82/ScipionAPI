"""Uploads from the user's computer into a project's Uploads folder: in chunks, resumable, never over a file."""
import importlib
from collections import namedtuple

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

DATA = bytes(range(256)) * 100  # 25600 bytes


class Mapper:
    def __init__(self, access="work"):
        self.access = access

    def getProject(self, projectId, userId):
        return {"id": projectId, "access": self.access}


class Service:
    def __init__(self, projectPath):
        self.projectPath = projectPath

    def getProjectDbRow(self, mapper, projectId, currentUser):
        return {"id": projectId, "name": str(self.projectPath)}


@pytest.fixture
def uploads():
    return importlib.import_module("app.backend.api.services.project_upload_service")


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "Proj"
    folder.mkdir()
    return folder


def _client(authTestEnv, project, permissions=("files.upload",), access="work", userId=3):
    router = importlib.import_module("app.backend.api.routers.project_upload_router")
    dependencies = importlib.import_module("app.backend.api.dependencies")
    database = importlib.import_module("app.backend.database")
    audit = importlib.import_module("app.backend.api.audit")
    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides[dependencies.getCurrentUser] = lambda: {"id": userId, "permissions": list(permissions)}
    app.dependency_overrides[database.getMapper] = lambda: Mapper(access)
    app.dependency_overrides[router.getProjectService] = lambda: Service(project)
    events = []
    audit_record = audit.recordAudit
    router.recordAudit = lambda mapper, user, action, *args: events.append((action, args))
    client = TestClient(app)
    client.events = events
    client.restore = lambda: setattr(router, "recordAudit", audit_record)
    return client


def _upload(client, name="mask.mrc", data=DATA, chunk=10000):
    start = client.post("/projects/7/uploads", json={"name": name, "size": len(data)})
    assert start.status_code == 200, start.text
    uploadId = start.json()["uploadId"]
    for offset in range(0, len(data), chunk):
        part = client.put("/projects/7/uploads/%s?offset=%d" % (uploadId, offset), content=data[offset:offset + chunk])
        assert part.status_code == 200, part.text
    return uploadId, client.post("/projects/7/uploads/%s/complete" % uploadId)


def test_a_file_uploads_in_chunks_into_the_projects_uploads_folder(authTestEnv, project):
    client = _client(authTestEnv, project)
    try:
        _, done = _upload(client)
        assert done.status_code == 200, done.text
        assert done.json()["path"] == "Uploads/mask.mrc"
        assert done.json()["absPath"] == (project.resolve() / "Uploads" / "mask.mrc").as_posix()
        assert (project / "Uploads" / "mask.mrc").read_bytes() == DATA
        # Nothing partial is left behind, and the upload is in the audit log
        assert list((project / "Uploads" / ".partial").iterdir()) == []
        assert client.events[0][0] == "projects.fileUploaded"
    finally:
        client.restore()


def test_an_interrupted_upload_resumes_from_what_arrived(authTestEnv, project):
    client = _client(authTestEnv, project)
    try:
        uploadId = client.post("/projects/7/uploads", json={"name": "ref.mrc", "size": len(DATA)}).json()["uploadId"]
        assert client.put("/projects/7/uploads/%s?offset=0" % uploadId, content=DATA[:10000]).status_code == 200
        # A chunk sent again after a drop is refused with where to go on
        again = client.put("/projects/7/uploads/%s?offset=0" % uploadId, content=DATA[:10000])
        assert again.status_code == 409 and again.json()["detail"]["received"] == 10000
        assert client.get("/projects/7/uploads/%s" % uploadId).json()["received"] == 10000
        assert client.put("/projects/7/uploads/%s?offset=10000" % uploadId, content=DATA[10000:]).status_code == 200
        assert client.post("/projects/7/uploads/%s/complete" % uploadId).status_code == 200
        assert (project / "Uploads" / "ref.mrc").read_bytes() == DATA
    finally:
        client.restore()


def test_an_incomplete_upload_is_not_given_its_name(authTestEnv, project):
    client = _client(authTestEnv, project)
    try:
        uploadId = client.post("/projects/7/uploads", json={"name": "half.mrc", "size": len(DATA)}).json()["uploadId"]
        client.put("/projects/7/uploads/%s?offset=0" % uploadId, content=DATA[:100])
        assert client.post("/projects/7/uploads/%s/complete" % uploadId).status_code == 409
        assert not (project / "Uploads" / "half.mrc").exists()
        assert client.delete("/projects/7/uploads/%s" % uploadId).status_code == 200
        assert list((project / "Uploads" / ".partial").iterdir()) == []
    finally:
        client.restore()


def test_an_existing_file_is_never_replaced(authTestEnv, project):
    (project / "Uploads").mkdir()
    (project / "Uploads" / "mask.mrc").write_bytes(b"mine")
    client = _client(authTestEnv, project)
    try:
        assert client.post("/projects/7/uploads", json={"name": "mask.mrc", "size": 4}).status_code == 409
        # Nor when a file of that name appears while the upload goes on
        uploadId = client.post("/projects/7/uploads", json={"name": "late.mrc", "size": 4}).json()["uploadId"]
        client.put("/projects/7/uploads/%s?offset=0" % uploadId, content=b"abcd")
        (project / "Uploads" / "late.mrc").write_bytes(b"theirs")
        assert client.post("/projects/7/uploads/%s/complete" % uploadId).status_code == 409
        assert (project / "Uploads" / "late.mrc").read_bytes() == b"theirs"
        assert (project / "Uploads" / "mask.mrc").read_bytes() == b"mine"
    finally:
        client.restore()


@pytest.mark.parametrize("name", ["../escape.mrc", "sub/dir.mrc", ".hidden", "..", "a\\b.mrc", "bad\x01name"])
def test_names_are_plain_visible_file_names(authTestEnv, project, name):
    client = _client(authTestEnv, project)
    try:
        assert client.post("/projects/7/uploads", json={"name": name, "size": 1}).status_code == 400
        assert not (project.parent / "escape.mrc").exists()
    finally:
        client.restore()


def test_the_size_limit_and_the_free_space_are_checked_first(authTestEnv, project, uploads, monkeypatch):
    client = _client(authTestEnv, project)
    try:
        monkeypatch.setenv("SCIPIONWEB_UPLOAD_MAX_GB", "1")
        big = client.post("/projects/7/uploads", json={"name": "movies.tif", "size": 2 * 1024 ** 3})
        assert big.status_code == 413 and "up to 1.0 GB" in big.json()["detail"]
        monkeypatch.setenv("SCIPIONWEB_UPLOAD_MAX_GB", "0")
        Usage = namedtuple("Usage", "total used free")
        monkeypatch.setattr(uploads.shutil, "disk_usage", lambda path: Usage(100, 99, 3 * 1024 ** 3))
        full = client.post("/projects/7/uploads", json={"name": "vol.mrc", "size": 2 * 1024 ** 3})
        assert full.status_code == 507 and "free disk space" in full.json()["detail"]
    finally:
        client.restore()


def test_uploading_needs_the_permission_and_work_access(authTestEnv, project):
    for kwargs in ({"permissions": ()}, {"access": "view"}):
        client = _client(authTestEnv, project, **kwargs)
        try:
            assert client.post("/projects/7/uploads", json={"name": "m.mrc", "size": 1}).status_code == 403
        finally:
            client.restore()


def test_only_who_started_an_upload_may_go_on_with_it(authTestEnv, project):
    owner = _client(authTestEnv, project, userId=3)
    try:
        uploadId = owner.post("/projects/7/uploads", json={"name": "m.mrc", "size": 4}).json()["uploadId"]
    finally:
        owner.restore()
    other = _client(authTestEnv, project, userId=4)
    try:
        assert other.put("/projects/7/uploads/%s?offset=0" % uploadId, content=b"abcd").status_code == 404
        assert other.get("/projects/7/uploads/../../etc").status_code == 404
    finally:
        other.restore()


def test_stale_partial_files_are_removed_when_an_upload_starts(uploads, project, monkeypatch):
    old = uploads.startUpload(project, 3, "old.mrc", 10)
    partial = project / "Uploads" / ".partial"
    later = uploads.time.time() + uploads.STALE_PARTIAL_SECONDS + 60
    monkeypatch.setattr(uploads.time, "time", lambda: later)
    uploads.startUpload(project, 3, "new.mrc", 10)
    assert not (partial / (old.uploadId + ".part")).exists()
    assert len(list(partial.iterdir())) == 2  # the new upload's data and description
