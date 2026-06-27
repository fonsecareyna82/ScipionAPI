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

import importlib

import pytest


class FakeParam:
    def __init__(self, value):
        self.value = value


class FakeProtocol:
    def __init__(self, status, outputs=None, steps=None, inputs=None, params=None, className="FakeProtocol"):
        self.status = status
        self.outputs = outputs or []
        self.steps = steps or []
        self.inputs = inputs or []
        self.params = params or {}
        self.className = className

    def getClassName(self):
        return self.className

    def getStatus(self):
        return self.status

    def iterOutputAttributes(self):
        return list(self.outputs)

    def loadSteps(self):
        return list(self.steps)

    def iterInputAttributes(self):
        return list(self.inputs)

    def iterParams(self):
        return [
            (paramName, FakeParam(value))
            for paramName, value in self.params.items()
        ]

    def getAttributeValue(self, paramName):
        return self.params.get(paramName)

class FakePointerTarget:
    def __init__(self, objId, className):
        self.objId = objId
        self.className = className

    def getObjId(self):
        return self.objId

    def getClassName(self):
        return self.className


class FakePointer:
    def __init__(self, parentProtocolId, outputName, className="SetOfParticles", objectId=100):
        self.parent = FakePointerTarget(parentProtocolId, className)
        self.target = FakePointerTarget(objectId, className)
        self.outputName = outputName

    def getObjValue(self):
        return self.parent

    def getExtended(self):
        return self.outputName

    def get(self):
        return self.target


class FakeOutput:
    def __init__(self, className, itemsCount=None):
        self.className = className
        self.itemsCount = itemsCount

    def getClassName(self):
        return self.className

    def getSize(self):
        return self.itemsCount


class FakeValueHolder:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class FakeStep:
    def __init__(self, index, name, status):
        self.index = index
        self.funcName = FakeValueHolder(name)
        self.status = status

    def getIndex(self):
        return self.index

    def getStatus(self):
        return self.status

    def getClassName(self):
        return "FakeStep"


class FakeParentNode:
    def __init__(self, name):
        self.name = name

    def getName(self):
        return self.name


class FakeRunNode:
    def __init__(self, name, status=None, parents=None):
        self.name = name
        self.run = FakeProtocol(status) if status is not None else None
        self._parents = [FakeParentNode(parentName) for parentName in (parents or [])]

    def getName(self):
        return self.name


class FakeRunsGraph:
    def __init__(self, nodes):
        self._nodesDict = nodes


class FakeCurrentProject:
    def __init__(self, nodes):
        self.nodes = nodes
        self.lastRefresh = None
        self.lastCheckPids = None

    def getRunsGraph(self, refresh=True, checkPids=True):
        self.lastRefresh = refresh
        self.lastCheckPids = checkPids
        return FakeRunsGraph(self.nodes)


class FakeMapper:
    def __init__(
            self,
            projectRow,
            protocolRows,
            adjacencyMap,
            setRows=None,
            treeRows=None,
            stepsByProtocolId=None,
            inputRefs=None,
    ):
        self.projectRow = projectRow
        self.protocolRows = protocolRows
        self.adjacencyMap = adjacencyMap
        self.stepsByProtocolId = stepsByProtocolId or {}
        self.inputRefs = inputRefs or []
        self.db = FakeDb(
            setRows=setRows,
            treeRows=treeRows,
        )

    def getProject(self, projectId, userId):
        if int(projectId) != int(self.projectRow["id"]):
            return None
        if int(userId) != int(self.projectRow["ownerId"]):
            return None
        return dict(self.projectRow)

    def getProtocols(self, projectId):
        return list(self.protocolRows)

    def getProjectProtocolAdjacencyMap(self, projectId):
        return dict(self.adjacencyMap)

    def getProjectProtocolStepsByProtocolId(self, projectId):
        return dict(self.stepsByProtocolId)

    def listProtocolInputRefs(self, projectId):
        return list(self.inputRefs)


class FakeDb:
    def __init__(self, setRows=None, treeRows=None):
        self.setRows = setRows or []
        self.treeRows = treeRows or []
        self.fetchAllCalls = []

    def fetchAll(self, query, params):
        normalizedQuery = " ".join(str(query).split())

        self.fetchAllCalls.append(
            {
                "query": query,
                "params": params,
            }
        )

        if "FROM scipion_objects o" in normalizedQuery:
            return list(self.treeRows)

        if "FROM scipion_sets s" in normalizedQuery and "JOIN protocols p" in normalizedQuery:
            return list(self.setRows)

        return []


def makeSetRow(
        protocolId="10",
        outputName="outputParticles",
        setClassName="SetOfParticles",
        itemsCount=1,
        itemsTableCount=None,
        maxItemId=1,
        maxItemIdFromItems=None,
        columnsCount=2,
        setColumnsCount=None,
        rootTablesCount=1,
        rootTableId=500,
        rootTableItemsCount=None,
        rootTableMaxItemId=None,
        rootTableColumnsCount=None,
        setColumnsSignature=None,
        rootTableColumnsSignature=None,
        itemsIdSignature="items-1-2-3",
        rootTableItemsIdSignature=None,
        itemsValueSignature="values-1-2-3",
        rootTableItemsValueSignature=None,
        propertiesPayloadSignature=None,
        setPropertiesSignature=None,
        propertiesPayloadCount=None,
        setPropertiesCount=None,
        protocolDbId=1000,
        rootObjectDbId=None,
        rootObjectProjectId=1,
        rootObjectProtocolDbId=None,
        rootObjectParentObjectId=None,
        rootObjectName=None,
        rootObjectPath=None,
        rootObjectClassName=None,
):
    defaultColumnsSignature = [
        {
            "labelProperty": "_id",
            "columnName": "id",
            "className": "Integer",
            "valueType": "int",
            "position": 0,
            "indexed": True,
        },
        {
            "labelProperty": "_enabled",
            "columnName": "enabled",
            "className": "Boolean",
            "valueType": "bool",
            "position": 1,
            "indexed": False,
        },
    ]

    resolvedItemsTableCount = (
        itemsCount if itemsTableCount is None else itemsTableCount
    )
    resolvedMaxItemIdFromItems = (
        maxItemId if maxItemIdFromItems is None else maxItemIdFromItems
    )
    resolvedSetColumnsCount = (
        columnsCount if setColumnsCount is None else setColumnsCount
    )
    resolvedSetColumnsSignature = (
        defaultColumnsSignature
        if setColumnsSignature is None
        else setColumnsSignature
    )

    if rootTablesCount == 0:
        resolvedRootTableId = None
        resolvedRootTableItemsCount = 0
        resolvedRootTableMaxItemId = None
        resolvedRootTableColumnsCount = 0
        resolvedRootTableColumnsSignature = []
        resolvedRootTableItemsIdSignature = None
        resolvedRootTableItemsValueSignature = None
    else:
        resolvedRootTableId = rootTableId
        resolvedRootTableItemsCount = (
            resolvedItemsTableCount
            if rootTableItemsCount is None
            else rootTableItemsCount
        )
        resolvedRootTableMaxItemId = (
            resolvedMaxItemIdFromItems
            if rootTableMaxItemId is None
            else rootTableMaxItemId
        )
        resolvedRootTableColumnsCount = (
            resolvedSetColumnsCount
            if rootTableColumnsCount is None
            else rootTableColumnsCount
        )
        resolvedRootTableColumnsSignature = (
            resolvedSetColumnsSignature
            if rootTableColumnsSignature is None
            else rootTableColumnsSignature
        )
        resolvedRootTableItemsIdSignature = (
            itemsIdSignature
            if rootTableItemsIdSignature is None
            else rootTableItemsIdSignature
        )
        resolvedRootTableItemsValueSignature = (
            itemsValueSignature
            if rootTableItemsValueSignature is None
            else rootTableItemsValueSignature
        )

    defaultPropertiesSignature = [
        {
            "key": "columnsCount",
            "value": str(columnsCount),
        },
        {
            "key": "itemsCount",
            "value": str(itemsCount),
        },
        {
            "key": "nestedTablesVersion",
            "value": "14",
        },
    ]

    resolvedPropertiesPayloadSignature = (
        defaultPropertiesSignature
        if propertiesPayloadSignature is None
        else propertiesPayloadSignature
    )
    resolvedSetPropertiesSignature = (
        resolvedPropertiesPayloadSignature
        if setPropertiesSignature is None
        else setPropertiesSignature
    )
    resolvedPropertiesPayloadCount = (
        len(resolvedPropertiesPayloadSignature)
        if propertiesPayloadCount is None
        else propertiesPayloadCount
    )
    resolvedSetPropertiesCount = (
        len(resolvedSetPropertiesSignature)
        if setPropertiesCount is None
        else setPropertiesCount
    )

    resolvedRootObjectDbId = (
        200 if rootObjectDbId is None else rootObjectDbId
    )
    resolvedRootObjectProtocolDbId = (
        protocolDbId if rootObjectProtocolDbId is None else rootObjectProtocolDbId
    )
    resolvedRootObjectName = (
        outputName if rootObjectName is None else rootObjectName
    )
    resolvedRootObjectPath = (
        outputName if rootObjectPath is None else rootObjectPath
    )
    resolvedRootObjectClassName = (
        setClassName if rootObjectClassName is None else rootObjectClassName
    )

    return {
        "protocolId": str(protocolId),
        "id": 100,
        "objectId": 200,
        "outputName": outputName,
        "setClassName": setClassName,
        "itemClassName": "Particle",
        "properties": {
            "itemsCount": itemsCount,
            "maxItemId": maxItemId,
            "columnsCount": columnsCount,
        },
        "itemsTableCount": resolvedItemsTableCount,
        "maxItemIdFromItems": resolvedMaxItemIdFromItems,
        "itemsIdSignature": itemsIdSignature,
        "setColumnsCount": resolvedSetColumnsCount,
        "setColumnsSignature": resolvedSetColumnsSignature,
        "rootTablesCount": rootTablesCount,
        "rootTableId": resolvedRootTableId,
        "rootTableItemsCount": resolvedRootTableItemsCount,
        "rootTableMaxItemId": resolvedRootTableMaxItemId,
        "rootTableItemsIdSignature": resolvedRootTableItemsIdSignature,
        "rootTableColumnsCount": resolvedRootTableColumnsCount,
        "rootTableColumnsSignature": resolvedRootTableColumnsSignature,
        "createdAt": None,
        "updatedAt": None,
        "itemsValueSignature": itemsValueSignature,
        "rootTableItemsValueSignature": resolvedRootTableItemsValueSignature,
        "propertiesPayloadCount": resolvedPropertiesPayloadCount,
        "propertiesPayloadSignature": resolvedPropertiesPayloadSignature,
        "setPropertiesCount": resolvedSetPropertiesCount,
        "setPropertiesSignature": resolvedSetPropertiesSignature,
        "protocolDbId": protocolDbId,
        "rootObjectDbId": resolvedRootObjectDbId,
        "rootObjectProjectId": rootObjectProjectId,
        "rootObjectProtocolDbId": resolvedRootObjectProtocolDbId,
        "rootObjectParentObjectId": rootObjectParentObjectId,
        "rootObjectName": resolvedRootObjectName,
        "rootObjectPath": resolvedRootObjectPath,
        "rootObjectClassName": resolvedRootObjectClassName,
    }


