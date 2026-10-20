"""Protocol tags on the migrated schema: conflicts, atomic replacement, project scoping and copies."""
from uuid import uuid4

import pytest

from app.backend.mapper.postgresql import PostgresqlFlatMapper, ProtocolTagConflict


@pytest.fixture
def tagProjects(postgresqlIntegrationDb):
    mapper = PostgresqlFlatMapper(postgresqlIntegrationDb)
    suffix = uuid4().hex
    userId = mapper.insertUser(
        email="protocol-tags-%s@example.com" % suffix, hashedPassword="integration-test",
        firstName="Tags", lastName="Test", institution=None, role="user", isActive=True,
        isVerified=True, verificationCode="integration-test",
    )
    projects = []
    try:
        for index in range(2):
            projectId = mapper.insertProject(ownerId=userId, name="Tags %s %d" % (suffix, index),
                                             description="", status="active")
            projects.append(projectId)
        protocols = {}
        for projectId in projects:
            for protocolId in (2, 3):
                protocols[(projectId, protocolId)] = mapper.saveProtocol({
                    "info": {"protocolId": protocolId, "projectId": projectId,
                             "protocolClassName": "TagsProtocol", "status": "finished"},
                    "values": {}, "parentIds": [], "childIds": [],
                })
        yield mapper, projects, protocols
    finally:
        for projectId in projects:
            mapper.deleteProject(projectId=projectId, ownerId=userId)
        postgresqlIntegrationDb.execute("DELETE FROM users WHERE id = %s", (userId,))


def test_titles_are_unique_per_project_and_ids_are_never_overwritten(tagProjects):
    mapper, (projectA, projectB), _ = tagProjects
    idA = "a-" + uuid4().hex
    mapper.insertProtocolTag(projectA, {"id": idA, "title": "Good", "color": "#22c55e"})
    with pytest.raises(ProtocolTagConflict):
        mapper.insertProtocolTag(projectA, {"id": "b-" + uuid4().hex, "title": "good"})
    # The id of a tag of another project neither overwrites it nor moves it.
    with pytest.raises(ProtocolTagConflict):
        mapper.insertProtocolTag(projectB, {"id": idA, "title": "Stolen"})
    assert mapper.getProtocolTag(projectA, idA)["title"] == "Good"
    assert mapper.updateProtocolTag(projectB, idA, {"title": "Stolen"}) is None
    # Another project may use the same title.
    mapper.insertProtocolTag(projectB, {"id": "c-" + uuid4().hex, "title": "Good"})
    other = mapper.insertProtocolTag(projectA, {"id": "d-" + uuid4().hex, "title": "Bad"})
    with pytest.raises(ProtocolTagConflict):
        mapper.updateProtocolTag(projectA, other["id"], {"title": "GOOD"})
    assert mapper.updateProtocolTag(projectA, idA, {"color": None})["color"] is None


def test_replacing_keeps_only_tags_of_the_project_and_the_graph_shows_only_those(tagProjects):
    mapper, (projectA, projectB), protocols = tagProjects
    good = mapper.insertProtocolTag(projectA, {"id": "g-" + uuid4().hex, "title": "Good"})["id"]
    foreign = mapper.insertProtocolTag(projectB, {"id": "f-" + uuid4().hex, "title": "Foreign"})["id"]
    result = mapper.setProtocolTagIdsByProtocolDbId(projectA, protocols[(projectA, 2)], [good, foreign, "gone"])
    assert result["tagIds"] == [good]
    assert sorted(result["ignoredTagIds"]) == sorted([foreign, "gone"])
    assert mapper.getProjectProtocolTagIdsByProtocolId(projectA) == {"2": [good]}
    # Replacing with nothing removes them.
    assert mapper.setProtocolTagIdsByProtocolDbId(projectA, protocols[(projectA, 2)], [])["tagIds"] == []
    assert mapper.getProjectProtocolTagIdsByProtocolId(projectA) == {}
    with pytest.raises(LookupError):
        mapper.setProtocolTagIdsByProtocolDbId(projectA, protocols[(projectB, 2)], [good])


def test_copies_keep_tags_and_imports_match_them_by_title(tagProjects):
    mapper, (projectA, projectB), protocols = tagProjects
    good = mapper.insertProtocolTag(projectA, {"id": "g-" + uuid4().hex, "title": "Good", "color": "#22c55e"})["id"]
    mapper.setProtocolTagIdsByProtocolDbId(projectA, protocols[(projectA, 2)], [good])
    mapper.copyProtocolTagAssignments(projectA, protocols[(projectA, 2)], protocols[(projectA, 3)])
    assert mapper.getProjectProtocolTagIdsByProtocolId(projectA) == {"2": [good], "3": [good]}

    exported = mapper.getProtocolTagsByProtocolId(projectA, ["2", "3"])
    assert [tag["title"] for tag in exported["2"]] == ["Good"]

    # Into project B: the title is created there once and reused.
    created = mapper.ensureProtocolTag(projectB, "Good", color="#22c55e")
    assert mapper.ensureProtocolTag(projectB, "GOOD") == created != good
    mapper.addProtocolTagAssignments(projectB, protocols[(projectB, 2)], [created, good])
    assert mapper.getProjectProtocolTagIdsByProtocolId(projectB) == {"2": [created]}
