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


class FakeProtocol:
    def __init__(self, status, outputs=None, steps=None):
        self.status = status
        self.outputs = outputs or []
        self.steps = steps or []

    def getStatus(self):
        return self.status

    def iterOutputAttributes(self):
        return list(self.outputs)

    def loadSteps(self):
        return list(self.steps)


class FakeOutput:
    def __init__(self, className):
        self.className = className

    def getClassName(self):
        return self.className


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
    ):
        self.projectRow = projectRow
        self.protocolRows = protocolRows
        self.adjacencyMap = adjacencyMap
        self.stepsByProtocolId = stepsByProtocolId or {}
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
    patchRuntimeProject(service, monkeypatch, currentProject)

    mapper = FakeMapper(
        projectRow={
            "id": 1,
            "ownerId": 7,
            "name": str(tmp_path),
        },
        protocolRows=[
            {"protocolId": "10", "status": "finished"},
            {"protocolId": "11", "status": "running"},
        ],
        adjacencyMap={
            "10": {"parents": [], "children": ["11"]},
            "11": {"parents": ["10"], "children": []},
        },
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
        "runtimeOutputs": 0,
        "postgresqlOutputs": 0,
        "runtimeSteps": 0,
        "postgresqlSteps": 0,
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
        "issues": 5,
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
            {"protocolId": "10", "status": "finished"},
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
            {"protocolId": "10", "status": "finished"},
            {"protocolId": "11", "status": "running"},
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