@pytest.fixture
def projectServiceModule(authTestEnv):
    return importlib.import_module("app.backend.api.services.project_service")


@pytest.fixture
def service(projectServiceModule):
    instance = object.__new__(projectServiceModule.ProjectService)
    instance.currentProject = None
    instance.tomoList = {}
    return instance


def patchRuntimeProject(service, monkeypatch, currentProject):
    def loadProjectForThumbnails(dbProj):
        service.currentProject = currentProject
        return currentProject

    monkeypatch.setattr(service, "loadProjectForThumbnails", loadProjectForThumbnails)


def test_ValidateProjectPostgresqlConsistencyReturnsOkWhenRuntimeAndDbMatch(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode("10", status="finished", parents=["PROJECT"]),
            "11": FakeRunNode("11", status="running", parents=["10"]),
        }
    )
    currentProject.nodes["10"].run.outputs = [
        ("outputParticles", FakeOutput("SetOfParticles", itemsCount=1)),
    ]
    currentProject.nodes["11"].run.inputs = [
        ("inputParticles", FakePointer(parentProtocolId=10, outputName="outputParticles")),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),

        },
        protocolRows=[
            {"protocolId": "10", "status": "finished", "protocolClassName": "FakeProtocol"},
            {"protocolId": "11", "status": "running", "protocolClassName": "FakeProtocol"},
        ],
        adjacencyMap={
            "10": {"parents": [], "children": ["11"]},
            "11": {"parents": ["10"], "children": []},
        },
        inputRefs=[
            {
                "protocolId": "11",
                "inputName": "inputParticles",
                "itemIndex": 0,
                "parentProtocolId": "10",
                "parentOutputName": "outputParticles",
                "objectClassName": "SetOfParticles",
                "objectId": "100",
            },
        ],
        setRows=[
            makeSetRow(
                protocolId="10",
                outputName="outputParticles",
                setClassName="SetOfParticles",
                itemsCount=1,
            ),
        ],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=False,
        checkPid=False,
    )

    assert result["ok"] is True
    assert result["summary"] == {
        "runtimeProtocols": 2,
        "postgresqlProtocols": 2,
        "runtimeDependencies": 1,
        "postgresqlDependencies": 1,
        "runtimeOutputs": 1,
        "postgresqlOutputs": 1,
        "runtimeSteps": 0,
        "postgresqlSteps": 0,
        "runtimeInputRefs": 1,
        "postgresqlInputRefs": 1,
        "runtimeInputRefDependencies": 1,
        "postgresqlInputRefDependencies": 1,
        "runtimeParams": 0,
        "postgresqlParams": 0,
        "issues": 0,
    }
    assert result["issues"] == {
        "missingProtocols": [],
        "extraProtocols": [],
        "statusMismatches": [],
        "missingDependencies": [],
        "extraDependencies": [],
        "missingOutputs": [],
        "extraOutputs": [],
        "missingSteps": [],
        "extraSteps": [],
        "stepMismatches": [],
        "missingInputRefs": [],
        "extraInputRefs": [],
        "inputRefMismatches": [],
        "runtimeInputRefDependenciesMissing": [],
        "runtimeDependenciesWithoutInputRefs": [],
        "postgresqlInputRefDependenciesMissing": [],
        "postgresqlDependenciesWithoutInputRefs": [],
        "missingParams": [],
        "extraParams": [],
        "paramValueMismatches": [],
        "outputClassMismatches": [],
        "outputMapperKindMismatches": [],
        "outputItemsCountMismatches": [],
        "postgresqlFlatSetMaxItemIdMismatches": [],
        "protocolClassMismatches": [],
        "postgresqlInputRefsWithMissingParentProtocols": [],
        "postgresqlInputRefsWithMissingParentOutputs": [],
        "postgresqlFlatSetOutputsWithIncompletePayload": [],
        "postgresqlTreeOutputsWithIncompletePayload": [],
        "postgresqlFlatSetItemsCountMismatches": [],
        "postgresqlFlatSetRootTableMismatches": [],
        "postgresqlFlatSetColumnsCountMismatches": [],
        "postgresqlFlatSetPropertiesMismatches": [],
        "postgresqlFlatSetRootObjectMismatches": [],
    }
    assert currentProject.lastRefresh is False
    assert currentProject.lastCheckPids is False


def test_ValidateProjectPostgresqlConsistencyReportsProtocolAndDependencyMismatches(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode("10", status="finished", parents=["PROJECT"]),
            "11": FakeRunNode("11", status="running", parents=["10"]),
        }
    )
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {"protocolId": "10", "status": "failed"},
            {"protocolId": "12", "status": "finished"},
        ],
        adjacencyMap={
            "10": {"parents": ["99"], "children": []},
            "12": {"parents": [], "children": []},
        },
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"] == {
        "runtimeProtocols": 2,
        "postgresqlProtocols": 2,
        "runtimeDependencies": 1,
        "postgresqlDependencies": 1,
        "runtimeOutputs": 0,
        "postgresqlOutputs": 0,
        "runtimeSteps": 0,
        "postgresqlSteps": 0,
        "runtimeInputRefs": 0,
        "postgresqlInputRefs": 0,
        "runtimeInputRefDependencies": 0,
        "postgresqlInputRefDependencies": 0,
        "runtimeParams": 0,
        "postgresqlParams": 0,
        "issues": 7,
    }
    assert result["issues"] == {
        "missingProtocols": [
            {
                "protocolId": "11",
                "runtimeStatus": "running",
            }
        ],
        "extraProtocols": [
            {
                "protocolId": "12",
                "postgresqlStatus": "finished",
            }
        ],
        "statusMismatches": [
            {
                "protocolId": "10",
                "runtimeStatus": "finished",
                "postgresqlStatus": "failed",
            }
        ],
        "missingDependencies": [
            {
                "parentId": "10",
                "childId": "11",
            }
        ],
        "extraDependencies": [
            {
                "parentId": "99",
                "childId": "10",
            }
        ],
        "missingOutputs": [],
        "extraOutputs": [],
        "missingSteps": [],
        "extraSteps": [],
        "stepMismatches": [],
        "missingInputRefs": [],
        "extraInputRefs": [],
        "inputRefMismatches": [],
        "runtimeInputRefDependenciesMissing": [],
        "runtimeDependenciesWithoutInputRefs": [
            {
                "parentId": "10",
                "childId": "11",
            }
        ],
        "postgresqlInputRefDependenciesMissing": [],
        "postgresqlDependenciesWithoutInputRefs": [
            {
                "parentId": "99",
                "childId": "10",
            }
        ],
        "missingParams": [],
        "extraParams": [],
        "paramValueMismatches": [],
        "outputClassMismatches": [],
        "outputMapperKindMismatches": [],
        "outputItemsCountMismatches": [],
        "postgresqlFlatSetMaxItemIdMismatches": [],
        "protocolClassMismatches": [],
        "postgresqlInputRefsWithMissingParentProtocols": [],
        "postgresqlInputRefsWithMissingParentOutputs": [],
        "postgresqlFlatSetOutputsWithIncompletePayload": [],
        "postgresqlTreeOutputsWithIncompletePayload": [],
        "postgresqlFlatSetItemsCountMismatches": [],
        "postgresqlFlatSetRootTableMismatches": [],
        "postgresqlFlatSetColumnsCountMismatches": [],
        "postgresqlFlatSetPropertiesMismatches": [],
        "postgresqlFlatSetRootObjectMismatches": [],
    }


