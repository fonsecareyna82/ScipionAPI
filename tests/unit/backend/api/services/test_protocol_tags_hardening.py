"""Tags: validation, clean conflicts, atomic replacement and copying with protocols."""
import importlib
from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.backend.api.schemas.tags_schema import ProtocolTagCreateIn, ProtocolTagsSetIn, ProtocolTagUpdateIn


@pytest.fixture
def postgresql(authTestEnv):
    return importlib.import_module("app.backend.mapper.postgresql")


@pytest.fixture
def service(authTestEnv):
    return importlib.import_module("app.backend.api.services.project_service").ProjectService()


# -- validation -------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    {"title": "   "},
    {"title": "x" * 81},
    {"title": "ok", "color": "red"},
    {"title": "ok", "color": "#12345"},
    {"title": "ok", "description": "d" * 1001},
    {"title": "ok", "id": "has space"},
])
def test_invalid_tags_are_rejected(payload):
    with pytest.raises(ValidationError):
        ProtocolTagCreateIn(**payload)


def test_valid_tags_are_cleaned():
    tag = ProtocolTagCreateIn(title="  Good  ", color="#3B82F6", id="tag_1:a.b-c")
    assert (tag.title, tag.color, tag.id) == ("Good", "#3B82F6", "tag_1:a.b-c")
    assert ProtocolTagCreateIn(title="x", color="").color is None


def test_an_update_knows_which_fields_were_sent():
    assert ProtocolTagUpdateIn(description=None).__fields_set__ == {"description"}
    with pytest.raises(ValidationError):
        ProtocolTagUpdateIn(title="")
    with pytest.raises(ValidationError):
        ProtocolTagsSetIn(tagIds=["t"] * 201)


# -- service ----------------------------------------------------------------------

class Mapper:
    def __init__(self, postgresql, conflict=False, existing=True):
        self.postgresql, self.conflict, self.existing = postgresql, conflict, existing
        self.updates = []

    def insertProtocolTag(self, projectId, tag):
        if self.conflict:
            raise self.postgresql.ProtocolTagConflict(tag["id"])
        return dict(tag, projectId=projectId)

    def updateProtocolTag(self, projectId, tagId, fields):
        self.updates.append(fields)
        if self.conflict:
            raise self.postgresql.ProtocolTagConflict(tagId)
        return dict(fields, id=tagId) if self.existing else None


def test_a_duplicate_title_is_a_clean_409(service, postgresql, monkeypatch):
    monkeypatch.setattr(service, "_touchProjectModificationTime", lambda **_: None)
    with pytest.raises(HTTPException) as error:
        service.createProjectTag(Mapper(postgresql, conflict=True), 1, {"id": 1}, ProtocolTagCreateIn(title="Good"))
    assert error.value.status_code == 409
    assert "Good" in error.value.detail and "duplicate key" not in error.value.detail


def test_a_saved_change_is_not_reported_as_failed_when_touching_the_project_fails(service, postgresql, monkeypatch):
    def fail(**_):
        raise RuntimeError("touch failed")
    monkeypatch.setattr(service, "_touchProjectModificationTime", fail)
    tag = service.createProjectTag(Mapper(postgresql), 1, {"id": 1}, ProtocolTagCreateIn(title="Good", id="t1"))
    assert tag["id"] == "t1"


def test_an_update_changes_only_what_was_sent(service, postgresql, monkeypatch):
    monkeypatch.setattr(service, "_touchProjectModificationTime", lambda **_: None)
    mapper = Mapper(postgresql)
    service.updateProjectTag(mapper, 1, "t1", {"id": 1}, ProtocolTagUpdateIn(color=None))
    service.updateProjectTag(mapper, 1, "t1", {"id": 1}, ProtocolTagUpdateIn(title=" New "))
    assert mapper.updates == [{"color": None}, {"title": "New"}]
    with pytest.raises(HTTPException) as error:
        service.updateProjectTag(Mapper(postgresql, existing=False), 1, "t9", {"id": 1}, ProtocolTagUpdateIn(title="x"))
    assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        service.updateProjectTag(Mapper(postgresql, conflict=True), 1, "t1", {"id": 1}, ProtocolTagUpdateIn(title="Bad"))
    assert error.value.status_code == 409


def test_deleting_a_missing_tag_is_404(authTestEnv):
    router = importlib.import_module("app.backend.api.routers.project_router")

    class Service:
        def getProjectDbRow(self, mapper, projectId, currentUser):
            return {"id": projectId}

        def deleteProjectTag(self, **_):
            return False

    with pytest.raises(HTTPException) as error:
        router.deleteProjectTag(projectId=1, tagId="gone", currentUser={"id": 1}, mapper=object(), service=Service())
    assert error.value.status_code == 404


# -- mapper -----------------------------------------------------------------------

class Cursor:
    def __init__(self, row=None, rowcount=1):
        self.row, self.rowcount = row, rowcount

    def fetchone(self):
        return self.row


class Db:
    def __init__(self, projectTagIds=(), protocol=True, insertRow=None):
        self.projectTagIds = list(projectTagIds)
        self.protocol = protocol
        self.insertRow = insertRow
        self.statements = []
        self.inTransaction = False
        self.transactions = 0

    @contextmanager
    def transaction(self):
        self.transactions += 1
        self.inTransaction = True
        try:
            yield self
        finally:
            self.inTransaction = False

    def fetchOne(self, query, params=None):
        self.statements.append(("one", " ".join(query.split()), params, self.inTransaction))
        return {"id": 5, "protocolId": "12"} if self.protocol else None

    def fetchAll(self, query, params=None):
        self.statements.append(("all", " ".join(query.split()), params, self.inTransaction))
        return [{"id": tagId} for tagId in self.projectTagIds if tagId in params[1]]

    def execute(self, query, params=None, commit=True):
        self.statements.append(("exec", " ".join(query.split()), params, self.inTransaction))
        return Cursor(self.insertRow)


