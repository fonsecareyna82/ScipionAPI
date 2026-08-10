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

from pyworkflow.object import Float, Object, Set, String

from app.backend.mapper.postgresql import PostgresqlDb, PostgresqlFlatMapper
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper
from app.backend.runtime.postgresql_runtime_set_factory import PostgresqlRuntimeSetFactory


class ItemStub(Object):
    def __init__(self):
        super().__init__()
        self._score = Float()
        self._code = String()


class OutputSetStub(Set):
    ITEM_TYPE = ItemStub


class NestedSetStub(Set):
    ITEM_TYPE = ItemStub

    def __init__(self):
        super().__init__()
        self._name = String()


class ParentOutputSetStub(Set):
    ITEM_TYPE = NestedSetStub


class SourceNestedSetStub(NestedSetStub):
    def __init__(self, items):
        super().__init__()
        self._integrationItems = list(items)
        self._size.set(len(self._integrationItems))
        self._idCount = max((int(item.getObjId()) for item in self._integrationItems), default=0)

    def getClassName(self):
        return "NestedSetStub"

    def iterItems(self, iterate=False):
        return iter(self._integrationItems)

    def getSize(self):
        return len(self._integrationItems)

    def getFirstItem(self):
        return self._integrationItems[0] if self._integrationItems else None

    def getLastItem(self):
        return self._integrationItems[-1] if self._integrationItems else None

    def getMaxId(self):
        if not self._integrationItems:
            return 0

        return max(int(item.getObjId()) for item in self._integrationItems)

    def getFileName(self):
        return None


class SourceParentOutputSetStub(ParentOutputSetStub):
    def __init__(self, items):
        super().__init__()
        self._integrationItems = list(items)
        self._size.set(len(self._integrationItems))
        self._idCount = max((int(item.getObjId()) for item in self._integrationItems), default=0)

    def getClassName(self):
        return "ParentOutputSetStub"

    def iterItems(self, iterate=False):
        return iter(self._integrationItems)

    def getSize(self):
        return len(self._integrationItems)

    def getFirstItem(self):
        return self._integrationItems[0] if self._integrationItems else None

    def getLastItem(self):
        return self._integrationItems[-1] if self._integrationItems else None

    def getMaxId(self):
        if not self._integrationItems:
            return 0

        return max(int(item.getObjId()) for item in self._integrationItems)

    def getFileName(self):
        return None


class SourceOutputSetStub(Set):
    ITEM_TYPE = ItemStub

    def __init__(self, items):
        super().__init__()
        self._integrationItems = list(items)

    def getClassName(self):
        return "OutputSetStub"

    def getObjDict(self, includeClass=False):
        if includeClass:
            return {
                "self": (
                    "OutputSetStub",
                    None,
                ),
            }

        return {}

    def iterItems(self, iterate=False):
        return iter(self._integrationItems)

    def getSize(self):
        return len(self._integrationItems)

    def getFirstItem(self):
        return self._integrationItems[0] if self._integrationItems else None

    def getLastItem(self):
        return self._integrationItems[-1] if self._integrationItems else None

    def getMaxId(self):
        if not self._integrationItems:
            return 0

        return max(
            int(item.getObjId())
            for item in self._integrationItems
        )

    def getFileName(self):
        return None


class ParentProtocolStub:
    def __init__(self, protocolId):
        self.protocolId = int(protocolId)

    def getObjId(self):
        return self.protocolId


def _buildItem(
        itemId,
        score,
        code,
):
    item = ItemStub()

    if itemId is not None:
        item.setObjId(itemId)

    item._score.set(score)
    item._code.set(code)
    return item


def _openPostgresqlIntegrationDb(
        postgresqlMigratedEnv,
):
    return PostgresqlDb(
        dbName=postgresqlMigratedEnv["databaseName"],
        user=postgresqlMigratedEnv["databaseUser"],
        password=postgresqlMigratedEnv["databasePass"],
        host=postgresqlMigratedEnv["postgresHost"],
        port=postgresqlMigratedEnv["postgresPort"],
    )


def _loadRuntimeOutputInfo(
        setMapper,
        projectId,
        protocolDbId,
        outputName,
):
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


