"""Which project and protocols a scratch folder belongs to, against the migrated database."""
from uuid import uuid4

from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.mapper.scratch_mapper import ScratchPostgresqlMapper


def test_TheProjectsOfAFolderNameAreFoundWithTheirProtocols(postgresqlIntegrationDb, postgresqlMigratedEnv, tmp_path):
    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    name = "Krios_%s" % uuid4().hex[:8]
    userId = flat.insertUser(email="scratch-%s@example.org" % uuid4().hex, hashedPassword="x", firstName="A",
                             lastName="B", institution=None, role="user", isActive=True, isVerified=True,
                             verificationCode="")
    projectId = flat.insertProject(ownerId=userId, name=str(tmp_path / "user" / name) + "/")
    emptyId = flat.insertProject(ownerId=userId, name=str(tmp_path / ("Empty_" + name)))
    db.execute('INSERT INTO protocols ("protocolId", "projectId", "protocolClassName", params, status) '
               "VALUES (%s, %s, %s, %s, %s)", (13, projectId, "ProtRefine3D", "{}", "Failed"))
    try:
        rows = ScratchPostgresqlMapper(db).protocolsOfProjects([name, "Empty_" + name, "Nobody"])

        assert {(row["shortName"], row["protocolId"] and int(row["protocolId"]), row["status"]) for row in rows} == {
            (name, 13, "failed"), ("Empty_" + name, None, "")}
    finally:
        db.execute("DELETE FROM projects WHERE id = ANY(%s)", ([projectId, emptyId],))
        db.execute("DELETE FROM users WHERE id = %s", (userId,))