def test_ValidateProjectPostgresqlConsistencyReportsOutputMismatches(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="finished",
                parents=["PROJECT"],
            ),
        }
    )
    currentProject.nodes["10"].run.outputs = [
        ("outputParticles", FakeOutput("SetOfParticles")),
        ("outputVolume", FakeOutput("Volume")),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {"protocolId": "10", "status": "finished", "protocolClassName": "FakeProtocol"},
        ],
        adjacencyMap={
            "10": {"parents": [], "children": []},
        },
        setRows=[
            {
                "protocolId": "10",
                "id": 100,
                "objectId": 200,
                "outputName": "outputParticles",
                "setClassName": "SetOfParticles",
                "itemClassName": "Particle",
                "properties": {"itemsCount": 12},
                "createdAt": None,
                "updatedAt": None,
            }
        ],
        treeRows=[
            {
                "protocolId": "10",
                "id": 300,
                "scipionObjId": 400,
                "name": "outputExtra",
                "path": "outputExtra",
                "className": "Volume",
                "value": None,
                "label": None,
                "comment": None,
                "metadata": {},
                "createdAt": None,
                "updatedAt": None,
            }
        ],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"] == {
        "runtimeProtocols": 1,
        "postgresqlProtocols": 1,
        "runtimeDependencies": 0,
        "postgresqlDependencies": 0,
        "runtimeOutputs": 2,
        "postgresqlOutputs": 2,
        "runtimeSteps": 0,
        "postgresqlSteps": 0,
        "runtimeInputRefs": 0,
        "postgresqlInputRefs": 0,
        "runtimeInputRefDependencies": 0,
        "postgresqlInputRefDependencies": 0,
        "runtimeParams": 0,
        "postgresqlParams": 0,
        "issues": 2,
    }
    assert result["issues"]["missingOutputs"] == [
        {
            "protocolId": "10",
            "outputName": "outputVolume",
            "className": "Volume",
        }
    ]
    assert result["issues"]["extraOutputs"] == [
        {
            "protocolId": "10",
            "outputName": "outputExtra",
            "mapperKind": "tree",
            "className": "Volume",
        }
    ]
    assert result["issues"]["missingProtocols"] == []
    assert result["issues"]["extraProtocols"] == []
    assert result["issues"]["statusMismatches"] == []
    assert result["issues"]["missingDependencies"] == []
    assert result["issues"]["extraDependencies"] == []
    assert result["issues"]["missingSteps"] == []
    assert result["issues"]["extraSteps"] == []
    assert result["issues"]["stepMismatches"] == []
    assert result["issues"]["missingInputRefs"] == []
    assert result["issues"]["extraInputRefs"] == []
    assert result["issues"]["inputRefMismatches"] == []
    assert result["issues"]["runtimeInputRefDependenciesMissing"] == []
    assert result["issues"]["runtimeDependenciesWithoutInputRefs"] == []
    assert result["issues"]["postgresqlInputRefDependenciesMissing"] == []
    assert result["issues"]["postgresqlDependenciesWithoutInputRefs"] == []
    assert result["issues"]["outputClassMismatches"] == []
    assert result["issues"]["outputMapperKindMismatches"] == []
    assert result["issues"]["outputItemsCountMismatches"] == []
    assert result["issues"]["protocolClassMismatches"] == []


def test_ValidateProjectPostgresqlConsistencyReportsStepMismatches(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="running",
                parents=["PROJECT"],
            ),
        }
    )
    currentProject.nodes["10"].run.steps = [
        FakeStep(index=1, name="importStep", status="finished"),
        FakeStep(index=2, name="processStep", status="running"),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {"protocolId": "10", "status": "running"},
        ],
        adjacencyMap={
            "10": {"parents": [], "children": []},
        },
        stepsByProtocolId={
            "10": [
                {
                    "index": 1,
                    "name": "importStep",
                    "status": "finished",
                },
                {
                    "index": 2,
                    "name": "processStep",
                    "status": "scheduled",
                },
                {
                    "index": 3,
                    "name": "extraStep",
                    "status": "new",
                },
            ],
        },
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"] == {
        "runtimeProtocols": 1,
        "postgresqlProtocols": 1,
        "runtimeDependencies": 0,
        "postgresqlDependencies": 0,
        "runtimeOutputs": 0,
        "postgresqlOutputs": 0,
        "runtimeSteps": 2,
        "postgresqlSteps": 3,
        "runtimeInputRefs": 0,
        "postgresqlInputRefs": 0,
        "runtimeInputRefDependencies": 0,
        "postgresqlInputRefDependencies": 0,
        "runtimeParams": 0,
        "postgresqlParams": 0,
        "issues": 2,
    }
    assert result["issues"]["missingSteps"] == []
    assert result["issues"]["extraSteps"] == [
        {
            "protocolId": "10",
            "index": 3,
            "name": "extraStep",
            "status": "new",
        }
    ]
    assert result["issues"]["stepMismatches"] == [
        {
            "protocolId": "10",
            "index": 2,
            "fields": ["status"],
            "runtimeName": "processStep",
            "postgresqlName": "processStep",
            "runtimeStatus": "running",
            "postgresqlStatus": "scheduled",
        }
    ]
    assert result["issues"]["missingProtocols"] == []
    assert result["issues"]["extraProtocols"] == []
    assert result["issues"]["statusMismatches"] == []
    assert result["issues"]["missingDependencies"] == []
    assert result["issues"]["extraDependencies"] == []
    assert result["issues"]["missingOutputs"] == []
    assert result["issues"]["extraOutputs"] == []
    assert result["issues"]["missingInputRefs"] == []
    assert result["issues"]["extraInputRefs"] == []
    assert result["issues"]["inputRefMismatches"] == []
    assert result["issues"]["runtimeInputRefDependenciesMissing"] == []
    assert result["issues"]["runtimeDependenciesWithoutInputRefs"] == []
    assert result["issues"]["postgresqlInputRefDependenciesMissing"] == []
    assert result["issues"]["postgresqlDependenciesWithoutInputRefs"] == []
    assert result["issues"]["missingParams"] == []
    assert result["issues"]["extraParams"] == []
    assert result["issues"]["paramValueMismatches"] == []
    assert result["issues"]["outputClassMismatches"] == []
    assert result["issues"]["outputMapperKindMismatches"] == []
    assert result["issues"]["outputItemsCountMismatches"] == []
    assert result["issues"]["protocolClassMismatches"] == []