def test_SetAndItemsPersistAndHydrateAcrossPostgresqlConnections(
        postgresqlIntegrationDb,
        postgresqlMigratedEnv,
):
    writerMapper = PostgresqlFlatMapper(
        postgresqlIntegrationDb
    )

    suffix = uuid4().hex

    userId = None
    projectId = None
    readerDb = None
    runtimeSet = None

    try:
        userId = writerMapper.insertUser(
            email="postgresql-set-%s@example.com" % suffix,
            hashedPassword="integration-test",
            firstName="PostgreSQL",
            lastName="Set Integration",
            institution=None,
            role="user",
            isActive=True,
            isVerified=True,
            verificationCode="integration-test",
        )

        projectId = writerMapper.insertProject(
            ownerId=userId,
            name="PostgreSQL Set integration %s" % suffix,
            description="Runtime Set persistence integration test.",
            status="active",
        )

        protocolId = 2

        protocolDbId = writerMapper.saveProtocol(
            {
                "info": {
                    "protocolId": protocolId,
                    "projectId": projectId,
                    "protocolClassName": "IntegrationSetProtocol",
                    "status": "finished",
                },
                "values": {},
                "parentIds": [],
                "childIds": [],
            }
        )

        sourceItems = [
            _buildItem(
                itemId=1,
                score=0.25,
                code="ITEM_01",
            ),
            _buildItem(
                itemId=2,
                score=0.75,
                code="ITEM_02",
            ),
        ]

        sourceSet = SourceOutputSetStub(
            sourceItems
        )

        sourceSet.setObjId(
            1_000_001
        )

        setMapper = ScipionSetPostgresqlMapper(
            postgresqlIntegrationDb
        )

        storeResult = setMapper.storeSet(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName="outputItems",
            scipionSet=sourceSet,
        )

        assert storeResult["itemsCount"] == 2
        assert storeResult["maxItemId"] == 2
        assert storeResult["runtimeObjectId"] == 1_000_001
        assert storeResult["setClassName"] == "OutputSetStub"
        assert storeResult["itemClassName"] == "ItemStub"

        readerDb = _openPostgresqlIntegrationDb(
            postgresqlMigratedEnv
        )

        readerSetMapper = ScipionSetPostgresqlMapper(
            readerDb
        )

        storedSet = readerSetMapper.getStoredSet(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName="outputItems",
        )

        assert storedSet is not None
        assert storedSet["setClassName"] == "OutputSetStub"
        assert storedSet["itemClassName"] == "ItemStub"
        assert len(storedSet["items"]) == 2

        assert storedSet["items"][0]["scipionItemId"] == 1
        assert storedSet["items"][0]["values"]["_score"] == 0.25
        assert storedSet["items"][0]["values"]["_code"] == "ITEM_01"

        assert storedSet["items"][1]["scipionItemId"] == 2
        assert storedSet["items"][1]["values"]["_score"] == 0.75
        assert storedSet["items"][1]["values"]["_code"] == "ITEM_02"

        objectTree = readerSetMapper.getStoredObjectTree(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName="outputItems",
        )

        rootObject = next(
            row
            for row in objectTree
            if row["path"] == "outputItems"
        )

        outputInfo = {
            "setId": int(storedSet["id"]),
            "rootObjectId": int(storedSet["objectId"]),
            "runtimeObjectId": int(rootObject["scipionObjId"]),
            "projectId": projectId,
            "protocolDbId": protocolDbId,
            "outputName": "outputItems",
            "setClassName": storedSet["setClassName"],
            "itemClassName": storedSet["itemClassName"],
            "properties": storedSet["properties"],
        }

        runtimeSetFactory = PostgresqlRuntimeSetFactory()

        runtimeSet = runtimeSetFactory.build(
            db=readerDb,
            parent=ParentProtocolStub(
                protocolId
            ),
            outputName="outputItems",
            outputInfo=outputInfo,
            classes={
                "OutputSetStub": OutputSetStub,
                "ItemStub": ItemStub,
            },
            cache=False,
        )

        assert isinstance(
            runtimeSet,
            OutputSetStub,
        )

        assert runtimeSet.isPostgresqlRuntimeOutput()
        assert runtimeSet.getObjId() == 1_000_001
        assert runtimeSet.getSize() == 2

        runtimeItems = list(
            runtimeSet.iterItems()
        )

        assert len(runtimeItems) == 2

        assert isinstance(
            runtimeItems[0],
            ItemStub,
        )
        assert runtimeItems[0].getObjId() == 1
        assert runtimeItems[0]._score.get() == 0.25
        assert runtimeItems[0]._code.get() == "ITEM_01"

        assert isinstance(
            runtimeItems[1],
            ItemStub,
        )
        assert runtimeItems[1].getObjId() == 2
        assert runtimeItems[1]._score.get() == 0.75
        assert runtimeItems[1]._code.get() == "ITEM_02"

    finally:
        if runtimeSet is not None:
            runtimeSet.close()

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


