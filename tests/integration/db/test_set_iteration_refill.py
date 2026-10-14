"""Opt-in Set iteration follows native Scipion template semantics."""
from uuid import uuid4

import pytest
from pwem import objects as emobj
from pyworkflow.object import Object

from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper
from app.backend.runtime import postgresql_runtime_set_factory as factoryModule
from app.backend.runtime.postgresql_runtime_set_factory import (
    SET_ITEM_TEMPLATE_ENV,
    PostgresqlRuntimeSetFactory,
)

CLASSES = {name: cls for name, cls in vars(emobj).items() if isinstance(cls, type)}


@pytest.fixture
def outputContext(postgresqlIntegrationDb, postgresqlMigratedEnv):
    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    userId = flat.insertUser(
        email="iteration-refill-%s@example.com" % uuid4().hex, hashedPassword="test-password",
        firstName="Iteration", lastName="Refill", institution=None, role="user",
        isActive=True, isVerified=True, verificationCode="")
    projectId = flat.insertProject(ownerId=userId, name="Iteration refill", description="Test")
    protocolDbId = flat.saveProtocol({"info": dict(protocolId=2, projectId=projectId,
        protocolClassName="IterationRefillTestProtocol", status="running"),
        "values": {}, "parentIds": [], "childIds": []})
    parent = Object()
    parent.setObjId(2)
    opened = []

    def build(info, writable=False):
        result = PostgresqlRuntimeSetFactory().build(
            db=db, parent=parent, outputName=info["outputName"],
            outputInfo=info, classes=CLASSES, cache=False)
        opened.append(result)
        if writable:
            result.enablePostgresqlWrite()
        return result

    try:
        yield dict(db=db, projectId=projectId, protocolDbId=protocolDbId, build=build)
    finally:
        for output in reversed(opened):
            output.close()
        flat.deleteProject(projectId=projectId, ownerId=userId)
        db.execute("DELETE FROM users WHERE id = %s", (userId,))


def _storeParticles(ctx, tmp_path):
    mapper = ScipionSetPostgresqlMapper(ctx["db"])
    particles = emobj.SetOfParticles()
    particles.setSamplingRate(1.25)
    particles.setObjId(1_000_101)
    info = mapper.reserveRuntimeSet(projectId=ctx["projectId"], protocolDbId=ctx["protocolDbId"],
                                    outputName="outputParticles", scipionSet=particles)
    output = ctx["build"](info, writable=True)
    stack = str(tmp_path / "particles.mrcs")
    for itemId in range(1, 7):
        item = emobj.Particle()
        item.setObjId(itemId)
        item.setLocation(itemId, stack)
        item.setSamplingRate(1.25)
        if itemId != 4:
            ctf = emobj.CTFModel()
            ctf.setStandardDefocus(10000.0 + itemId, 9000.0 + itemId, 30.0)
            item.setCTF(ctf)
        output.append(item)
    output.write()
    result = mapper.finalizeRuntimeSetOutput(projectId=ctx["projectId"], protocolDbId=ctx["protocolDbId"],
                                             outputName="outputParticles", scipionSet=output)
    return info, result, stack


def test_IterationBuildsFreshItemsUnlessTemplateIsEnabled(outputContext, tmp_path, monkeypatch):
    monkeypatch.delenv(SET_ITEM_TEMPLATE_ENV, raising=False)
    info, result, stack = _storeParticles(outputContext, tmp_path)
    reopened = outputContext["build"](dict(info, properties=result["properties"]))
    kept = list(reopened.iterItems())
    assert len({id(item) for item in kept}) == 6
    assert [item.getObjId() for item in kept] == list(range(1, 7))
    assert [item.getLocation() for item in kept] == [(itemId, stack) for itemId in range(1, 7)]


def test_NativeSwitchDisablesTheOptInTemplate(monkeypatch):
    monkeypatch.setenv(SET_ITEM_TEMPLATE_ENV, "1")
    assert factoryModule.isSetItemTemplateEnabled()
    monkeypatch.setattr(factoryModule.ScipionConfig, "SCIPION_MAPPER_USE_TEMPLATE", False)
    assert not factoryModule.isSetItemTemplateEnabled()
    monkeypatch.setenv(SET_ITEM_TEMPLATE_ENV, "0")
    monkeypatch.setattr(factoryModule.ScipionConfig, "SCIPION_MAPPER_USE_TEMPLATE", True)
    assert not factoryModule.isSetItemTemplateEnabled()


def test_IterationRefillsLikeScipionAndCopiesWhenAsked(outputContext, tmp_path, monkeypatch):
    monkeypatch.setenv(SET_ITEM_TEMPLATE_ENV, "1")
    ctx = outputContext
    info, result, stack = _storeParticles(ctx, tmp_path)
    reopened = ctx["build"](dict(info, properties=result["properties"]))

    seen = [(id(item), item.getObjId(), item.hasCTF(),
             item.getCTF().getDefocusU() if item.hasCTF() else None, item.getLocation())
            for item in reopened.iterItems()]

    assert [row[1:] for row in seen] == [
        (itemId, itemId != 4, 10000.0 + itemId if itemId != 4 else None, (itemId, stack))
        for itemId in range(1, 7)
    ]
    # Same-shape rows share one object, as native Scipion iteration does;
    # the CTF-less row breaks the run and gets its own object.
    identities = [row[0] for row in seen]
    assert identities[0] == identities[1] == identities[2]
    assert identities[3] != identities[2]
    assert identities[4] != identities[3]

    copies = list(reopened.iterItems(iterate=False))
    assert len({id(item) for item in copies}) == 6
    assert [item.getObjId() for item in copies] == list(range(1, 7))
    assert [item.hasCTF() for item in copies] == [itemId != 4 for itemId in range(1, 7)]