def test_ValidateProjectPostgresqlConsistencyCollectsStepsForAllRuntimeProtocols(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="finished",
                parents=["PROJECT"],
            ),
            "11": FakeRunNode(
                "11",
                status="running",
                parents=["10"],
            ),
        }
    )
    currentProject.nodes["10"].run.outputs = [
        ("outputParticles", FakeOutput("SetOfParticles", itemsCount=1)),
    ]
    currentProject.nodes["11"].run.inputs = [
        ("inputParticles", FakePointer(parentProtocolId=10, outputName="outputParticles")),
    ]
    currentProject.nodes["10"].run.steps = [
        FakeStep(index=1, name="importStep", status="finished"),
    ]
    currentProject.nodes["11"].run.steps = [
        FakeStep(index=1, name="processStep", status="running"),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {"protocolId": "10", "status": "finished", "protocolClassName": "FakeProtocol"},
            {"protocolId": "11", "status": "running", "protocolClassName": "FakeProtocol"},
        ],
        adjacencyMap={
            "10": {"parents": [], "children": ["11"]},
            "11": {"parents": ["10"], "children": []},
        },
        stepsByProtocolId={
            "10": [
                {
                    "index": 1,
                    "name": "importStep",
                    "status": "finished",
                }
            ],
            "11": [
                {
                    "index": 1,
                    "name": "processStep",
                    "status": "running",
                }
            ],
        },
        inputRefs=[
            {
                "protocolId": "11",
                "inputName": "inputParticles",
                "itemIndex": 0,
                "parentProtocolId": "10",
                "parentOutputName": "outputParticles",
                "objectClassName": "SetOfParticles",
                "objectId": "100",
            },
        ],
        setRows=[
            makeSetRow(
                protocolId="10",
                outputName="outputParticles",
                setClassName="SetOfParticles",
                itemsCount=1,
            ),
        ],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is True
    assert result["summary"]["runtimeSteps"] == 2
    assert result["summary"]["postgresqlSteps"] == 2
    assert result["issues"]["missingSteps"] == []
    assert result["issues"]["extraSteps"] == []
    assert result["issues"]["stepMismatches"] == []
    assert result["summary"]["runtimeInputRefs"] == 1
    assert result["summary"]["postgresqlInputRefs"] == 1
    assert result["summary"]["runtimeInputRefDependencies"] == 1
    assert result["summary"]["postgresqlInputRefDependencies"] == 1

    assert result["issues"]["runtimeInputRefDependenciesMissing"] == []
    assert result["issues"]["runtimeDependenciesWithoutInputRefs"] == []
    assert result["issues"]["postgresqlInputRefDependenciesMissing"] == []
    assert result["issues"]["postgresqlDependenciesWithoutInputRefs"] == []
    assert result["issues"]["outputClassMismatches"] == []
    assert result["issues"]["outputMapperKindMismatches"] == []
    assert result["issues"]["outputItemsCountMismatches"] == []
    assert result["issues"]["protocolClassMismatches"] == []


def test_ValidateProjectPostgresqlConsistencyReportsInputRefMismatches(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="finished",
                parents=["PROJECT"],
            ),
            "11": FakeRunNode(
                "11",
                status="running",
                parents=["10"],
            ),
        }
    )
    currentProject.nodes["10"].run.outputs = [
        ("outputParticles", FakeOutput("SetOfParticles", itemsCount=1)),
    ]
    currentProject.nodes["11"].run.inputs = [
        ("inputParticles", FakePointer(parentProtocolId=10, outputName="outputParticles")),
        ("inputVolume", FakePointer(parentProtocolId=10, outputName="outputVolume", className="Volume")),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {"protocolId": "10", "status": "finished", "protocolClassName": "FakeProtocol"},
            {"protocolId": "11", "status": "running", "protocolClassName": "FakeProtocol"},
        ],
        adjacencyMap={
            "10": {"parents": [], "children": ["11"]},
            "11": {"parents": ["10"], "children": []},
        },
        inputRefs=[
            {
                "protocolId": "11",
                "inputName": "inputParticles",
                "itemIndex": 0,
                "parentProtocolId": "10",
                "parentOutputName": "wrongOutput",
                "objectClassName": "SetOfParticles",
                "objectId": "100",
            },
            {
                "protocolId": "11",
                "inputName": "inputMask",
                "itemIndex": 0,
                "parentProtocolId": "10",
                "parentOutputName": "outputMask",
                "objectClassName": "VolumeMask",
                "objectId": "101",
            },
        ],
        setRows=[
            makeSetRow(
                protocolId="10",
                outputName="outputParticles",
                setClassName="SetOfParticles",
                itemsCount=1,
            ),
        ],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"] == {
        "runtimeProtocols": 2,
        "postgresqlProtocols": 2,
        "runtimeDependencies": 1,
        "postgresqlDependencies": 1,
        "runtimeOutputs": 1,
        "postgresqlOutputs": 1,
        "runtimeSteps": 0,
        "postgresqlSteps": 0,
        "runtimeInputRefs": 2,
        "postgresqlInputRefs": 2,
        "runtimeInputRefDependencies": 1,
        "postgresqlInputRefDependencies": 1,
        "runtimeParams": 0,
        "postgresqlParams": 0,
        "issues": 5,
    }

    assert result["issues"]["missingInputRefs"] == [
        {
            "protocolId": "11",
            "inputName": "inputVolume",
            "itemIndex": 0,
            "parentProtocolId": "10",
            "parentOutputName": "outputVolume",
            "objectClassName": "Volume",
        }
    ]

    assert result["issues"]["extraInputRefs"] == [
        {
            "protocolId": "11",
            "inputName": "inputMask",
            "itemIndex": 0,
            "parentProtocolId": "10",
            "parentOutputName": "outputMask",
            "objectClassName": "VolumeMask",
        }
    ]

    assert result["issues"]["inputRefMismatches"] == [
        {
            "protocolId": "11",
            "inputName": "inputParticles",
            "itemIndex": 0,
            "fields": ["parentOutputName"],
            "runtimeParentProtocolId": "10",
            "postgresqlParentProtocolId": "10",
            "runtimeParentOutputName": "outputParticles",
            "postgresqlParentOutputName": "wrongOutput",
            "runtimeObjectClassName": "SetOfParticles",
            "postgresqlObjectClassName": "SetOfParticles",
        }
    ]
    assert result["issues"]["postgresqlInputRefsWithMissingParentProtocols"] == []
    assert result["issues"]["postgresqlInputRefsWithMissingParentOutputs"] == [
        {
            "protocolId": "11",
            "inputName": "inputMask",
            "itemIndex": 0,
            "parentProtocolId": "10",
            "parentOutputName": "outputMask",
            "objectClassName": "VolumeMask",
            "missingParentOutputName": "outputMask",
        },
        {
            "protocolId": "11",
            "inputName": "inputParticles",
            "itemIndex": 0,
            "parentProtocolId": "10",
            "parentOutputName": "wrongOutput",
            "objectClassName": "SetOfParticles",
            "missingParentOutputName": "wrongOutput",
        },
    ]

    assert result["issues"]["missingProtocols"] == []
    assert result["issues"]["extraProtocols"] == []
    assert result["issues"]["statusMismatches"] == []
    assert result["issues"]["missingDependencies"] == []
    assert result["issues"]["extraDependencies"] == []
    assert result["issues"]["missingOutputs"] == []
    assert result["issues"]["extraOutputs"] == []
    assert result["issues"]["missingSteps"] == []
    assert result["issues"]["extraSteps"] == []
    assert result["issues"]["stepMismatches"] == []
    assert result["issues"]["runtimeInputRefDependenciesMissing"] == []
    assert result["issues"]["runtimeDependenciesWithoutInputRefs"] == []
    assert result["issues"]["postgresqlInputRefDependenciesMissing"] == []
    assert result["issues"]["postgresqlDependenciesWithoutInputRefs"] == []
    assert result["issues"]["outputClassMismatches"] == []
    assert result["issues"]["outputMapperKindMismatches"] == []
    assert result["issues"]["outputItemsCountMismatches"] == []
    assert result["issues"]["protocolClassMismatches"] == []


