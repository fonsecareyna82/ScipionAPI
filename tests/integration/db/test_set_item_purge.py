"""Deleting a Set leaves its items to the background purge, whatever deletes it."""
from uuid import uuid4

import pytest
from pwem import objects as emobj
from pyworkflow.protocol import STATUS_FINISHED

from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.mapper.scipion_object_mapper import ScipionObjectPostgresqlMapper
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper
from app.backend.runtime.postgresql_runtime_set_factory import PostgresqlRuntimeSetFactory
from app.backend.utils.set_item_purge import purgePendingSetItems

CLASSES = {name: cls for name, cls in vars(emobj).items() if isinstance(cls, type)}
PARTICLES = 50


class ParentProtocolStub:
    def __init__(self, protocolId):
        self.protocolId = protocolId

    def getObjId(self):
        return self.protocolId


@pytest.fixture
def purgeProject(postgresqlIntegrationDb, postgresqlMigratedEnv):
    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    # Leftovers of other tests must not be counted here
    purgePendingSetItems(db)
    userId = flat.insertUser(email="set-item-purge-%s@example.com" % uuid4().hex, hashedPassword="test",
                             firstName="Set", lastName="Purge", institution=None, role="user",
                             isActive=True, isVerified=True, verificationCode="")
    projectId = flat.insertProject(ownerId=userId, name="/tmp/set-item-purge-%s" % uuid4().hex,
                                   description="Set item purge")
    try:
        yield db, flat, projectId, userId
    finally:
        flat.deleteProject(projectId=projectId, ownerId=userId)
        purgePendingSetItems(db)
        db.execute("DELETE FROM users WHERE id = %s", (userId,))


def _protocolWithParticles(db, flat, projectId, protocolId):
    protocolDbId = flat.saveProtocol({
        "info": {"protocolId": protocolId, "projectId": projectId, "protocolClassName": "PurgeProtocol",
                 "status": STATUS_FINISHED},
        "values": {}, "parentIds": [], "childIds": []})
    particles = emobj.SetOfParticles()
    particles.setSamplingRate(1.0)
    particles.setObjId(4_000_000 + protocolId)
    setMapper = ScipionSetPostgresqlMapper(db)
    info = setMapper.reserveRuntimeSet(projectId=projectId, protocolDbId=protocolDbId,
                                       outputName="outputParticles", scipionSet=particles)
    output = PostgresqlRuntimeSetFactory().build(db=db, parent=ParentProtocolStub(protocolId),
                                                 outputName="outputParticles", outputInfo=info,
                                                 classes=CLASSES, cache=False)
    output.enablePostgresqlWrite()
    for particleId in range(1, PARTICLES + 1):
        particle = emobj.Particle()
        particle.setObjId(particleId)
        particle.setLocation(particleId, "particles.mrcs")
        output.append(particle)
    output.write()
    setMapper.finalizeRuntimeSetOutput(projectId=projectId, protocolDbId=protocolDbId,
                                       outputName="outputParticles", scipionSet=output)
    output.close()
    return protocolDbId, int(info["setId"])


def _itemsOf(db, setId):
    row = db.fetchOne("""
        SELECT (SELECT COUNT(*) FROM scipion_set_items WHERE "setId" = %s) AS "setItems",
               (SELECT COUNT(*) FROM scipion_set_table_items i
                 WHERE i."tableId" IN (SELECT "tableId" FROM scipion_set_item_purges WHERE "tableId" IS NOT NULL)
                    OR i."tableId" IN (SELECT id FROM scipion_set_tables WHERE "setId" = %s)) AS "tableItems",
               (SELECT COUNT(*) FROM scipion_set_item_purges WHERE "setId" = %s) AS queued
    """, (setId, setId, setId))
    return {key: int(value) for key, value in row.items()}


def test_DeletingTheOutputsOfAProtocolQueuesItsItemsAndThePurgeRemovesThem(purgeProject):
    db, flat, projectId, _ = purgeProject
    protocolDbId, setId = _protocolWithParticles(db, flat, projectId, 2)

    ScipionObjectPostgresqlMapper(db).deleteProtocolOutputMetadata(projectId=projectId, protocolDbId=protocolDbId)

    assert db.fetchOne("SELECT COUNT(*) AS n FROM scipion_sets WHERE id = %s", (setId,))["n"] == 0
    left = _itemsOf(db, setId)
    assert left == {"setItems": PARTICLES, "tableItems": PARTICLES, "queued": 1}

    assert purgePendingSetItems(db, batchSize=7) == 2 * PARTICLES
    assert _itemsOf(db, setId) == {"setItems": 0, "tableItems": 0, "queued": 0}
    assert db.fetchOne("SELECT COUNT(*) AS n FROM scipion_set_item_purges")["n"] == 0


def test_DeletingAProtocolOrItsProjectQueuesTheItemsOfItsSets(purgeProject):
    db, flat, projectId, userId = purgeProject
    firstDbId, firstSetId = _protocolWithParticles(db, flat, projectId, 2)
    _, secondSetId = _protocolWithParticles(db, flat, projectId, 3)

    # A protocol's Sets go through the foreign-key cascade, the project's too
    db.execute('DELETE FROM protocols WHERE id = %s', (firstDbId,))
    assert _itemsOf(db, firstSetId)["queued"] == 1
    flat.deleteProject(projectId=projectId, ownerId=userId)
    assert _itemsOf(db, secondSetId)["queued"] == 1

    assert purgePendingSetItems(db) == 4 * PARTICLES
    assert _itemsOf(db, firstSetId)["setItems"] == 0 and _itemsOf(db, secondSetId)["setItems"] == 0


def test_OnlyOneProcessPurgesAtATime(purgeProject, postgresqlMigratedEnv):
    from app.backend.mapper.postgresql import PostgresqlDb
    from app.backend.mapper.set_item_purge_mapper import SetItemPurgePostgresqlMapper

    db, flat, projectId, _ = purgeProject
    protocolDbId, setId = _protocolWithParticles(db, flat, projectId, 2)
    ScipionObjectPostgresqlMapper(db).deleteProtocolOutputMetadata(projectId=projectId, protocolDbId=protocolDbId)
    env = postgresqlMigratedEnv
    other = PostgresqlDb(dbName=env["databaseName"], user=env["databaseUser"], password=env["databasePass"],
                         host=env["postgresHost"], port=int(env["postgresPort"]))
    otherMapper = SetItemPurgePostgresqlMapper(other)
    try:
        assert otherMapper.tryLock()
        assert purgePendingSetItems(db) == 0
        assert _itemsOf(db, setId)["setItems"] == PARTICLES
    finally:
        otherMapper.unlock()
        other.close()
    assert purgePendingSetItems(db) == 2 * PARTICLES
