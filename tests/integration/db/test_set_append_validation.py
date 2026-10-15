"""Runtime Sets run the admission check a Set defines for its new items, as native inserts do."""
from uuid import uuid4

import pytest
from pwem import objects as emobj
from pyworkflow.object import Object

from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper
from app.backend.runtime.postgresql_runtime_set_factory import PostgresqlRuntimeSetFactory


class SetOfUniqueMicParticles(emobj.SetOfParticles):
    """Refuses two particles of the same micrograph, the way tomo Sets refuse a repeated tsId."""

    def _validateNewItem(self, item):
        seen = self.__dict__.setdefault('_seenMicIds', set())
        if item.getMicId() in seen:
            raise ValueError('Duplicated micrograph %s' % item.getMicId())
        seen.add(item.getMicId())


CLASSES = dict({name: cls for name, cls in vars(emobj).items() if isinstance(cls, type)},
               SetOfUniqueMicParticles=SetOfUniqueMicParticles)


@pytest.fixture
def writableSet(postgresqlIntegrationDb, postgresqlMigratedEnv):
    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    userId = flat.insertUser(
        email="set-append-validation-%s@example.com" % uuid4().hex, hashedPassword="test-password",
        firstName="Set", lastName="Validation", institution=None, role="user",
        isActive=True, isVerified=True, verificationCode="")
    projectId = flat.insertProject(ownerId=userId, name="Set append validation", description="Test")
    protocolDbId = flat.saveProtocol({"info": dict(protocolId=2, projectId=projectId,
        protocolClassName="SetAppendValidationProtocol", status="running"),
        "values": {}, "parentIds": [], "childIds": []})
    parent = Object()
    parent.setObjId(2)
    nativeSet = SetOfUniqueMicParticles()
    nativeSet.setSamplingRate(1.0)
    nativeSet.setObjId(1_000_301)
    info = ScipionSetPostgresqlMapper(db).reserveRuntimeSet(
        projectId=projectId, protocolDbId=protocolDbId, outputName="output1000301", scipionSet=nativeSet)
    runtimeSet = PostgresqlRuntimeSetFactory().build(
        db=db, parent=parent, outputName=info["outputName"], outputInfo=info, classes=CLASSES, cache=False)
    runtimeSet.enablePostgresqlWrite()
    try:
        yield runtimeSet
    finally:
        runtimeSet.close()
        flat.deleteProject(projectId=projectId, ownerId=userId)
        db.execute("DELETE FROM users WHERE id = %s", (userId,))


def _particle(micId):
    particle = emobj.Particle()
    particle.setSamplingRate(1.0)
    particle.setMicId(micId)
    return particle


def test_AppendRefusesWhatTheSetRefuses(writableSet):
    writableSet.append(_particle(1))

    with pytest.raises(ValueError, match='Duplicated micrograph 1'):
        writableSet.append(_particle(1))

    writableSet.append(_particle(2))
    writableSet.write()
    assert writableSet.getSize() == 2