def test_ValidateProjectPostgresqlConsistencyReportsInputRefsDependencyMismatches(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="finished",
                parents=["PROJECT"],
            ),
            "11": FakeRunNode(
                "11",
                status="running",
                parents=["10"],
            ),
            "12": FakeRunNode(
                "12",
                status="running",
                parents=[],
            ),
        }
    )
    currentProject.nodes["10"].run.outputs = [
        ("outputParticles", FakeOutput("SetOfParticles", itemsCount=1)),
        ("outputVolume", FakeOutput("Volume")),
    ]
    currentProject.nodes["11"].run.inputs = [
        ("inputParticles", FakePointer(parentProtocolId=10, outputName="outputParticles")),
    ]
    currentProject.nodes["12"].run.inputs = [
        ("inputVolume", FakePointer(parentProtocolId=10, outputName="outputVolume", className="Volume")),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {"protocolId": "10", "status": "finished", "protocolClassName": "FakeProtocol"},
            {"protocolId": "11", "status": "running", "protocolClassName": "FakeProtocol"},
            {"protocolId": "12", "status": "running", "protocolClassName": "FakeProtocol"},
        ],
        adjacencyMap={
            "10": {"parents": [], "children": ["11"]},
            "11": {"parents": ["10"], "children": []},
            "12": {"parents": [], "children": []},
        },
        inputRefs=[
            {
                "protocolId": "11",
                "inputName": "inputParticles",
                "itemIndex": 0,
                "parentProtocolId": "10",
                "parentOutputName": "outputParticles",
                "objectClassName": "SetOfParticles",
                "objectId": "100",
            },
            {
                "protocolId": "12",
                "inputName": "inputVolume",
                "itemIndex": 0,
                "parentProtocolId": "10",
                "parentOutputName": "outputVolume",
                "objectClassName": "Volume",
                "objectId": "101",
            },
        ],
        setRows=[
            makeSetRow(
                protocolId="10",
                outputName="outputParticles",
                setClassName="SetOfParticles",
                itemsCount=1,
            ),
        ],
        treeRows=[
            {
                "protocolId": "10",
                "id": 300,
                "scipionObjId": 400,
                "name": "outputVolume",
                "path": "outputVolume",
                "className": "Volume",
                "value": None,
                "label": None,
                "comment": None,
                "metadata": {},
                "createdAt": None,
                "updatedAt": None,
            },
        ],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"] == {
        "runtimeProtocols": 3,
        "postgresqlProtocols": 3,
        "runtimeDependencies": 1,
        "postgresqlDependencies": 1,
        "runtimeOutputs": 2,
        "postgresqlOutputs": 2,
        "runtimeSteps": 0,
        "postgresqlSteps": 0,
        "runtimeInputRefs": 2,
        "postgresqlInputRefs": 2,
        "runtimeInputRefDependencies": 2,
        "postgresqlInputRefDependencies": 2,
        "runtimeParams": 0,
        "postgresqlParams": 0,
        "issues": 2,
    }

    assert result["issues"]["runtimeInputRefDependenciesMissing"] == [
        {
            "parentId": "10",
            "childId": "12",
        }
    ]
    assert result["issues"]["runtimeDependenciesWithoutInputRefs"] == []
    assert result["issues"]["postgresqlInputRefDependenciesMissing"] == [
        {
            "parentId": "10",
            "childId": "12",
        }
    ]
    assert result["issues"]["postgresqlDependenciesWithoutInputRefs"] == []

    assert result["issues"]["missingProtocols"] == []
    assert result["issues"]["extraProtocols"] == []
    assert result["issues"]["statusMismatches"] == []
    assert result["issues"]["missingDependencies"] == []
    assert result["issues"]["extraDependencies"] == []
    assert result["issues"]["missingOutputs"] == []
    assert result["issues"]["extraOutputs"] == []
    assert result["issues"]["missingSteps"] == []
    assert result["issues"]["extraSteps"] == []
    assert result["issues"]["stepMismatches"] == []
    assert result["issues"]["missingInputRefs"] == []
    assert result["issues"]["extraInputRefs"] == []
    assert result["issues"]["inputRefMismatches"] == []
    assert result["issues"]["outputClassMismatches"] == []
    assert result["issues"]["outputMapperKindMismatches"] == []
    assert result["issues"]["outputItemsCountMismatches"] == []
    assert result["issues"]["protocolClassMismatches"] == []
    assert result["issues"]["postgresqlInputRefsWithMissingParentProtocols"] == []
    assert result["issues"]["postgresqlInputRefsWithMissingParentOutputs"] == []


def test_ValidateProjectPostgresqlConsistencyReportsParamMismatches(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="finished",
                parents=["PROJECT"],
            ),
        }
    )
    currentProject.nodes["10"].run.params = {
        "boxSize": 128,
        "threshold": 0.5,
    }
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {
                "protocolId": "10",
                "status": "finished",
                "params": {
                    "boxSize": 256,
                    "extraParam": "abc",
                },
            },
        ],
        adjacencyMap={
            "10": {"parents": [], "children": []},
        },
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"]["runtimeParams"] == 2
    assert result["summary"]["postgresqlParams"] == 2
    assert result["issues"]["missingParams"] == [
        {
            "protocolId": "10",
            "paramName": "threshold",
            "value": 0.5,
        }
    ]
    assert result["issues"]["extraParams"] == [
        {
            "protocolId": "10",
            "paramName": "extraParam",
            "value": "abc",
        }
    ]
    assert result["issues"]["paramValueMismatches"] == [
        {
            "protocolId": "10",
            "paramName": "boxSize",
            "runtimeValue": 128,
            "postgresqlValue": 256,
        }
    ]
    assert result["issues"]["outputMapperKindMismatches"] == []
    assert result["issues"]["outputItemsCountMismatches"] == []
    assert result["issues"]["protocolClassMismatches"] == []


def test_ValidateProjectPostgresqlConsistencyReportsOutputClassMismatches(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="finished",
                parents=["PROJECT"],
            ),
        }
    )
    currentProject.nodes["10"].run.outputs = [
        ("outputParticles", FakeOutput("SetOfParticles")),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {"protocolId": "10", "status": "finished", "protocolClassName": "FakeProtocol"},
        ],
        adjacencyMap={
            "10": {"parents": [], "children": []},
        },
        setRows=[
            {
                "protocolId": "10",
                "id": 100,
                "objectId": 200,
                "outputName": "outputParticles",
                "setClassName": "Volume",
                "itemClassName": "Particle",
                "properties": {"itemsCount": 12},
                "createdAt": None,
                "updatedAt": None,
            }
        ],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"]["runtimeOutputs"] == 1
    assert result["summary"]["postgresqlOutputs"] == 1
    assert result["summary"]["issues"] == 1
    assert result["issues"]["missingOutputs"] == []
    assert result["issues"]["extraOutputs"] == []
    assert result["issues"]["outputClassMismatches"] == [
        {
            "protocolId": "10",
            "outputName": "outputParticles",
            "runtimeClassName": "SetOfParticles",
            "postgresqlClassName": "Volume",
            "mapperKind": "flat_set",
        }
    ]
    assert result["issues"]["outputMapperKindMismatches"] == []
    assert result["issues"]["outputItemsCountMismatches"] == []
    assert result["issues"]["protocolClassMismatches"] == []


def test_ValidateProjectPostgresqlConsistencyReportsOutputMapperKindMismatches(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="finished",
                parents=["PROJECT"],
            ),
        }
    )
    currentProject.nodes["10"].run.outputs = [
        ("outputParticles", FakeOutput("SetOfParticles")),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {
                "protocolId": "10",
                "status": "finished",
            },
        ],
        adjacencyMap={
            "10": {"parents": [], "children": []},
        },
        treeRows=[
            {
                "protocolId": "10",
                "id": 300,
                "scipionObjId": 400,
                "name": "outputParticles",
                "path": "outputParticles",
                "className": "SetOfParticles",
                "value": None,
                "label": None,
                "comment": None,
                "metadata": {},
                "createdAt": None,
                "updatedAt": None,
            },
        ],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"]["runtimeOutputs"] == 1
    assert result["summary"]["postgresqlOutputs"] == 1
    assert result["summary"]["issues"] == 1

    assert result["issues"]["missingOutputs"] == []
    assert result["issues"]["extraOutputs"] == []
    assert result["issues"]["outputClassMismatches"] == []
    assert result["issues"]["outputMapperKindMismatches"] == [
        {
            "protocolId": "10",
            "outputName": "outputParticles",
            "className": "SetOfParticles",
            "expectedMapperKind": "flat_set",
            "postgresqlMapperKind": "tree",
        }
    ]
    assert result["issues"]["outputItemsCountMismatches"] == []
    assert result["issues"]["protocolClassMismatches"] == []


def test_ValidateProjectPostgresqlConsistencyReportsOutputItemsCountMismatches(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="finished",
                parents=["PROJECT"],
            ),
        }
    )
    currentProject.nodes["10"].run.outputs = [
        ("outputParticles", FakeOutput("SetOfParticles", itemsCount=12)),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {
                "protocolId": "10",
                "status": "finished",
            },
        ],
        adjacencyMap={
            "10": {"parents": [], "children": []},
        },
        setRows=[
            {
                "protocolId": "10",
                "id": 100,
                "objectId": 200,
                "outputName": "outputParticles",
                "setClassName": "SetOfParticles",
                "itemClassName": "Particle",
                "properties": {
                    "itemsCount": 10,
                },
                "createdAt": None,
                "updatedAt": None,
            }
        ],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"]["runtimeOutputs"] == 1
    assert result["summary"]["postgresqlOutputs"] == 1
    assert result["summary"]["issues"] == 1

    assert result["issues"]["missingOutputs"] == []
    assert result["issues"]["extraOutputs"] == []
    assert result["issues"]["outputClassMismatches"] == []
    assert result["issues"]["outputMapperKindMismatches"] == []
    assert result["issues"]["outputItemsCountMismatches"] == [
        {
            "protocolId": "10",
            "outputName": "outputParticles",
            "className": "SetOfParticles",
            "runtimeItemsCount": 12,
            "postgresqlItemsCount": 10,
            "mapperKind": "flat_set",
        }
    ]
    assert result["issues"]["protocolClassMismatches"] == []


