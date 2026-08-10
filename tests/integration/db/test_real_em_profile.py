# ******************************************************************************
# *
# * Authors:     Yunior C. Fonseca Reyna
# *
# * Unidad de  Bioinformatica of Centro Nacional de Biotecnologia , CSIC
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 3 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************
from uuid import uuid4

from pwem.objects import Acquisition, CTFModel, Particle, SetOfParticles

from app.backend.mapper.postgresql import PostgresqlDb, PostgresqlFlatMapper
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper
from app.backend.runtime.postgresql_runtime_set_factory import PostgresqlRuntimeSetFactory


class ParentProtocolStub:
    def __init__(self, protocolId):
        self.protocolId = int(protocolId)

    def getObjId(self):
        return self.protocolId


def _openPostgresqlIntegrationDb(postgresqlMigratedEnv):
    return PostgresqlDb(
        dbName=postgresqlMigratedEnv["databaseName"],
        user=postgresqlMigratedEnv["databaseUser"],
        password=postgresqlMigratedEnv["databasePass"],
        host=postgresqlMigratedEnv["postgresHost"],
        port=postgresqlMigratedEnv["postgresPort"],
    )


def _loadRuntimeOutputInfo(setMapper, projectId, protocolDbId, outputName):
    storedSet = setMapper.getStoredSet(
        projectId=projectId,
        protocolDbId=protocolDbId,
        outputName=outputName,
    )

    assert storedSet is not None

    objectTree = setMapper.getStoredObjectTree(
        projectId=projectId,
        protocolDbId=protocolDbId,
        outputName=outputName,
    )

    rootObject = next(
        row
        for row in objectTree
        if row["path"] == outputName
    )

    return {
        "setId": int(storedSet["id"]),
        "rootObjectId": int(storedSet["objectId"]),
        "runtimeObjectId": int(rootObject["scipionObjId"]),
        "projectId": projectId,
        "protocolDbId": protocolDbId,
        "outputName": outputName,
        "setClassName": storedSet["setClassName"],
        "itemClassName": storedSet["itemClassName"],
        "properties": storedSet["properties"],
    }


def _buildParticleWithMetadata(itemId, index, fileName):
    particle = Particle()

    particle.setObjId(
        itemId
    )

    particle.setLocation(
        index,
        fileName,
    )

    ctf = CTFModel()

    ctf.setDefocusU(
        15000.0
    )

    ctf.setDefocusV(
        14000.0
    )

    ctf.setDefocusAngle(
        25.0
    )

    particle.setCTF(
        ctf
    )

    acquisition = Acquisition()

    acquisition.setMagnification(
        100000.0
    )

    acquisition.setVoltage(
        300.0
    )

    acquisition.setSphericalAberration(
        2.7
    )

    acquisition.setAmplitudeContrast(
        0.1
    )

    particle.setAcquisition(
        acquisition
    )

    return particle


