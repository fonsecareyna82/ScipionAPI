"""The projects' disk usage and the users' projects folders, against the migrated database."""
import time
from uuid import uuid4

import pytest

from app.backend.api.services import project_storage as storage
from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.mapper.storage_mapper import StoragePostgresqlMapper


def _user(db, email):
    return PostgresqlFlatMapper(db).insertUser(email=email, hashedPassword="test", firstName=email.split("@")[0],
                                               lastName="Test", institution=None, role="user", isActive=True,
                                               isVerified=True, verificationCode="")


@pytest.fixture
def lab(postgresqlIntegrationDb, postgresqlMigratedEnv, tmp_path):
    """Two users in a group, a third alone, and their projects' folders; all removed after the test."""
    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    tag = uuid4().hex[:8]
    root = tmp_path / "projects"
    root.mkdir()
    ana, marta, luis = (_user(db, "%s-%s@cnb.csic.es" % (name, tag)) for name in ("ana", "marta", "luis"))
    group = db.fetchOne("INSERT INTO user_groups (name) VALUES (%s) RETURNING id", ("Lab %s" % tag,))
    for userId, role in ((ana, "pi"), (marta, "member")):
        db.execute('INSERT INTO user_group_members ("groupId", "userId", "groupRole") VALUES (%s, %s, %s)',
                   (group["id"], userId, role))
    projects = {}
    for owner, name, size in ((ana, "Apoferritin", 5000), (marta, "Ribosome", 90000), (marta, "Empty", 0),
                              (luis, "Gone", None)):
        path = root / str(owner) / name
        if size is not None:
            (path / "Runs").mkdir(parents=True)
            (path / "Runs" / "movie.mrc").write_bytes(b"x" * size)
        projects[name] = flat.insertProject(ownerId=owner, name=str(path), description="", status="active")
    try:
        yield db, root, {"ana": ana, "marta": marta, "luis": luis}, group["id"], projects
    finally:
        db.execute("DELETE FROM projects WHERE id = ANY(%s)", (list(projects.values()),))
        db.execute("DELETE FROM user_groups WHERE id = %s", (group["id"],))
        db.execute("DELETE FROM users WHERE id = ANY(%s)", ([ana, marta, luis],))


def _measureAll(db, root, projectIds):
    """Run the measurer until these projects are measured (the test database may hold others)."""
    storage.requestMeasure(db, projectIds)
    for _ in range(500):
        pending = [project for project in storage.usageReport(db, root)["projects"]
                   if project["id"] in projectIds and (project["requested"] or project["measuredAt"] is None)]
        if not pending:
            return
        if storage.measureNext(db, root, sleep=lambda seconds: None) is None:
            # Another measurer of this process (started by an earlier test) may hold the turn for a moment
            time.sleep(0.05)
    raise AssertionError("The projects were not measured")


def test_TheMeasurerMeasuresEachProjectAndTheReportSumsThemByUserAndGroup(lab):
    db, root, users, groupId, projects = lab
    _measureAll(db, root, list(projects.values()))

    report = storage.usageReport(db, root)

    mine = {project["id"]: project for project in report["projects"] if project["id"] in projects.values()}
    ribosome = mine[projects["Ribosome"]]
    assert ribosome["totalBytes"] >= 90000 and ribosome["runsBytes"] == ribosome["totalBytes"]
    assert ribosome["location"] == "managed" and ribosome["files"] == 1 and not ribosome["requested"]
    assert mine[projects["Empty"]]["totalBytes"] == 0
    assert mine[projects["Gone"]]["error"] == "The project folder is not there"

    byUser = {user["userId"]: user for user in report["users"]}
    assert byUser[users["marta"]]["totalBytes"] == ribosome["totalBytes"]
    assert byUser[users["marta"]]["projects"] == 2
    assert byUser[users["luis"]]["measured"] == 0 and byUser[users["luis"]]["totalBytes"] == 0
    group = next(group for group in report["groups"] if group["groupId"] == groupId)
    assert group["totalBytes"] == ribosome["totalBytes"] + mine[projects["Apoferritin"]]["totalBytes"]
    assert group["members"] == 2 and group["projects"] == 3
    assert report["disk"]["freeBytes"] > 0

    # What the project list reads
    measures = StoragePostgresqlMapper(db).usageOfProjects([projects["Ribosome"]])
    assert measures[projects["Ribosome"]]["totalBytes"] == ribosome["totalBytes"]


def test_AMeasureAskedForIsPendingUntilItIsMade(lab):
    db, root, users, groupId, projects = lab
    _measureAll(db, root, list(projects.values()))
    (root / str(users["ana"]) / "Apoferritin" / "Uploads").mkdir()
    (root / str(users["ana"]) / "Apoferritin" / "Uploads" / "gain.mrc").write_bytes(b"x" * 40000)

    storage.requestMeasure(db, [projects["Apoferritin"]])
    asked = next(project for project in storage.usageReport(db, root)["projects"]
                 if project["id"] == projects["Apoferritin"])
    assert asked["requested"] and asked["uploadsBytes"] == 0

    _measureAll(db, root, [projects["Apoferritin"]])
    measured = next(project for project in storage.usageReport(db, root)["projects"]
                    if project["id"] == projects["Apoferritin"])
    assert not measured["requested"] and measured["uploadsBytes"] >= 40000


def test_EachUserGetsAFolderOfTheirOwnNamedAfterTheirEmail(lab, tmp_path):
    db, root, users, groupId, projects = lab
    tag = uuid4().hex[:8]
    first = _user(db, "sofia%s@cnb.csic.es" % tag)
    # Another user with the same name before the @, and a project folder of that name made before
    second = _user(db, "sofia%s@csic.es" % tag)
    third = _user(db, "sofia%s@uam.es" % tag)
    (root / ("sofia%s_2" % tag)).mkdir()
    try:
        folder = storage.userProjectsFolder(db, {"id": first, "email": "sofia%s@cnb.csic.es" % tag}, root)
        assert folder == root / ("sofia%s" % tag) and folder.is_dir()
        # Kept afterwards, even when the email changes
        assert storage.userProjectsFolder(db, {"id": first, "email": "other@cnb.csic.es"}, root) == folder

        assert storage.userProjectsFolder(db, {"id": second, "email": "sofia%s@csic.es" % tag}, root) \
            == root / ("sofia%s_3" % tag)
        assert storage.userProjectsFolder(db, {"id": third, "email": "sofia%s@uam.es" % tag}, root) \
            == root / ("sofia%s_4" % tag)
    finally:
        db.execute("DELETE FROM users WHERE id = ANY(%s)", ([first, second, third],))