def test_PostgresqlRuntimeSetAppendPersistsAcrossConnections(
        postgresqlIntegrationDb,
        postgresqlMigratedEnv,
):
    writerMapper = PostgresqlFlatMapper(
        postgresqlIntegrationDb
    )

    suffix = uuid4().hex

    userId = None
    projectId = None
    readerDb = None
    verifierDb = None
    runtimeSet = None
    verifiedRuntimeSet = None

    try:
        userId = writerMapper.insertUser(
            email="postgresql-streaming-%s@example.com" % suffix,
            hashedPassword="integration-test",
            firstName="PostgreSQL",
            lastName="Streaming Integration",
            institution=None,
            role="user",
            isActive=True,
            isVerified=True,
            verificationCode="integration-test",
        )

        projectId = writerMapper.insertProject(
            ownerId=userId,
            name="PostgreSQL streaming integration %s" % suffix,
            description="Runtime PostgreSQL incremental append integration test.",
            status="active",
        )

        protocolId = 2

        protocolDbId = writerMapper.saveProtocol(
            {
                "info": {
                    "protocolId": protocolId,
                    "projectId": projectId,
                    "protocolClassName": "IntegrationStreamingProtocol",
                    "status": "running",
                },
                "values": {},
                "parentIds": [],
                "childIds": [],
            }
        )

        sourceSet = SourceOutputSetStub(
            [
                _buildItem(
                    itemId=1,
                    score=0.25,
                    code="ITEM_01",
                ),
                _buildItem(
                    itemId=2,
                    score=0.75,
                    code="ITEM_02",
                ),
            ]
        )

        sourceSet.setObjId(
            1_000_002
        )

        setMapper = ScipionSetPostgresqlMapper(
            postgresqlIntegrationDb
        )

        storeResult = setMapper.storeSet(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName="outputStreamingItems",
            scipionSet=sourceSet,
        )

        assert storeResult["itemsCount"] == 2
        assert storeResult["maxItemId"] == 2

        readerDb = _openPostgresqlIntegrationDb(
            postgresqlMigratedEnv
        )

        readerSetMapper = ScipionSetPostgresqlMapper(
            readerDb
        )

        storedSet = readerSetMapper.getStoredSet(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName="outputStreamingItems",
        )

        assert storedSet is not None

        objectTree = readerSetMapper.getStoredObjectTree(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName="outputStreamingItems",
        )

        rootObject = next(
            row
            for row in objectTree
            if row["path"] == "outputStreamingItems"
        )

        outputInfo = {
            "setId": int(storedSet["id"]),
            "rootObjectId": int(storedSet["objectId"]),
            "runtimeObjectId": int(rootObject["scipionObjId"]),
            "projectId": projectId,
            "protocolDbId": protocolDbId,
            "outputName": "outputStreamingItems",
            "setClassName": storedSet["setClassName"],
            "itemClassName": storedSet["itemClassName"],
            "properties": storedSet["properties"],
        }

        runtimeSetFactory = PostgresqlRuntimeSetFactory()

        runtimeSet = runtimeSetFactory.build(
            db=readerDb,
            parent=ParentProtocolStub(
                protocolId
            ),
            outputName="outputStreamingItems",
            outputInfo=outputInfo,
            classes={
                "OutputSetStub": OutputSetStub,
                "ItemStub": ItemStub,
            },
            cache=False,
        )

        assert runtimeSet.getSize() == 2
        assert runtimeSet.supportsPostgresqlNativeWrite()
        assert not runtimeSet.isPostgresqlWritable()

        runtimeSet.enableAppend()

        assert runtimeSet.isPostgresqlWritable()

        appendedItem = _buildItem(
            itemId=None,
            score=0.95,
            code="ITEM_03",
        )

        assert appendedItem.getObjId() is None

        runtimeSet.append(
            appendedItem
        )

        assert appendedItem.getObjId() == 3
        assert runtimeSet.getSize() == 3

        runtimeSet.close()
        runtimeSet = None

        readerDb.close()
        readerDb = None

        verifierDb = _openPostgresqlIntegrationDb(
            postgresqlMigratedEnv
        )

        verifierSetMapper = ScipionSetPostgresqlMapper(
            verifierDb
        )

        verifiedStoredSet = verifierSetMapper.getStoredSet(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName="outputStreamingItems",
        )

        assert verifiedStoredSet is not None
        assert len(verifiedStoredSet["items"]) == 3

        assert verifiedStoredSet["items"][2]["scipionItemId"] == 3
        assert verifiedStoredSet["items"][2]["values"]["_score"] == 0.95
        assert verifiedStoredSet["items"][2]["values"]["_code"] == "ITEM_03"

        verifierObjectTree = verifierSetMapper.getStoredObjectTree(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName="outputStreamingItems",
        )

        verifierRootObject = next(
            row
            for row in verifierObjectTree
            if row["path"] == "outputStreamingItems"
        )

        verifiedOutputInfo = {
            "setId": int(verifiedStoredSet["id"]),
            "rootObjectId": int(verifiedStoredSet["objectId"]),
            "runtimeObjectId": int(verifierRootObject["scipionObjId"]),
            "projectId": projectId,
            "protocolDbId": protocolDbId,
            "outputName": "outputStreamingItems",
            "setClassName": verifiedStoredSet["setClassName"],
            "itemClassName": verifiedStoredSet["itemClassName"],
            "properties": verifiedStoredSet["properties"],
        }

        verifierRuntimeSetFactory = PostgresqlRuntimeSetFactory()

        verifiedRuntimeSet = verifierRuntimeSetFactory.build(
            db=verifierDb,
            parent=ParentProtocolStub(
                protocolId
            ),
            outputName="outputStreamingItems",
            outputInfo=verifiedOutputInfo,
            classes={
                "OutputSetStub": OutputSetStub,
                "ItemStub": ItemStub,
            },
            cache=False,
        )

        assert verifiedRuntimeSet.getSize() == 3

        verifiedItems = list(
            verifiedRuntimeSet.iterItems()
        )

        assert len(verifiedItems) == 3

        assert verifiedItems[2].getObjId() == 3
        assert verifiedItems[2]._score.get() == 0.95
        assert verifiedItems[2]._code.get() == "ITEM_03"

    finally:
        if verifiedRuntimeSet is not None:
            verifiedRuntimeSet.close()

        if runtimeSet is not None:
            runtimeSet.close()

        if verifierDb is not None:
            verifierDb.close()

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