def test_RealSetOfParticlesPersistsAndHydratesFromPostgresql(
        postgresqlIntegrationDb,
        postgresqlMigratedEnv,
        tmp_path,
):
    writerMapper = PostgresqlFlatMapper(
        postgresqlIntegrationDb
    )

    suffix = uuid4().hex

    userId = None
    projectId = None
    readerDb = None
    observerDb = None
    sourceSet = None
    runtimeSet = None
    observerRuntimeSet = None

    try:
        userId = writerMapper.insertUser(
            email="postgresql-real-em-%s@example.com" % suffix,
            hashedPassword="integration-test",
            firstName="PostgreSQL",
            lastName="Real EM",
            institution=None,
            role="user",
            isActive=True,
            isVerified=True,
            verificationCode="integration-test",
        )

        projectId = writerMapper.insertProject(
            ownerId=userId,
            name="PostgreSQL real EM %s" % suffix,
            description="Real SetOfParticles PostgreSQL integration test.",
            status="active",
        )

        protocolId = 2

        protocolDbId = writerMapper.saveProtocol(
            {
                "info": {
                    "protocolId": protocolId,
                    "projectId": projectId,
                    "protocolClassName": "IntegrationRealEmProtocol",
                    "status": "finished",
                },
                "values": {},
                "parentIds": [],
                "childIds": [],
            }
        )

        sourceSqlite = (
            tmp_path
            / "source-particles.sqlite"
        )

        sourceSet = SetOfParticles(
            filename=str(
                sourceSqlite
            )
        )

        sourceSet.setObjId(
            1_500_001
        )

        sourceSet.setSamplingRate(
            1.25
        )

        firstParticle = _buildParticleWithMetadata(
            itemId=1,
            index=1,
            fileName="particles_01.mrcs",
        )

        secondParticle = _buildParticleWithMetadata(
            itemId=2,
            index=2,
            fileName="particles_02.mrcs",
        )

        sourceSet.append(
            firstParticle
        )

        sourceSet.append(
            secondParticle
        )

        sourceSet.write()

        assert sourceSet.getSize() == 2
        assert sourceSet.getSamplingRate() == 1.25

        outputName = "outputParticles"

        setMapper = ScipionSetPostgresqlMapper(
            postgresqlIntegrationDb
        )

        storeResult = setMapper.storeSet(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName=outputName,
            scipionSet=sourceSet,
        )

        assert storeResult["itemsCount"] == 2
        assert storeResult["maxItemId"] == 2
        assert storeResult["runtimeObjectId"] == 1_500_001
        assert storeResult["setClassName"] == "SetOfParticles"
        assert storeResult["itemClassName"] == "Particle"

        sourceSet.close()
        sourceSet = None

        readerDb = _openPostgresqlIntegrationDb(
            postgresqlMigratedEnv
        )

        readerSetMapper = ScipionSetPostgresqlMapper(
            readerDb
        )

        storedSet = readerSetMapper.getStoredSet(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName=outputName,
        )

        assert storedSet is not None
        assert storedSet["setClassName"] == "SetOfParticles"
        assert storedSet["itemClassName"] == "Particle"
        assert len(storedSet["items"]) == 2

        outputInfo = _loadRuntimeOutputInfo(
            setMapper=readerSetMapper,
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName=outputName,
        )

        runtimeSetFactory = PostgresqlRuntimeSetFactory()

        runtimeSet = runtimeSetFactory.build(
            db=readerDb,
            parent=ParentProtocolStub(
                protocolId
            ),
            outputName=outputName,
            outputInfo=outputInfo,
            classes={
                "SetOfParticles": SetOfParticles,
                "Particle": Particle,
                "CTFModel": CTFModel,
                "Acquisition": Acquisition,
            },
            cache=False,
        )

        assert runtimeSet is not None
        assert isinstance(
            runtimeSet,
            SetOfParticles,
        )

        assert runtimeSet.isPostgresqlRuntimeOutput()
        assert runtimeSet.getClass() is SetOfParticles
        assert runtimeSet.getObjId() == 1_500_001
        assert runtimeSet.getSize() == 2
        assert runtimeSet.getSamplingRate() == 1.25

        runtimeParticles = [
            {
                "id": particle.getObjId(),
                "index": particle.getIndex(),
                "fileName": particle.getFileName(),
                "hasCTF": particle.hasCTF(),
                "defocusU": (
                    particle.getCTF().getDefocusU()
                    if particle.hasCTF()
                    else None
                ),
                "defocusV": (
                    particle.getCTF().getDefocusV()
                    if particle.hasCTF()
                    else None
                ),
                "defocusAngle": (
                    particle.getCTF().getDefocusAngle()
                    if particle.hasCTF()
                    else None
                ),
                "hasAcquisition": particle.hasAcquisition(),
                "voltage": (
                    particle.getAcquisition().getVoltage()
                    if particle.hasAcquisition()
                    else None
                ),
                "magnification": (
                    particle.getAcquisition().getMagnification()
                    if particle.hasAcquisition()
                    else None
                ),
                "sphericalAberration": (
                    particle.getAcquisition().getSphericalAberration()
                    if particle.hasAcquisition()
                    else None
                ),
                "amplitudeContrast": (
                    particle.getAcquisition().getAmplitudeContrast()
                    if particle.hasAcquisition()
                    else None
                ),
            }
            for particle in runtimeSet.iterItems(
                orderBy="id",
                direction="ASC",
            )
        ]

        assert runtimeParticles == [
            {
                "id": 1,
                "index": 1,
                "fileName": "particles_01.mrcs",
                "hasCTF": True,
                "defocusU": 15000.0,
                "defocusV": 14000.0,
                "defocusAngle": 25.0,
                "hasAcquisition": True,
                "voltage": 300.0,
                "magnification": 100000.0,
                "sphericalAberration": 2.7,
                "amplitudeContrast": 0.1,
            },
            {
                "id": 2,
                "index": 2,
                "fileName": "particles_02.mrcs",
                "hasCTF": True,
                "defocusU": 15000.0,
                "defocusV": 14000.0,
                "defocusAngle": 25.0,
                "hasAcquisition": True,
                "voltage": 300.0,
                "magnification": 100000.0,
                "sphericalAberration": 2.7,
                "amplitudeContrast": 0.1,
            },
        ]

        runtimeSet.close()
        runtimeSet = None

        readerDb.close()
        readerDb = None

        # --------------------------------------------------------------
        # Third independent connection:
        # PostgreSQL remains sufficient to reconstruct the native Set.
        # --------------------------------------------------------------

        observerDb = _openPostgresqlIntegrationDb(
            postgresqlMigratedEnv
        )

        observerSetMapper = ScipionSetPostgresqlMapper(
            observerDb
        )

        observerOutputInfo = _loadRuntimeOutputInfo(
            setMapper=observerSetMapper,
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName=outputName,
        )

        observerRuntimeSetFactory = PostgresqlRuntimeSetFactory()

        observerRuntimeSet = observerRuntimeSetFactory.build(
            db=observerDb,
            parent=ParentProtocolStub(
                protocolId
            ),
            outputName=outputName,
            outputInfo=observerOutputInfo,
            classes={
                "SetOfParticles": SetOfParticles,
                "Particle": Particle,
                "CTFModel": CTFModel,
                "Acquisition": Acquisition,
            },
            cache=False,
        )

        assert isinstance(
            observerRuntimeSet,
            SetOfParticles,
        )

        assert observerRuntimeSet.getObjId() == 1_500_001
        assert observerRuntimeSet.getSize() == 2
        assert observerRuntimeSet.getSamplingRate() == 1.25

        observerParticles = [
            (
                particle.getObjId(),
                particle.getIndex(),
                particle.getFileName(),
                particle.hasCTF(),
                particle.hasAcquisition(),
            )
            for particle in observerRuntimeSet.iterItems(
                orderBy="id",
                direction="ASC",
            )
        ]

        assert observerParticles == [
            (
                1,
                1,
                "particles_01.mrcs",
                True,
                True,
            ),
            (
                2,
                2,
                "particles_02.mrcs",
                True,
                True,
            ),
        ]

    finally:
        if observerRuntimeSet is not None:
            observerRuntimeSet.close()

        if runtimeSet is not None:
            runtimeSet.close()

        if sourceSet is not None:
            sourceSet.close()

        if observerDb is not None:
            observerDb.close()

        if readerDb is not None:
            readerDb.close()

        if projectId is not None and userId is not None:
            writerMapper.deleteProject(
                projectId=projectId,
                ownerId=userId,
            )

        if userId is not None:
            postgresqlIntegrationDb.execute(
                "DELETE FROM users WHERE id = %s",
                (
                    userId,
                ),
            )