def make_mapper(postgresql, db):
    mapper = object.__new__(postgresql.PostgresqlFlatMapper)
    mapper.db = db
    return mapper


def test_replacing_tags_is_one_transaction_that_keeps_only_tags_of_the_project(postgresql):
    db = Db(projectTagIds=["a", "b"])
    result = make_mapper(postgresql, db).setProtocolTagIdsByProtocolDbId(projectId=1, protocolDbId=5, tagIds=["b", "gone", "a", " a "])
    assert result == {"protocolId": "12", "tagIds": ["a", "b"], "ignoredTagIds": ["gone"]}
    assert db.transactions == 1
    assert all(inTransaction for *_rest, inTransaction in db.statements)
    lock, filtered, delete, insert = db.statements
    assert "FOR UPDATE" in lock[1]
    assert filtered[2] == (1, ["a", "b", "gone"])
    assert delete[1].startswith("DELETE FROM protocol_tag_assignments")
    assert insert[2] == (5, ["a", "b"])


def test_replacing_tags_of_a_protocol_of_another_project_fails_before_writing(postgresql):
    db = Db(protocol=False)
    with pytest.raises(LookupError):
        make_mapper(postgresql, db).setProtocolTagIdsByProtocolDbId(projectId=1, protocolDbId=5, tagIds=["a"])
    assert [kind for kind, *_ in db.statements] == ["one"]


def test_creating_a_tag_whose_id_or_title_is_taken_is_a_conflict(postgresql):
    mapper = make_mapper(postgresql, Db(insertRow=None))
    with pytest.raises(postgresql.ProtocolTagConflict):
        mapper.insertProtocolTag(projectId=1, tag={"id": "t1", "title": "Good"})
    statement = mapper.db.statements[0][1]
    assert "ON CONFLICT DO NOTHING" in statement and "DO UPDATE" not in statement


# -- copying with protocols -------------------------------------------------------

def test_a_duplicate_copies_the_tags_and_never_fails_because_of_them(authTestEnv):
    duplicate = importlib.import_module("app.backend.runtime.protocol_duplicate_service").RuntimeProtocolDuplicateService

    class TagMapper:
        calls = []

        def copyProtocolTagAssignments(self, **kwargs):
            self.calls.append(kwargs)

    mapper = TagMapper()
    duplicate.copyProtocolTags(mapper=mapper, projectId=1, sourceProtocolDbId=5, duplicatedProtocolDbId=9)
    assert mapper.calls == [{"projectId": 1, "sourceProtocolDbId": 5, "targetProtocolDbId": 9}]

    class Failing:
        def copyProtocolTagAssignments(self, **kwargs):
            raise RuntimeError("boom")

    duplicate.copyProtocolTags(mapper=Failing(), projectId=1, sourceProtocolDbId=5, duplicatedProtocolDbId=9)


def test_exported_protocols_carry_their_tags_and_imports_apply_them_by_title(service, monkeypatch):
    class TagMapper:
        def __init__(self):
            self.ensured, self.added = [], []

        def getProtocolTagsByProtocolId(self, projectId, protocolIds):
            assert protocolIds == ["4", "7"]
            return {"4": [{"id": "t1", "title": "Good", "description": None, "color": "#22c55e"}]}

        def ensureProtocolTag(self, projectId, title, description=None, color=None):
            self.ensured.append((projectId, title, color))
            return "new-" + title

        def addProtocolTagAssignments(self, projectId, protocolDbId, tagIds):
            self.added.append((projectId, protocolDbId, tagIds))

    mapper = TagMapper()
    workflow = [{"object.id": "4", "object.className": "ProtA"}, {"object.id": "7", "object.className": "ProtB"}]
    service._addTagsToExportedWorkflow(mapper, 1, workflow)
    assert workflow[0][service.WORKFLOW_TAGS_KEY] == [{"title": "Good", "description": None, "color": "#22c55e"}]
    assert service.WORKFLOW_TAGS_KEY not in workflow[1]

    # A bad colour is not imported; the title is reused or created in the target project.
    workflow[0][service.WORKFLOW_TAGS_KEY].append({"title": "Odd", "color": "javascript:alert(1)"})
    monkeypatch.setattr(service, "_resolvePostgresqlProtocolDbIdFromScipionProtocolId",
                        lambda mapper, projectId, protocolId: {"41": 410}.get(str(protocolId)))
    service._applyImportedWorkflowTags(mapper, 2, workflow, [{"sourceId": "4", "newId": "41"}, {"sourceId": "7", "newId": "42"}])
    assert mapper.ensured == [(2, "Good", "#22c55e"), (2, "Odd", None)]
    assert mapper.added == [(2, 410, ["new-Good", "new-Odd"])]


# -- model ------------------------------------------------------------------------

def test_the_tag_model_matches_the_migrated_schema(authTestEnv):
    tagModel = importlib.import_module("app.backend.models.tag_model").ProtocolTag.__table__
    assert set(tagModel.columns.keys()) == {"id", "title", "description", "color", "createdAt", "updatedAt", "projectId"}
    assert not tagModel.columns["projectId"].nullable
    foreignKey, = tagModel.columns["projectId"].foreign_keys
    assert (foreignKey.target_fullname, foreignKey.ondelete, foreignKey.name) == ("projects.id", "CASCADE", "fk_protocol_tags_projectid")
    indexes = {index.name: index for index in tagModel.indexes}
    assert set(indexes) == {"idx_protocol_tags_projectid", "ux_protocol_tags_project_lower_title"}
    assert indexes["ux_protocol_tags_project_lower_title"].unique