def test_ValidateProjectPostgresqlConsistencyReportsFlatSetItemsTableCountMismatches(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="finished",
                parents=["PROJECT"],
            ),
        }
    )
    currentProject.nodes["10"].run.outputs = [
        ("outputParticles", FakeOutput("SetOfParticles", itemsCount=12)),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {
                "protocolId": "10",
                "status": "finished",
            },
        ],
        adjacencyMap={
            "10": {"parents": [], "children": []},
        },
        setRows=[
            makeSetRow(
                protocolId="10",
                outputName="outputParticles",
                setClassName="SetOfParticles",
                itemsCount=12,
                itemsTableCount=10,
            ),
        ],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"]["runtimeOutputs"] == 1
    assert result["summary"]["postgresqlOutputs"] == 1
    assert result["summary"]["issues"] == 1

    assert result["issues"]["outputItemsCountMismatches"] == []
    assert result["issues"]["postgresqlFlatSetItemsCountMismatches"] == [
        {
            "protocolId": "10",
            "outputName": "outputParticles",
            "mapperKind": "flat_set",
            "className": "SetOfParticles",
            "setId": 100,
            "rootObjectId": 200,
            "itemsCount": 12,
            "itemsTableCount": 10,
            "itemClassName": "Particle",
        }
    ]


def test_ValidateProjectPostgresqlConsistencyReportsProtocolClassMismatches(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="finished",
                parents=["PROJECT"],
            ),
        }
    )
    currentProject.nodes["10"].run.className = "RuntimeProtocolClass"
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {
                "protocolId": "10",
                "status": "finished",
                "protocolClassName": "PostgresqlProtocolClass",
            },
        ],
        adjacencyMap={
            "10": {"parents": [], "children": []},
        },
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"]["runtimeProtocols"] == 1
    assert result["summary"]["postgresqlProtocols"] == 1
    assert result["summary"]["issues"] == 1
    assert result["issues"]["protocolClassMismatches"] == [
        {
            "protocolId": "10",
            "runtimeClassName": "RuntimeProtocolClass",
            "postgresqlClassName": "PostgresqlProtocolClass",
        }
    ]


def test_ValidateProjectPostgresqlConsistencyReportsInputRefMissingParentProtocol(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "11": FakeRunNode("11", status="running", parents=["PROJECT"]),
        }
    )
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {"protocolId": "11", "status": "running", "protocolClassName": "FakeProtocol"},
        ],
        adjacencyMap={
            "11": {"parents": [], "children": []},
        },
        inputRefs=[
            {
                "protocolId": "11",
                "inputName": "inputParticles",
                "itemIndex": 0,
                "parentProtocolId": "99",
                "parentOutputName": "outputParticles",
                "objectClassName": "SetOfParticles",
                "objectId": "100",
            },
        ],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=False,
        checkPid=False,
    )

    assert result["ok"] is False
    assert result["issues"]["postgresqlInputRefsWithMissingParentProtocols"] == [
        {
            "protocolId": "11",
            "inputName": "inputParticles",
            "itemIndex": 0,
            "parentProtocolId": "99",
            "parentOutputName": "outputParticles",
            "objectClassName": "SetOfParticles",
            "missingParentProtocolId": "99",
        }
    ]
    assert result["issues"]["postgresqlInputRefsWithMissingParentOutputs"] == []


def test_ValidateProjectPostgresqlConsistencyReportsInputRefMissingParentOutput(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode("10", status="finished", parents=["PROJECT"]),
            "11": FakeRunNode("11", status="running", parents=["10"]),
        }
    )
    currentProject.nodes["10"].run.outputs = [
        ("outputParticles", FakeOutput("SetOfParticles")),
    ]
    currentProject.nodes["11"].run.inputs = [
        ("inputParticles", FakePointer(parentProtocolId=10, outputName="outputParticles")),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {"protocolId": "10", "status": "finished", "protocolClassName": "FakeProtocol"},
            {"protocolId": "11", "status": "running", "protocolClassName": "FakeProtocol"},
        ],
        adjacencyMap={
            "10": {"parents": [], "children": ["11"]},
            "11": {"parents": ["10"], "children": []},
        },
        inputRefs=[
            {
                "protocolId": "11",
                "inputName": "inputParticles",
                "itemIndex": 0,
                "parentProtocolId": "10",
                "parentOutputName": "outputParticles",
                "objectClassName": "SetOfParticles",
                "objectId": "100",
            },
        ],
        setRows=[],
        treeRows=[],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=False,
        checkPid=False,
    )

    assert result["ok"] is False
    assert result["issues"]["postgresqlInputRefsWithMissingParentProtocols"] == []
    assert result["issues"]["postgresqlInputRefsWithMissingParentOutputs"] == [
        {
            "protocolId": "11",
            "inputName": "inputParticles",
            "itemIndex": 0,
            "parentProtocolId": "10",
            "parentOutputName": "outputParticles",
            "objectClassName": "SetOfParticles",
            "missingParentOutputName": "outputParticles",
        }
    ]

def test_ValidateProjectPostgresqlConsistencyReportsIncompletePostgresqlOutputPayloads(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="finished",
                parents=["PROJECT"],
            ),
        }
    )
    currentProject.nodes["10"].run.outputs = [
        ("outputParticles", FakeOutput("SetOfParticles", itemsCount=None)),
        ("outputVolume", FakeOutput("Volume")),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {"protocolId": "10", "status": "finished", "protocolClassName": "FakeProtocol"},
        ],
        adjacencyMap={
            "10": {"parents": [], "children": []},
        },
        setRows=[
            makeSetRow(
                protocolId="10",
                outputName="outputParticles",
                setClassName="SetOfParticles",
                itemsCount=None,
            ),
        ],
        treeRows=[
            {
                "protocolId": "10",
                "id": None,
                "scipionObjId": 400,
                "name": "outputVolume",
                "path": "outputVolume",
                "className": "Volume",
                "value": None,
                "label": None,
                "comment": None,
                "metadata": {},
                "createdAt": None,
                "updatedAt": None,
            },
        ],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"]["runtimeOutputs"] == 2
    assert result["summary"]["postgresqlOutputs"] == 2
    assert result["summary"]["issues"] == 2

    assert result["issues"]["missingOutputs"] == []
    assert result["issues"]["extraOutputs"] == []
    assert result["issues"]["outputClassMismatches"] == []
    assert result["issues"]["outputMapperKindMismatches"] == []
    assert result["issues"]["outputItemsCountMismatches"] == []

    assert result["issues"]["postgresqlFlatSetOutputsWithIncompletePayload"] == [
        {
            "protocolId": "10",
            "outputName": "outputParticles",
            "mapperKind": "flat_set",
            "className": "SetOfParticles",
            "missingFields": ["itemsCount"],
            "setId": 100,
            "rootObjectId": 200,
            "itemsCount": None,
            "itemClassName": "Particle",
        }
    ]

    assert result["issues"]["postgresqlTreeOutputsWithIncompletePayload"] == [
        {
            "protocolId": "10",
            "outputName": "outputVolume",
            "mapperKind": "tree",
            "className": "Volume",
            "missingFields": ["rootObjectId"],
            "rootObjectId": None,
            "scipionObjId": 400,
        }
    ]


def test_ValidateProjectPostgresqlConsistencyReportsFlatSetMaxItemIdMismatches(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="finished",
                parents=["PROJECT"],
            ),
        }
    )
    currentProject.nodes["10"].run.outputs = [
        ("outputParticles", FakeOutput("SetOfParticles", itemsCount=3)),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {
                "protocolId": "10",
                "status": "finished",
            },
        ],
        adjacencyMap={
            "10": {"parents": [], "children": []},
        },
        setRows=[
            makeSetRow(
                protocolId="10",
                outputName="outputParticles",
                setClassName="SetOfParticles",
                itemsCount=3,
                itemsTableCount=3,
                maxItemId=20,
                maxItemIdFromItems=30,
            ),
        ],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"]["issues"] == 1
    assert result["issues"]["postgresqlFlatSetItemsCountMismatches"] == []
    assert result["issues"]["postgresqlFlatSetMaxItemIdMismatches"] == [
        {
            "protocolId": "10",
            "outputName": "outputParticles",
            "mapperKind": "flat_set",
            "className": "SetOfParticles",
            "setId": 100,
            "rootObjectId": 200,
            "maxItemId": 20,
            "maxItemIdFromItems": 30,
            "itemClassName": "Particle",
        }
    ]