def test_PostgresqlStreamingProducerConsumerRefreshesItemsAndState(
        postgresqlIntegrationDb,
        postgresqlMigratedEnv,
):
    writerMapper = PostgresqlFlatMapper(
        postgresqlIntegrationDb
    )

    suffix = uuid4().hex

    userId = None
    projectId = None
    producerDb = None
    consumerDb = None
    producerSet = None
    consumerSet = None

    try:
        userId = writerMapper.insertUser(
            email="postgresql-producer-consumer-%s@example.com" % suffix,
            hashedPassword="integration-test",
            firstName="PostgreSQL",
            lastName="Producer Consumer",
            institution=None,
            role="user",
            isActive=True,
            isVerified=True,
            verificationCode="integration-test",
        )

        projectId = writerMapper.insertProject(
            ownerId=userId,
            name="PostgreSQL producer consumer %s" % suffix,
            description="Runtime PostgreSQL streaming producer-consumer integration test.",
            status="active",
        )

        protocolId = 2

        protocolDbId = writerMapper.saveProtocol(
            {
                "info": {
                    "protocolId": protocolId,
                    "projectId": projectId,
                    "protocolClassName": "IntegrationStreamingProtocol",
                    "status": "running",
                },
                "values": {},
                "parentIds": [],
                "childIds": [],
            }
        )

        sourceSet = SourceOutputSetStub(
            [
                _buildItem(
                    itemId=1,
                    score=0.25,
                    code="ITEM_01",
                ),
                _buildItem(
                    itemId=2,
                    score=0.75,
                    code="ITEM_02",
                ),
            ]
        )

        sourceSet.setObjId(
            1_000_003
        )

        sourceSetMapper = ScipionSetPostgresqlMapper(
            postgresqlIntegrationDb
        )

        storeResult = sourceSetMapper.storeSet(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName="outputStreamingItems",
            scipionSet=sourceSet,
        )

        assert storeResult["itemsCount"] == 2
        assert storeResult["maxItemId"] == 2

        producerDb = _openPostgresqlIntegrationDb(
            postgresqlMigratedEnv
        )

        consumerDb = _openPostgresqlIntegrationDb(
            postgresqlMigratedEnv
        )

        producerSetMapper = ScipionSetPostgresqlMapper(
            producerDb
        )

        consumerSetMapper = ScipionSetPostgresqlMapper(
            consumerDb
        )

        producerOutputInfo = _loadRuntimeOutputInfo(
            setMapper=producerSetMapper,
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName="outputStreamingItems",
        )

        consumerOutputInfo = _loadRuntimeOutputInfo(
            setMapper=consumerSetMapper,
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName="outputStreamingItems",
        )

        producerSetFactory = PostgresqlRuntimeSetFactory()

        consumerSetFactory = PostgresqlRuntimeSetFactory()

        producerSet = producerSetFactory.build(
            db=producerDb,
            parent=ParentProtocolStub(
                protocolId
            ),
            outputName="outputStreamingItems",
            outputInfo=producerOutputInfo,
            classes={
                "OutputSetStub": OutputSetStub,
                "ItemStub": ItemStub,
            },
            cache=False,
        )

        consumerSet = consumerSetFactory.build(
            db=consumerDb,
            parent=ParentProtocolStub(
                protocolId
            ),
            outputName="outputStreamingItems",
            outputInfo=consumerOutputInfo,
            classes={
                "OutputSetStub": OutputSetStub,
                "ItemStub": ItemStub,
            },
            cache=False,
        )

        assert producerSet.getSize() == 2
        assert consumerSet.getSize() == 2

        assert producerSet.isStreamClosed()
        assert consumerSet.isStreamClosed()

        assert not producerSet.isPostgresqlWritable()
        assert not consumerSet.isPostgresqlWritable()

        producerSet.enableAppend()

        assert producerSet.isPostgresqlWritable()
        assert not consumerSet.isPostgresqlWritable()

        producerSet.setStreamState(
            Set.STREAM_OPEN
        )

        producerSet.write()

        consumerSet.loadAllProperties()

        assert producerSet.isStreamOpen()
        assert consumerSet.isStreamOpen()

        appendedItem = _buildItem(
            itemId=None,
            score=0.95,
            code="ITEM_03",
        )

        producerSet.append(
            appendedItem
        )

        producerSet.write()

        assert appendedItem.getObjId() == 3
        assert producerSet.getSize() == 3
        assert producerSet.isStreamOpen()

        consumerSet.loadAllProperties()

        assert consumerSet.getSize() == 3
        assert consumerSet.isStreamOpen()

        consumerItems = list(
            consumerSet.iterItems()
        )

        assert len(consumerItems) == 3

        assert consumerItems[2].getObjId() == 3
        assert consumerItems[2]._score.get() == 0.95
        assert consumerItems[2]._code.get() == "ITEM_03"

        producerSet.setStreamState(
            Set.STREAM_CLOSED
        )

        producerSet.write()

        assert producerSet.isStreamClosed()

        consumerSet.loadAllProperties()

        assert consumerSet.getSize() == 3
        assert consumerSet.isStreamClosed()

        closedStoredSet = consumerSetMapper.getStoredSet(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName="outputStreamingItems",
        )

        assert closedStoredSet is not None
        assert int(
            closedStoredSet["properties"]["_streamState"]
        ) == Set.STREAM_CLOSED

    finally:
        if consumerSet is not None:
            consumerSet.close()

        if producerSet is not None:
            producerSet.close()

        if consumerDb is not None:
            consumerDb.close()

        if producerDb is not None:
            producerDb.close()

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


