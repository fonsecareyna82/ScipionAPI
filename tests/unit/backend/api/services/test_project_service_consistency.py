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
    def __init__(self, status):
        self.status = status

    def getStatus(self):
        return self.status


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
    def __init__(self, projectRow, protocolRows, adjacencyMap):
        self.projectRow = projectRow
        self.protocolRows = protocolRows
        self.adjacencyMap = adjacencyMap

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
        "issues": 0,
    }
    assert result["issues"] == {
        "missingProtocols": [],
        "extraProtocols": [],
        "statusMismatches": [],
        "missingDependencies": [],
        "extraDependencies": [],
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
    }