def test_ValidateProjectPostgresqlConsistencyReportsMissingFlatSetRootTable(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="finished",
                parents=["PROJECT"],
            ),
        }
    )
    currentProject.nodes["10"].run.outputs = [
        ("outputParticles", FakeOutput("SetOfParticles", itemsCount=3)),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {
                "protocolId": "10",
                "status": "finished",
            },
        ],
        adjacencyMap={
            "10": {"parents": [], "children": []},
        },
        setRows=[
            makeSetRow(
                protocolId="10",
                outputName="outputParticles",
                setClassName="SetOfParticles",
                itemsCount=3,
                itemsTableCount=3,
                maxItemId=30,
                maxItemIdFromItems=30,
                rootTablesCount=0,
                rootTableId=None,
                rootTableItemsCount=0,
                rootTableMaxItemId=None,
                rootTableColumnsCount=0,
            ),
        ],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"]["issues"] == 1
    assert result["issues"]["postgresqlFlatSetRootTableMismatches"] == [
        {
            "protocolId": "10",
            "outputName": "outputParticles",
            "mapperKind": "flat_set",
            "className": "SetOfParticles",
            "setId": 100,
            "rootObjectId": 200,
            "rootTableId": None,
            "fields": ["rootTableMissing"],
            "rootTablesCount": 0,
            "itemsTableCount": 3,
            "rootTableItemsCount": 0,
            "maxItemIdFromItems": 30,
            "rootTableMaxItemId": None,
            "setColumnsCount": 2,
            "rootTableColumnsCount": 0,
            "itemClassName": "Particle",
        }
    ]


def test_ValidateProjectPostgresqlConsistencyReportsFlatSetColumnsCountMismatches(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="finished",
                parents=["PROJECT"],
            ),
        }
    )
    currentProject.nodes["10"].run.outputs = [
        ("outputParticles", FakeOutput("SetOfParticles", itemsCount=3)),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {
                "protocolId": "10",
                "status": "finished",
            },
        ],
        adjacencyMap={
            "10": {"parents": [], "children": []},
        },
        setRows=[
            makeSetRow(
                protocolId="10",
                outputName="outputParticles",
                setClassName="SetOfParticles",
                itemsCount=3,
                itemsTableCount=3,
                maxItemId=30,
                maxItemIdFromItems=30,
                columnsCount=5,
                setColumnsCount=4,
            ),
        ],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"]["runtimeOutputs"] == 1
    assert result["summary"]["postgresqlOutputs"] == 1
    assert result["summary"]["issues"] == 1

    assert result["issues"]["postgresqlFlatSetColumnsCountMismatches"] == [
        {
            "protocolId": "10",
            "outputName": "outputParticles",
            "mapperKind": "flat_set",
            "className": "SetOfParticles",
            "setId": 100,
            "rootObjectId": 200,
            "columnsCount": 5,
            "setColumnsCount": 4,
            "itemClassName": "Particle",
        }
    ]
    assert result["issues"]["postgresqlFlatSetItemsCountMismatches"] == []
    assert result["issues"]["postgresqlFlatSetMaxItemIdMismatches"] == []
    assert result["issues"]["postgresqlFlatSetRootTableMismatches"] == []


def test_ValidateProjectPostgresqlConsistencyReportsRootTableColumnsCountMismatches(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="finished",
                parents=["PROJECT"],
            ),
        }
    )
    currentProject.nodes["10"].run.outputs = [
        ("outputParticles", FakeOutput("SetOfParticles", itemsCount=3)),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {
                "protocolId": "10",
                "status": "finished",
            },
        ],
        adjacencyMap={
            "10": {"parents": [], "children": []},
        },
        setRows=[
            makeSetRow(
                protocolId="10",
                outputName="outputParticles",
                setClassName="SetOfParticles",
                itemsCount=3,
                itemsTableCount=3,
                maxItemId=30,
                maxItemIdFromItems=30,
                columnsCount=5,
                setColumnsCount=5,
                rootTablesCount=1,
                rootTableId=500,
                rootTableItemsCount=3,
                rootTableMaxItemId=30,
                rootTableColumnsCount=4,
            ),
        ],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"]["issues"] == 1
    assert result["issues"]["postgresqlFlatSetRootTableMismatches"] == [
        {
            "protocolId": "10",
            "outputName": "outputParticles",
            "mapperKind": "flat_set",
            "className": "SetOfParticles",
            "setId": 100,
            "rootObjectId": 200,
            "rootTableId": 500,
            "fields": ["rootTableColumnsCount"],
            "rootTablesCount": 1,
            "itemsTableCount": 3,
            "rootTableItemsCount": 3,
            "maxItemIdFromItems": 30,
            "rootTableMaxItemId": 30,
            "setColumnsCount": 5,
            "rootTableColumnsCount": 4,
            "itemClassName": "Particle",
        }
    ]
    assert result["issues"]["postgresqlFlatSetColumnsCountMismatches"] == []
    assert result["issues"]["postgresqlFlatSetItemsCountMismatches"] == []
    assert result["issues"]["postgresqlFlatSetMaxItemIdMismatches"] == []

def test_ValidateProjectPostgresqlConsistencyReportsRootTableColumnSchemaMismatches(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="finished",
                parents=["PROJECT"],
            ),
        }
    )
    currentProject.nodes["10"].run.outputs = [
        ("outputParticles", FakeOutput("SetOfParticles", itemsCount=3)),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    setColumnsSignature = [
        {
            "labelProperty": "_id",
            "columnName": "id",
            "className": "Integer",
            "valueType": "int",
            "position": 0,
            "indexed": True,
        },
        {
            "labelProperty": "_enabled",
            "columnName": "enabled",
            "className": "Boolean",
            "valueType": "bool",
            "position": 1,
            "indexed": False,
        },
    ]

    rootTableColumnsSignature = [
        {
            "labelProperty": "_id",
            "columnName": "id",
            "className": "Integer",
            "valueType": "int",
            "position": 0,
            "indexed": True,
        },
        {
            "labelProperty": "_enabled",
            "columnName": "wrong_enabled",
            "className": "Boolean",
            "valueType": "bool",
            "position": 1,
            "indexed": False,
        },
    ]

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {
                "protocolId": "10",
                "status": "finished",
            },
        ],
        adjacencyMap={
            "10": {"parents": [], "children": []},
        },
        setRows=[
            makeSetRow(
                protocolId="10",
                outputName="outputParticles",
                setClassName="SetOfParticles",
                itemsCount=3,
                itemsTableCount=3,
                maxItemId=30,
                maxItemIdFromItems=30,
                columnsCount=2,
                setColumnsCount=2,
                rootTablesCount=1,
                rootTableId=500,
                rootTableItemsCount=3,
                rootTableMaxItemId=30,
                rootTableColumnsCount=2,
                setColumnsSignature=setColumnsSignature,
                rootTableColumnsSignature=rootTableColumnsSignature,
            ),
        ],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"]["issues"] == 1
    assert result["issues"]["postgresqlFlatSetRootTableMismatches"] == [
        {
            "protocolId": "10",
            "outputName": "outputParticles",
            "mapperKind": "flat_set",
            "className": "SetOfParticles",
            "setId": 100,
            "rootObjectId": 200,
            "rootTableId": 500,
            "fields": ["rootTableColumnsSignature"],
            "rootTablesCount": 1,
            "itemsTableCount": 3,
            "rootTableItemsCount": 3,
            "maxItemIdFromItems": 30,
            "rootTableMaxItemId": 30,
            "setColumnsCount": 2,
            "rootTableColumnsCount": 2,
            "setColumnsSignature": setColumnsSignature,
            "rootTableColumnsSignature": rootTableColumnsSignature,
            "itemClassName": "Particle",
        }
    ]