def test_NestedSetLogicalTablesPersistAndHydrateAcrossPostgresqlConnections(
        postgresqlIntegrationDb,
        postgresqlMigratedEnv,
):
    writerMapper = PostgresqlFlatMapper(postgresqlIntegrationDb)

    suffix = uuid4().hex

    userId = None
    projectId = None
    readerDb = None
    runtimeSet = None

    try:
        userId = writerMapper.insertUser(
            email="postgresql-nested-%s@example.com" % suffix,
            hashedPassword="integration-test",
            firstName="PostgreSQL",
            lastName="Nested Integration",
            institution=None,
            role="user",
            isActive=True,
            isVerified=True,
            verificationCode="integration-test",
        )

        projectId = writerMapper.insertProject(
            ownerId=userId,
            name="PostgreSQL nested integration %s" % suffix,
            description="Runtime nested Set PostgreSQL integration test.",
            status="active",
        )

        protocolId = 2

        protocolDbId = writerMapper.saveProtocol(
            {
                "info": {
                    "protocolId": protocolId,
                    "projectId": projectId,
                    "protocolClassName": "IntegrationNestedSetProtocol",
                    "status": "finished",
                },
                "values": {},
                "parentIds": [],
                "childIds": [],
            }
        )

        nestedSet = SourceNestedSetStub(
            [
                _buildItem(
                    itemId=1,
                    score=0.25,
                    code="CHILD_01",
                ),
                _buildItem(
                    itemId=2,
                    score=0.75,
                    code="CHILD_02",
                ),
            ]
        )

        nestedSet.setObjId(7)
        nestedSet._name.set("SERIES_07")

        sourceSet = SourceParentOutputSetStub(
            [
                nestedSet,
            ]
        )

        sourceSet.setObjId(1_000_004)

        setMapper = ScipionSetPostgresqlMapper(
            postgresqlIntegrationDb
        )

        storeResult = setMapper.storeSet(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName="outputNestedItems",
            scipionSet=sourceSet,
        )

        assert storeResult["itemsCount"] == 1
        assert storeResult["maxItemId"] == 7
        assert storeResult["runtimeObjectId"] == 1_000_004
        assert storeResult["setClassName"] == "ParentOutputSetStub"
        assert storeResult["itemClassName"] == "NestedSetStub"

        readerDb = _openPostgresqlIntegrationDb(
            postgresqlMigratedEnv
        )

        readerSetMapper = ScipionSetPostgresqlMapper(
            readerDb
        )

        storedSet = readerSetMapper.getStoredSet(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName="outputNestedItems",
        )

        assert storedSet is not None
        assert storedSet["setClassName"] == "ParentOutputSetStub"
        assert storedSet["itemClassName"] == "NestedSetStub"
        assert len(storedSet["items"]) == 1
        assert storedSet["items"][0]["scipionItemId"] == 7

        logicalTables = readerSetMapper.listStoredSetTables(
            int(storedSet["id"])
        )

        assert len(logicalTables) == 2

        rootTable = next(
            table
            for table in logicalTables
            if table["tableKind"] == "root"
        )

        childTable = next(
            table
            for table in logicalTables
            if table["tableKind"] == "child"
        )

        assert childTable["parentTableId"] == rootTable["id"]
        assert childTable["parentItemId"] == 7
        assert childTable["itemClassName"] == "ItemStub"

        childRows = readerSetMapper.getStoredSetTableItems(
            int(childTable["id"])
        )

        assert len(childRows) == 2

        assert childRows[0]["scipionItemId"] == 1
        assert childRows[0]["parentItemId"] == 7
        assert childRows[0]["values"]["_score"] == 0.25
        assert childRows[0]["values"]["_code"] == "CHILD_01"

        assert childRows[1]["scipionItemId"] == 2
        assert childRows[1]["parentItemId"] == 7
        assert childRows[1]["values"]["_score"] == 0.75
        assert childRows[1]["values"]["_code"] == "CHILD_02"

        outputInfo = _loadRuntimeOutputInfo(
            setMapper=readerSetMapper,
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName="outputNestedItems",
        )

        runtimeSetFactory = PostgresqlRuntimeSetFactory()

        runtimeSet = runtimeSetFactory.build(
            db=readerDb,
            parent=ParentProtocolStub(protocolId),
            outputName="outputNestedItems",
            outputInfo=outputInfo,
            classes={
                "ParentOutputSetStub": ParentOutputSetStub,
                "NestedSetStub": NestedSetStub,
                "ItemStub": ItemStub,
            },
            cache=False,
        )

        assert isinstance(runtimeSet, ParentOutputSetStub)
        assert runtimeSet.isPostgresqlRuntimeOutput()
        assert runtimeSet.getObjId() == 1_000_004
        assert runtimeSet.getSize() == 1

        hydratedNestedSet = runtimeSet.getFirstItem()

        assert isinstance(hydratedNestedSet, NestedSetStub)
        assert hydratedNestedSet.isPostgresqlRuntimeOutput()
        assert hydratedNestedSet.getObjId() == 7
        assert hydratedNestedSet._name.get() == "SERIES_07"
        assert hydratedNestedSet._objParent is None
        assert hydratedNestedSet.supportsPostgresqlNativeWrite()
        assert not hydratedNestedSet.isPostgresqlWritable()

        hydratedChildren = list(
            hydratedNestedSet.iterItems()
        )

        assert len(hydratedChildren) == 2
        assert hydratedNestedSet.getSize() == 2

        assert isinstance(hydratedChildren[0], ItemStub)
        assert hydratedChildren[0].getObjId() == 1
        assert hydratedChildren[0].getObjParentId() == 7
        assert hydratedChildren[0]._score.get() == 0.25
        assert hydratedChildren[0]._code.get() == "CHILD_01"

        assert isinstance(hydratedChildren[1], ItemStub)
        assert hydratedChildren[1].getObjId() == 2
        assert hydratedChildren[1].getObjParentId() == 7
        assert hydratedChildren[1]._score.get() == 0.75
        assert hydratedChildren[1]._code.get() == "CHILD_02"

    finally:
        if runtimeSet is not None:
            runtimeSet.close()

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


