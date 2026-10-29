"""A streaming child sees its input Set's items only once the producer has written the Set."""
from uuid import uuid4

import tomo.objects as tomoobj
from pwem import objects as emobj

from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper
from app.backend.runtime.postgresql_runtime_set_factory import PostgresqlRuntimeSetFactory
from app.backend.runtime.protocol_graph_repository import ProtocolGraphRepository

CLASSES = {name: cls for module in (emobj, tomoobj) for name, cls in vars(module).items() if isinstance(cls, type)}


class ParentProtocolStub:
    def __init__(self, protocolId):
        self.protocolId = protocolId

    def getObjId(self):
        return self.protocolId


class MapperStub:
    def __init__(self, db):
        self.db = db


def test_ATiltSeriesAppendedButNotWrittenIsNotPublishedYet(postgresqlIntegrationDb, postgresqlMigratedEnv):
    db = postgresqlIntegrationDb
    flat = PostgresqlFlatMapper(db)
    userId = flat.insertUser(email="set-publication-%s@example.com" % uuid4().hex, hashedPassword="test",
                             firstName="Set", lastName="Publication", institution=None, role="user",
                             isActive=True, isVerified=True, verificationCode="")
    projectId = flat.insertProject(ownerId=userId, name="/tmp/set-publication-%s" % uuid4().hex,
                                   description="Set publication")
    try:
        protocolDbId = flat.saveProtocol({
            "info": {"protocolId": 2, "projectId": projectId, "protocolClassName": "PublicationProtocol",
                     "status": "running"},
            "values": {}, "parentIds": [], "childIds": []})
        tiltSeries = tomoobj.SetOfTiltSeries()
        tiltSeries.setSamplingRate(1.0)
        tiltSeries.setObjId(5_000_000)
        tiltSeries.setStreamState(tiltSeries.STREAM_OPEN)
        setMapper = ScipionSetPostgresqlMapper(db)
        info = setMapper.reserveRuntimeSet(projectId=projectId, protocolDbId=protocolDbId,
                                           outputName="TiltSeries", scipionSet=tiltSeries)
        output = PostgresqlRuntimeSetFactory().build(db=db, parent=ParentProtocolStub(2), outputName="TiltSeries",
                                                     outputInfo=info, classes=CLASSES, cache=False)
        output.enablePostgresqlWrite()
        setMapper.finalizeRuntimeSetOutput(projectId=projectId, protocolDbId=protocolDbId,
                                           outputName="TiltSeries", scipionSet=output)

        def published():
            outputInfo = ProtocolGraphRepository().getPostgresqlRuntimeOutputInfo(
                mapper=MapperStub(db), projectId=projectId, parentProtocolDbId=protocolDbId, outputName="TiltSeries")
            return (outputInfo["itemsCount"], outputInfo["publishedItemsCount"],
                    outputInfo["properties"].get("_hasOddEven"))

        # As Warp does: the tilt series is appended first, its tilt images and the Set's attributes come later
        series = tomoobj.TiltSeries(tsId="TS_1")
        output.append(series)
        for index in range(3):
            image = tomoobj.TiltImage()
            image.setLocation(index + 1, "TS_1.mrcs")
            image.setOddEven(["TS_1_odd.mrcs", "TS_1_even.mrcs"])
            series.append(image)
        series.write()
        assert published() == (1, 0, False)

        output.update(series)
        output.write()
        assert published() == (1, 1, True)
        output.close()
    finally:
        flat.deleteProject(projectId=projectId, ownerId=userId)
        db.execute("DELETE FROM users WHERE id = %s", (userId,))