def test_ValidateProjectPostgresqlConsistencyReportsRootTableItemsIdSignatureMismatches(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="finished",
                parents=["PROJECT"],
            ),
        }
    )
    currentProject.nodes["10"].run.outputs = [
        ("outputParticles", FakeOutput("SetOfParticles", itemsCount=3)),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {
                "protocolId": "10",
                "status": "finished",
            },
        ],
        adjacencyMap={
            "10": {"parents": [], "children": []},
        },
        setRows=[
            makeSetRow(
                protocolId="10",
                outputName="outputParticles",
                setClassName="SetOfParticles",
                itemsCount=3,
                itemsTableCount=3,
                maxItemId=30,
                maxItemIdFromItems=30,
                rootTablesCount=1,
                rootTableId=500,
                rootTableItemsCount=3,
                rootTableMaxItemId=30,
                itemsIdSignature="items-10-20-30",
                rootTableItemsIdSignature="items-10-25-30",
            ),
        ],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"]["issues"] == 1
    assert result["issues"]["postgresqlFlatSetRootTableMismatches"] == [
        {
            "protocolId": "10",
            "outputName": "outputParticles",
            "mapperKind": "flat_set",
            "className": "SetOfParticles",
            "setId": 100,
            "rootObjectId": 200,
            "rootTableId": 500,
            "fields": ["rootTableItemsIdSignature"],
            "rootTablesCount": 1,
            "itemsTableCount": 3,
            "rootTableItemsCount": 3,
            "maxItemIdFromItems": 30,
            "rootTableMaxItemId": 30,
            "setColumnsCount": 2,
            "rootTableColumnsCount": 2,
            "itemsIdSignature": "items-10-20-30",
            "rootTableItemsIdSignature": "items-10-25-30",
            "itemClassName": "Particle",
        }
    ]

def test_ValidateProjectPostgresqlConsistencyReportsRootTableItemsValueSignatureMismatches(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="finished",
                parents=["PROJECT"],
            ),
        }
    )
    currentProject.nodes["10"].run.outputs = [
        ("outputParticles", FakeOutput("SetOfParticles", itemsCount=3)),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {
                "protocolId": "10",
                "status": "finished",
            },
        ],
        adjacencyMap={
            "10": {"parents": [], "children": []},
        },
        setRows=[
            makeSetRow(
                protocolId="10",
                outputName="outputParticles",
                setClassName="SetOfParticles",
                itemsCount=3,
                itemsTableCount=3,
                maxItemId=30,
                maxItemIdFromItems=30,
                rootTablesCount=1,
                rootTableId=500,
                rootTableItemsCount=3,
                rootTableMaxItemId=30,
                itemsIdSignature="items-10-20-30",
                rootTableItemsIdSignature="items-10-20-30",
                itemsValueSignature="values-original",
                rootTableItemsValueSignature="values-corrupted",
            ),
        ],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"]["issues"] == 1
    assert result["issues"]["postgresqlFlatSetRootTableMismatches"] == [
        {
            "protocolId": "10",
            "outputName": "outputParticles",
            "mapperKind": "flat_set",
            "className": "SetOfParticles",
            "setId": 100,
            "rootObjectId": 200,
            "rootTableId": 500,
            "fields": ["rootTableItemsValueSignature"],
            "rootTablesCount": 1,
            "itemsTableCount": 3,
            "rootTableItemsCount": 3,
            "maxItemIdFromItems": 30,
            "rootTableMaxItemId": 30,
            "setColumnsCount": 2,
            "rootTableColumnsCount": 2,
            "itemsValueSignature": "values-original",
            "rootTableItemsValueSignature": "values-corrupted",
            "itemClassName": "Particle",
        }
    ]

def test_ValidateProjectPostgresqlConsistencyReportsFlatSetPropertiesMismatches(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="finished",
                parents=["PROJECT"],
            ),
        }
    )
    currentProject.nodes["10"].run.outputs = [
        ("outputParticles", FakeOutput("SetOfParticles", itemsCount=3)),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    propertiesPayloadSignature = [
        {
            "key": "columnsCount",
            "value": "2",
        },
        {
            "key": "itemsCount",
            "value": "3",
        },
        {
            "key": "nestedTablesVersion",
            "value": "14",
        },
    ]
    setPropertiesSignature = [
        {
            "key": "columnsCount",
            "value": "2",
        },
        {
            "key": "itemsCount",
            "value": "4",
        },
        {
            "key": "nestedTablesVersion",
            "value": "14",
        },
    ]

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {
                "protocolId": "10",
                "status": "finished",
            },
        ],
        adjacencyMap={
            "10": {"parents": [], "children": []},
        },
        setRows=[
            makeSetRow(
                protocolId="10",
                outputName="outputParticles",
                setClassName="SetOfParticles",
                itemsCount=3,
                itemsTableCount=3,
                maxItemId=30,
                maxItemIdFromItems=30,
                propertiesPayloadSignature=propertiesPayloadSignature,
                setPropertiesSignature=setPropertiesSignature,
            ),
        ],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"]["issues"] == 1
    assert result["issues"]["postgresqlFlatSetPropertiesMismatches"] == [
        {
            "protocolId": "10",
            "outputName": "outputParticles",
            "mapperKind": "flat_set",
            "className": "SetOfParticles",
            "setId": 100,
            "rootObjectId": 200,
            "fields": ["setPropertiesSignature"],
            "propertiesPayloadCount": 3,
            "setPropertiesCount": 3,
            "propertiesPayloadSignature": propertiesPayloadSignature,
            "setPropertiesSignature": setPropertiesSignature,
            "itemClassName": "Particle",
        }
    ]


def test_ValidateProjectPostgresqlConsistencyReportsFlatSetRootObjectMismatches(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="finished",
                parents=["PROJECT"],
            ),
        }
    )
    currentProject.nodes["10"].run.outputs = [
        ("outputParticles", FakeOutput("SetOfParticles", itemsCount=3)),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {
                "id": 1000,
                "protocolId": "10",
                "status": "finished",
            },
        ],
        adjacencyMap={
            "10": {"parents": [], "children": []},
        },
        setRows=[
            makeSetRow(
                protocolId="10",
                protocolDbId=1000,
                outputName="outputParticles",
                setClassName="SetOfParticles",
                itemsCount=3,
                itemsTableCount=3,
                maxItemId=30,
                maxItemIdFromItems=30,
                rootObjectProjectId=2,
                rootObjectProtocolDbId=9999,
                rootObjectParentObjectId=123,
                rootObjectName="wrongName",
                rootObjectPath="wrongPath",
                rootObjectClassName="WrongSetClass",
            ),
        ],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"]["issues"] == 1
    assert result["issues"]["postgresqlFlatSetRootObjectMismatches"] == [
        {
            "protocolId": "10",
            "outputName": "outputParticles",
            "mapperKind": "flat_set",
            "className": "SetOfParticles",
            "setId": 100,
            "rootObjectId": 200,
            "fields": [
                "rootObjectProjectId",
                "rootObjectProtocolDbId",
                "rootObjectParentObjectId",
                "rootObjectName",
                "rootObjectPath",
                "rootObjectClassName",
            ],
            "protocolDbId": 1000,
            "rootObjectDbId": 200,
            "rootObjectProjectId": 2,
            "rootObjectProtocolDbId": 9999,
            "rootObjectParentObjectId": 123,
            "rootObjectName": "wrongName",
            "rootObjectPath": "wrongPath",
            "rootObjectClassName": "WrongSetClass",
            "itemClassName": "Particle",
        }
    ]

def test_ValidateProjectPostgresqlConsistencyReportsMissingFlatSetRootObject(
    service,
    monkeypatch,
    tmp_path,
):
    currentProject = FakeCurrentProject(
        nodes={
            "PROJECT": FakeRunNode("PROJECT"),
            "10": FakeRunNode(
                "10",
                status="finished",
                parents=["PROJECT"],
            ),
        }
    )
    currentProject.nodes["10"].run.outputs = [
        ("outputParticles", FakeOutput("SetOfParticles", itemsCount=3)),
    ]
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {
                "id": 1000,
                "protocolId": "10",
                "status": "finished",
            },
        ],
        adjacencyMap={
            "10": {"parents": [], "children": []},
        },
        setRows=[
            makeSetRow(
                protocolId="10",
                protocolDbId=1000,
                outputName="outputParticles",
                setClassName="SetOfParticles",
                itemsCount=3,
                itemsTableCount=3,
                maxItemId=30,
                maxItemIdFromItems=30,
                rootObjectDbId=None,
            ),
        ],
    )

    result = service.validateProjectPostgresqlConsistency(
        mapper=mapper,
        projectId=1,
        currentUser={"id": 7},
        refresh=True,
        checkPid=True,
    )

    assert result["ok"] is False
    assert result["summary"]["issues"] == 1
    assert result["issues"]["postgresqlFlatSetRootObjectMismatches"] == [
        {
            "protocolId": "10",
            "outputName": "outputParticles",
            "mapperKind": "flat_set",
            "className": "SetOfParticles",
            "setId": 100,
            "rootObjectId": 200,
            "fields": ["rootObjectMissing"],
            "protocolDbId": 1000,
            "rootObjectDbId": None,
            "rootObjectProjectId": 1,
            "rootObjectProtocolDbId": 1000,
            "rootObjectParentObjectId": None,
            "rootObjectName": "outputParticles",
            "rootObjectPath": "outputParticles",
            "rootObjectClassName": "SetOfParticles",
            "itemClassName": "Particle",
        }
    ]