def test_NestedSetIncrementalAppendPersistsAndHydratesAcrossPostgresqlConnections(postgresqlIntegrationDb, postgresqlMigratedEnv):
    from uuid import uuid4

    writerMapper = PostgresqlFlatMapper(postgresqlIntegrationDb)

    userId = writerMapper.insertUser(
        email="nested-append-%s@example.com" % uuid4().hex,
        hashedPassword="test-password",
        firstName="Nested",
        lastName="Append",
        institution=None,
        role="user",
        isActive=True,
        isVerified=True,
        verificationCode="",
    )

    projectId = writerMapper.insertProject(
        ownerId=userId,
        name="PostgreSQL Nested Append Integration",
        description="Nested PostgreSQL incremental append integration test",
    )

    protocolId = 2

    protocolDbId = writerMapper.saveProtocol({
        "info": {
            "protocolId": protocolId,
            "projectId": projectId,
            "protocolClassName": "NestedSetIntegrationProtocol",
            "status": "finished",
        },
        "values": {},
        "parentIds": [],
        "childIds": [],
    })

    outputName = "outputNestedItems"

    nestedSet = SourceNestedSetStub([
        _buildItem(itemId=1, score=0.25, code="CHILD_01"),
        _buildItem(itemId=2, score=0.75, code="CHILD_02"),
    ])
    nestedSet.setObjId(7)
    nestedSet._name.set("SERIES_07")

    sourceSet = SourceParentOutputSetStub([
        nestedSet,
    ])
    sourceSet.setObjId(1_000_004)

    setMapper = ScipionSetPostgresqlMapper(
        postgresqlIntegrationDb
    )

    firstReaderDb = None
    secondReaderDb = None
    runtimeSet = None
    hydratedNestedSet = None
    rehydratedRuntimeSet = None
    rehydratedNestedSet = None

    def buildRuntimeSet(db):
        readerSetMapper = ScipionSetPostgresqlMapper(
            db
        )

        storedSet = readerSetMapper.getStoredSet(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName=outputName,
        )

        assert storedSet is not None

        setClassName = storedSet["setClassName"]
        itemClassName = storedSet["itemClassName"]

        outputInfo = {
            "setId": int(storedSet["id"]),
            "projectId": projectId,
            "protocolDbId": protocolDbId,
            "protocolId": str(protocolId),
            "objectId": storedSet.get("objectId"),
            "runtimeObjectId": sourceSet.getObjId(),
            "outputName": outputName,
            "className": setClassName,
            "setClassName": setClassName,
            "itemClassName": itemClassName,
            "itemsCount": len(storedSet.get("items") or []),
            "properties": storedSet.get("properties") or {},
        }

        classes = {
            setClassName: ParentOutputSetStub,
            itemClassName: NestedSetStub,
            "ParentOutputSetStub": ParentOutputSetStub,
            "NestedSetStub": NestedSetStub,
            "ItemStub": ItemStub,
        }

        return PostgresqlRuntimeSetFactory().build(
            db=db,
            parent=ParentProtocolStub(protocolId),
            outputName=outputName,
            outputInfo=outputInfo,
            classes=classes,
            cache=False,
        )

    try:
        storeResult = setMapper.storeSet(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName=outputName,
            scipionSet=sourceSet,
        )

        setId = int(
            storeResult["setId"]
        )

        logicalTables = setMapper.listStoredSetTables(
            setId
        )

        rootTables = [
            table
            for table in logicalTables
            if table["tableKind"] == "root"
        ]

        childTables = [
            table
            for table in logicalTables
            if table["tableKind"] == "child"
        ]

        assert len(rootTables) == 1
        assert len(childTables) == 1

        rootTable = rootTables[0]
        childTable = childTables[0]

        assert childTable["parentTableId"] == rootTable["id"]
        assert childTable["parentItemId"] == 7

        childTableId = int(
            childTable["id"]
        )

        initialChildRows = setMapper.getStoredSetTableItems(
            childTableId
        )

        assert len(initialChildRows) == 2
        assert [row["scipionItemId"] for row in initialChildRows] == [1, 2]

        firstReaderDb = _openPostgresqlIntegrationDb(
            postgresqlMigratedEnv
        )

        runtimeSet = buildRuntimeSet(
            firstReaderDb
        )

        assert runtimeSet.getSize() == 1

        hydratedNestedSet = runtimeSet.getFirstItem()

        assert isinstance(
            hydratedNestedSet,
            NestedSetStub,
        )

        assert hydratedNestedSet.getObjId() == 7
        assert hydratedNestedSet.getSize() == 2
        assert hydratedNestedSet.supportsPostgresqlNativeWrite() is True
        assert hydratedNestedSet.isPostgresqlWritable() is False

        initialChildren = list(
            hydratedNestedSet.iterItems()
        )

        assert len(initialChildren) == 2
        assert [child.getObjId() for child in initialChildren] == [1, 2]
        assert [child._score.get() for child in initialChildren] == [0.25, 0.75]
        assert [child._code.get() for child in initialChildren] == ["CHILD_01", "CHILD_02"]
        assert all(child.getObjParentId() == 7 for child in initialChildren)

        hydratedNestedSet.enableAppend()

        assert hydratedNestedSet.isPostgresqlWritable() is True

        appendedChild = _buildItem(
            itemId=None,
            score=0.95,
            code="CHILD_03",
        )

        assert appendedChild.getObjId() is None

        hydratedNestedSet.append(
            appendedChild
        )

        assert appendedChild.getObjId() == 3
        assert hydratedNestedSet.getSize() == 3

        storedChild = postgresqlIntegrationDb.fetchOne(
            """
            SELECT
                item."tableId",
                item."scipionItemId",
                item."parentItemId",
                item."values"
              FROM scipion_set_table_items item
              JOIN scipion_set_tables logical_table
                ON logical_table.id = item."tableId"
             WHERE logical_table."setId" = %s
               AND logical_table."tableKind" = 'child'
               AND logical_table."parentItemId" = %s
               AND item."scipionItemId" = %s
            """,
            (
                setId,
                7,
                3,
            ),
        )

        assert storedChild is not None
        assert storedChild["tableId"] == childTableId
        assert storedChild["scipionItemId"] == 3
        assert storedChild["parentItemId"] == 7
        assert storedChild["values"]["_score"] == 0.95
        assert storedChild["values"]["_code"] == "CHILD_03"

        physicalChildren = postgresqlIntegrationDb.fetchAll(
            """
            SELECT
                item."scipionItemId",
                item."parentItemId",
                item."values"
              FROM scipion_set_table_items item
             WHERE item."tableId" = %s
             ORDER BY item."scipionItemId"
            """,
            (
                childTableId,
            ),
        )

        assert len(physicalChildren) == 3
        assert [row["scipionItemId"] for row in physicalChildren] == [1, 2, 3]
        assert all(row["parentItemId"] == 7 for row in physicalChildren)

        hydratedNestedSet.close()
        runtimeSet.close()
        firstReaderDb.close()

        secondReaderDb = _openPostgresqlIntegrationDb(
            postgresqlMigratedEnv
        )

        rehydratedRuntimeSet = buildRuntimeSet(
            secondReaderDb
        )

        assert rehydratedRuntimeSet.getSize() == 1

        rehydratedNestedSet = rehydratedRuntimeSet.getFirstItem()

        assert isinstance(
            rehydratedNestedSet,
            NestedSetStub,
        )

        assert rehydratedNestedSet.getObjId() == 7
        assert rehydratedNestedSet.getSize() == 3
        assert rehydratedNestedSet.supportsPostgresqlNativeWrite() is True
        assert rehydratedNestedSet.isPostgresqlWritable() is False

        rehydratedChildren = list(
            rehydratedNestedSet.iterItems()
        )

        assert len(rehydratedChildren) == 3
        assert [child.getObjId() for child in rehydratedChildren] == [1, 2, 3]
        assert [child._score.get() for child in rehydratedChildren] == [0.25, 0.75, 0.95]
        assert [child._code.get() for child in rehydratedChildren] == ["CHILD_01", "CHILD_02", "CHILD_03"]
        assert all(child.getObjParentId() == 7 for child in rehydratedChildren)

        appendedHydratedChild = rehydratedChildren[2]

        assert appendedHydratedChild.getObjId() == 3
        assert appendedHydratedChild.getObjParentId() == 7
        assert appendedHydratedChild._score.get() == 0.95
        assert appendedHydratedChild._code.get() == "CHILD_03"

    finally:
        if rehydratedNestedSet is not None:
            rehydratedNestedSet.close()

        if rehydratedRuntimeSet is not None:
            rehydratedRuntimeSet.close()

        if secondReaderDb is not None:
            secondReaderDb.close()

        if hydratedNestedSet is not None:
            hydratedNestedSet.close()

        if runtimeSet is not None:
            runtimeSet.close()

        if firstReaderDb is not None:
            firstReaderDb.close()

        writerMapper.deleteProject(
            projectId=projectId,
            ownerId=userId,
        )

        postgresqlIntegrationDb.execute(
            """
            DELETE FROM users
             WHERE id = %s
            """,
            (
                userId,
            ),
        )



