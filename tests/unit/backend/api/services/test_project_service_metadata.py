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

import numpy as np
import pytest


class IntRenderer:
    # intRenderer
    def render(self, rawValue, rowValues):
        return int(rawValue)


class FloatRenderer:
    # floatRenderer
    def __init__(self, decimals=2):
        self._decimals = decimals

    def render(self, rawValue, rowValues):
        return float(rawValue)

    def getDecimalsNumber(self):
        return self._decimals


class StrRenderer:
    # strRenderer
    def render(self, rawValue, rowValues):
        return str(rawValue)


class ImageRenderer:
    # imageRenderer
    def __init__(self):
        self.size = None
        self.applyTransform = None

    def render(self, rawValue, rowValues):
        return rawValue

    def setSize(self, size):
        self.size = size

    def setApplyTransformation(self, value):
        self.applyTransform = value


class MatrixRender:
    # matrixRender
    def render(self, rawValue, rowValues):
        return np.asarray(rawValue)

    def hasTransformation(self):
        return True


class FakeColumn:
    # fakeColumn
    def __init__(self, name, alias, renderer, sortable=True):
        self._name = name
        self._alias = alias
        self._renderer = renderer
        self._sortable = sortable
        self._index = None

    def getName(self):
        return self._name

    def getAlias(self):
        return self._alias

    def getRenderer(self):
        return self._renderer

    def isSorteable(self):
        return self._sortable

    def setIndex(self, idx):
        self._index = idx


class FakeRow:
    # fakeRow
    def __init__(self, rowId, values):
        self._rowId = rowId
        self._values = values

    def getId(self):
        return self._rowId

    def getValues(self):
        return list(self._values)


class FakeSelection:
    # fakeSelection
    def __init__(self, keys=None):
        self._keys = keys or {}

    def isEmpty(self):
        return len(self._keys) == 0

    def getSelection(self):
        return self._keys


class FakeAction:
    # fakeAction
    def __init__(self, name):
        self._name = name

    def getName(self):
        return self._name


class FakeTable:
    # fakeTable
    def __init__(
        self,
        name,
        alias,
        columns,
        hasColumnId=True,
        actions=None,
        selection=None,
    ):
        self._name = name
        self._alias = alias
        self._columns = list(columns)
        self._hasColumnId = hasColumnId
        self._actions = actions or []
        self._selection = selection or FakeSelection()
        self.sortBy = None
        self.sortAsc = None

    def getName(self):
        return self._name

    def getAlias(self):
        return self._alias

    def getColumns(self):
        return list(self._columns)

    def hasColumnId(self):
        return self._hasColumnId

    def getActions(self):
        return list(self._actions)

    def getColumnIndexFromLabel(self, columnName):
        for idx, col in enumerate(self._columns):
            if col.getName() == columnName:
                return idx
        return -1

    def getSelection(self):
        return self._selection

    def setSortingColumn(self, value):
        self.sortBy = value

    def setSortingAsc(self, value):
        self.sortAsc = value


class FakeDao:
    # fakeDao
    def __init__(self, objectsType=None, actionAliases=None):
        self._objectsType = objectsType or {"create subset": "SetOfParticles"}
        self._actionAliases = actionAliases or {}
        self.fillTableCalls = []

    def fillTable(self, table, objMgr):
        self.fillTableCalls.append(
            {
                "table": table,
                "objMgr": objMgr,
            }
        )

    def _getActionAliasForTableName(self, tableName):
        return self._actionAliases.get(tableName, "")


class FakeObjectManager:
    # fakeObjectManager
    def __init__(self, tables, rowsByTable, rowCounts=None, dao=None, fileName=""):
        self._tables = tables
        self._rowsByTable = rowsByTable
        self._rowCounts = rowCounts or {}
        self._dao = dao or FakeDao()
        self._fileName = fileName

    def getTables(self):
        return self._tables

    def getTable(self, tableName):
        return self._tables.get(tableName)

    def getTableRowCount(self, tableName):
        if tableName in self._rowCounts:
            return self._rowCounts[tableName]
        return len(self._rowsByTable.get(tableName, []))

    def getRows(self, tableName, offset, limit):
        rows = self._rowsByTable.get(tableName, [])
        return rows[offset:offset + limit]

    def getDAO(self):
        return self._dao


class FakeOutput:
    # fakeOutput
    def __init__(self, fileName):
        self._fileName = fileName

    def getFileName(self):
        return self._fileName


class FakeProtocol:
    # fakeProtocol
    def __init__(self, outputName, output):
        setattr(self, outputName, output)
        self.newProtocolCalls = []
        self.launchProtocolCalls = []

    def newProtocol(self, *args, **kwargs):
        self.newProtocolCalls.append(
            {
                "args": args,
                "kwargs": kwargs,
            }
        )
        return {"batchProtocol": True, "kwargs": kwargs}


class FakeCurrentProject:
    # fakeCurrentProject
    def __init__(self, protocol, projectPath=None):
        self._protocol = protocol
        self._projectPath = projectPath
        self.launchedProtocols = []

    def getProtocol(self, protocolId):
        return self._protocol

    def getPath(self):
        if self._projectPath is None:
            raise AttributeError("Project path is not set")
        return str(self._projectPath)

    def newProtocol(self, *args, **kwargs):
        return self._protocol.newProtocol(*args, **kwargs)

    def launchProtocol(self, protocol):
        self.launchedProtocols.append(protocol)


@pytest.fixture
def projectServiceModule(authTestEnv):
    # projectServiceModule
    return importlib.import_module("app.backend.api.services.project_service")


@pytest.fixture
def service(projectServiceModule, tmp_path):
    # service
    outputFile = tmp_path / "metadata.sqlite"
    outputFile.write_text("placeholder", encoding="utf-8")

    output = FakeOutput(str(outputFile))
    protocol = FakeProtocol("outputParticles", output)

    instance = object.__new__(projectServiceModule.ProjectService)
    instance.currentProject = FakeCurrentProject(protocol, projectPath=tmp_path)
    instance.tomoList = {}
    return instance


def patchOpenMetadataTable(service, monkeypatch, objMgr, table, calls=None):
    # patchOpenMetadataTable
    def openMetadataTable(projectId, protocolId, outputName, tableName, mapper=None):
        if calls is not None:
            calls.append(
                {
                    "projectId": projectId,
                    "protocolId": protocolId,
                    "outputName": outputName,
                    "tableName": tableName,
                    "mapper": mapper,
                }
            )
        return objMgr, table

    monkeypatch.setattr(service, "_openMetadataTable", openMetadataTable)


def patchObjectManagerForOutput(service, monkeypatch, objMgr, calls=None):
    # patchObjectManagerForOutput
    def getMetadataObjectManagerForOutput(projectId, protocolId, outputName, mapper=None):
        if calls is not None:
            calls.append(
                {
                    "projectId": projectId,
                    "protocolId": protocolId,
                    "outputName": outputName,
                    "mapper": mapper,
                }
            )
        return objMgr

    monkeypatch.setattr(
        service,
        "_getMetadataObjectManagerForOutput",
        getMetadataObjectManagerForOutput,
    )


def test_ListOutputMetadataTablesServiceReturnsSummaries(service, monkeypatch):
    tables = {
        "objects": FakeTable(
            name="objects",
            alias="Particles",
            columns=[],
            hasColumnId=True,
        ),
        "classes": FakeTable(
            name="classes",
            alias="Class2D",
            columns=[],
            hasColumnId=False,
        ),
    }
    objMgr = FakeObjectManager(
        tables=tables,
        rowsByTable={"objects": [], "classes": []},
        rowCounts={"objects": 11, "classes": 3},
    )
    mapper = object()
    calls = []

    patchObjectManagerForOutput(service, monkeypatch, objMgr, calls=calls)

    result = service.listOutputMetadataTablesService(
        projectId=1,
        protocolId=10,
        outputName="outputParticles",
        mapper=mapper,
    )

    assert calls == [
        {
            "projectId": 1,
            "protocolId": 10,
            "outputName": "outputParticles",
            "mapper": mapper,
        }
    ]
    assert result == [
        {
            "name": "objects",
            "alias": "Particles",
            "rowCount": 11,
            "hasColumnId": True,
        },
        {
            "name": "classes",
            "alias": "Class2D",
            "rowCount": 3,
            "hasColumnId": False,
        },
    ]


def test_GetMetadataTableSchemaServiceBuildsColumns(service, monkeypatch):
    columns = [
        FakeColumn("id", "Id", IntRenderer(), sortable=True),
        FakeColumn("score", "Score", FloatRenderer(decimals=4), sortable=False),
        FakeColumn("image", "Image", ImageRenderer(), sortable=True),
        FakeColumn("matrix", "Matrix", MatrixRender(), sortable=True),
    ]
    table = FakeTable(
        name="objects",
        alias="Particles",
        columns=columns,
        hasColumnId=True,
    )
    objMgr = FakeObjectManager(
        tables={"objects": table},
        rowsByTable={"objects": []},
    )
    mapper = object()
    calls = []

    patchOpenMetadataTable(service, monkeypatch, objMgr, table, calls=calls)

    result = service.getMetadataTableSchemaService(
        projectId=1,
        protocolId=10,
        outputName="outputParticles",
        tableName="objects",
        mapper=mapper,
    )

    assert calls == [
        {
            "projectId": 1,
            "protocolId": 10,
            "outputName": "outputParticles",
            "tableName": "objects",
            "mapper": mapper,
        }
    ]
    assert result["name"] == "objects"
    assert result["alias"] == "Particles"
    assert result["hasColumnId"] is True
    assert result["actions"] == []
    assert result["columns"] == [
        {
            "name": "id",
            "alias": "Id",
            "index": 0,
            "sortable": True,
            "visible": True,
            "rendererType": "int",
            "decimals": None,
            "hasTransformation": False,
        },
        {
            "name": "score",
            "alias": "Score",
            "index": 1,
            "sortable": False,
            "visible": True,
            "rendererType": "float",
            "decimals": 4,
            "hasTransformation": False,
        },
        {
            "name": "image",
            "alias": "Image",
            "index": 2,
            "sortable": True,
            "visible": True,
            "rendererType": "image",
            "decimals": None,
            "hasTransformation": False,
        },
        {
            "name": "matrix",
            "alias": "Matrix",
            "index": 3,
            "sortable": True,
            "visible": True,
            "rendererType": "matrix",
            "decimals": None,
            "hasTransformation": True,
        },
    ]


def test_GetMetadataTableSchemaServiceReturnsActionsForChildTables(service, monkeypatch):
    table = FakeTable(
        name="Class001_Objects",
        alias="Class001_Particle",
        columns=[],
        actions=[FakeAction("Particle"), FakeAction("Particle")],
    )
    objMgr = FakeObjectManager(
        tables={"Class001_Objects": table},
        rowsByTable={"Class001_Objects": []},
    )

    patchOpenMetadataTable(service, monkeypatch, objMgr, table)

    result = service.getMetadataTableSchemaService(
        projectId=1,
        protocolId=10,
        outputName="outputParticles",
        tableName="Class001_Objects",
        mapper=object(),
    )

    assert result["name"] == "Class001_Objects"
    assert result["alias"] == "Class001_Particle"
    assert result["actions"] == ["Particle"]


def test_GetMetadataTableSchemaServiceDoesNotReturnActionsForProperties(service, monkeypatch):
    table = FakeTable(
        name="Properties",
        alias="Properties",
        columns=[FakeColumn("key", "key", StrRenderer())],
        actions=[FakeAction("Particle")],
    )
    objMgr = FakeObjectManager(
        tables={"Properties": table},
        rowsByTable={"Properties": []},
    )

    patchOpenMetadataTable(service, monkeypatch, objMgr, table)

    result = service.getMetadataTableSchemaService(
        projectId=1,
        protocolId=10,
        outputName="outputParticles",
        tableName="Properties",
        mapper=object(),
    )

    assert result["name"] == "Properties"
    assert result["alias"] == "Properties"
    assert result["actions"] == []


def test_ResolveMetadataActionOutputClassNameReturnsSetOfVolumesForClass3D(service):
    table = FakeTable(
        name="objects",
        alias="SetOfClasses3D",
        columns=[],
        actions=[FakeAction("Volumes")],
    )
    dao = FakeDao(
        objectsType={},
        actionAliases={"objects": "Class3D"},
    )

    result = service._resolveMetadataActionOutputClassName(
        dao=dao,
        table=table,
        action="Volumes",
    )

    assert result == "SetOfVolumes"


def test_ResolveMetadataActionOutputClassNameReturnsSetOfAveragesForClass2D(service):
    table = FakeTable(
        name="objects",
        alias="SetOfClasses2D",
        columns=[],
        actions=[FakeAction("Averages")],
    )
    dao = FakeDao(
        objectsType={},
        actionAliases={"objects": "Class2D"},
    )

    result = service._resolveMetadataActionOutputClassName(
        dao=dao,
        table=table,
        action="Averages",
    )

    assert result == "SetOfAverages"


def test_ResolveMetadataActionOutputClassNameUsesDaoObjectsType(service):
    table = FakeTable(
        name="objects",
        alias="Particles",
        columns=[],
        actions=[FakeAction("Particle")],
    )
    dao = FakeDao(objectsType={"Particle": "SetOfParticles"})

    result = service._resolveMetadataActionOutputClassName(
        dao=dao,
        table=table,
        action="Particle",
    )

    assert result == "SetOfParticles"


def test_GetMetadataTablePageServiceConvertsCells(service, monkeypatch):
    columns = [
        FakeColumn("id", "Id", IntRenderer()),
        FakeColumn("label", "Label", StrRenderer()),
        FakeColumn("image", "Image", ImageRenderer()),
        FakeColumn("matrix", "Matrix", MatrixRender()),
    ]
    row = FakeRow(7, [1, "particle-001", "thumb.png", [[1, 2], [3, 4]]])
    table = FakeTable(name="objects", alias="Particles", columns=columns)
    objMgr = FakeObjectManager(
        tables={"objects": table},
        rowsByTable={"objects": [row]},
        rowCounts={"objects": 1},
    )

    patchOpenMetadataTable(service, monkeypatch, objMgr, table)

    result = service.getMetadataTablePageService(
        projectId=1,
        protocolId=10,
        outputName="outputParticles",
        tableName="objects",
        page=1,
        pageSize=20,
        sortBy="id",
        asc=True,
        selectionOnly=False,
        mapper=object(),
    )

    assert result == {
        "pageNumber": 1,
        "pageSize": 20,
        "totalRows": 1,
        "rows": [
            {
                "id": 7,
                "values": [
                    1,
                    "particle-001",
                    {"kind": "image", "path": "thumb.png"},
                    {"kind": "matrix", "value": [[1, 2], [3, 4]]},
                ],
            }
        ],
    }


def test_GetMetadataTableWindowServiceReturnsOffsetWindow(service, monkeypatch):
    columns = [
        FakeColumn("id", "Id", IntRenderer()),
        FakeColumn("label", "Label", StrRenderer()),
    ]
    rows = [
        FakeRow(1, [1, "row-1"]),
        FakeRow(2, [2, "row-2"]),
        FakeRow(3, [3, "row-3"]),
    ]
    table = FakeTable(name="objects", alias="Particles", columns=columns)
    objMgr = FakeObjectManager(
        tables={"objects": table},
        rowsByTable={"objects": rows},
        rowCounts={"objects": 3},
    )

    patchOpenMetadataTable(service, monkeypatch, objMgr, table)

    result = service.getMetadataTableWindowService(
        projectId=1,
        protocolId=10,
        outputName="outputParticles",
        tableName="objects",
        offset=1,
        limit=2,
        selectionOnly=False,
        sortBy="label",
        asc=False,
        mapper=object(),
    )

    assert table.sortBy == "label"
    assert table.sortAsc is False
    assert result == {
        "offset": 1,
        "limit": 2,
        "totalRows": 3,
        "rows": [
            {
                "id": 1,
                "index": 1,
                "rowId": 2,
                "values": [2, "row-2"],
            },
            {
                "id": 2,
                "index": 2,
                "rowId": 3,
                "values": [3, "row-3"],
            },
        ],
    }


def test_ExportMetadataTableServiceReturnsCsv(service, monkeypatch):
    columns = [
        FakeColumn("id", "Id", IntRenderer()),
        FakeColumn("label", "Label", StrRenderer()),
    ]
    rows = [
        FakeRow(1, [1, "row-1"]),
        FakeRow(2, [2, "row-2"]),
    ]
    table = FakeTable(name="objects", alias="Particles", columns=columns)
    objMgr = FakeObjectManager(
        tables={"objects": table},
        rowsByTable={"objects": rows},
        rowCounts={"objects": 2},
    )

    patchOpenMetadataTable(service, monkeypatch, objMgr, table)

    response = service.exportMetadataTableService(
        projectId=1,
        protocolId=10,
        outputName="outputParticles",
        tableName="objects",
        fmt="csv",
        selectionOnly=False,
        ids=None,
        mapper=object(),
    )

    text = response.body.decode("utf-8")
    assert response.media_type == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == 'attachment; filename="objects.csv"'
    assert "id,label" in text
    assert "1,row-1" in text
    assert "2,row-2" in text


def test_RenderMetadataImageCellServiceReturnsPlaceholderWhenRowMissing(service, monkeypatch):
    columns = [FakeColumn("image", "Image", ImageRenderer())]
    table = FakeTable(name="objects", alias="Particles", columns=columns)
    objMgr = FakeObjectManager(
        tables={"objects": table},
        rowsByTable={"objects": []},
        rowCounts={"objects": 0},
        fileName="postgresql://project/1/protocol/10/output/outputParticles",
    )

    patchOpenMetadataTable(service, monkeypatch, objMgr, table)

    response = service.renderMetadataImageCellService(
        projectId=1,
        protocolId=10,
        outputName="outputParticles",
        tableName="objects",
        rowId=1,
        rowIndex=None,
        columnName="image",
        size=64,
        applyTransform=False,
        inline=True,
        fmt="png",
        mapper=object(),
    )

    assert response.status_code == 200
    assert response.headers["x-image-placeholder"] == "1"
    assert response.media_type == "image/png"


def test_RunMetadataTableActionServiceLaunchesSubsetProtocol(
    service,
    projectServiceModule,
    monkeypatch,
    tmp_path,
):
    outputFile = tmp_path / "metadata.sqlite"
    outputFile.write_text("placeholder", encoding="utf-8")

    output = FakeOutput(str(outputFile))
    protocol = FakeProtocol("outputParticles", output)
    service.currentProject = FakeCurrentProject(protocol, projectPath=tmp_path)

    table = FakeTable(
        name="objects",
        alias="Particles",
        columns=[],
        actions=[FakeAction("create subset")],
    )
    dao = FakeDao(objectsType={"create subset": "SetOfParticles"})
    objMgr = FakeObjectManager(
        tables={"objects": table},
        rowsByTable={"objects": []},
        dao=dao,
    )

    class FakeDb:
        # fakeDb
        def fetchOne(self, *args, **kwargs):
            return None

    class FakeMapper:
        # fakeMapper
        def __init__(self):
            self.db = FakeDb()

    mapper = FakeMapper()
    calls = []
    syncCalls = []
    syncResult = {
        "protocols": 2,
        "dependencies": 1,
    }

    def syncProjectProtocolsAndDependencies(
            mapperArg,
            projectIdArg,
            refresh=True,
            checkPid=True,
    ):
        syncCalls.append(
            {
                "mapper": mapperArg,
                "projectId": projectIdArg,
                "refresh": refresh,
                "checkPid": checkPid,
            }
        )
        return syncResult

    patchOpenMetadataTable(service, monkeypatch, objMgr, table, calls=calls)
    monkeypatch.setattr(projectServiceModule, "OBJECT_TABLE", "objects")
    monkeypatch.setattr(projectServiceModule, "ProtUserSubSet", object())
    monkeypatch.setattr(
        service,
        "syncProjectProtocolsAndDependencies",
        syncProjectProtocolsAndDependencies,
    )

    result = service.runMetadataTableActionService(
        projectId=1,
        protocolId=10,
        outputName="outputParticles",
        tableName="objects",
        action="create subset",
        subsetName="subset A",
        ids=[3, 5, 7],
        currentUser={"id": 1},
        mapper=mapper,
    )

    assert result == {
        "success": True,
        "message": "Subset protocol was launched successfully",
        "postgresqlSync": syncResult,
        "postgresqlError": None,
    }
    assert syncCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "refresh": True,
            "checkPid": True,
        }
    ]
    assert calls == [
        {
            "projectId": 1,
            "protocolId": 10,
            "outputName": "outputParticles",
            "tableName": "objects",
            "mapper": mapper,
        }
    ]
    assert len(protocol.newProtocolCalls) == 1
    call = protocol.newProtocolCalls[0]
    assert call["kwargs"]["inputObject"] is output
    assert call["kwargs"]["outputClassName"] == "SetOfParticles"
    assert call["kwargs"]["label"] == "subset A"
    assert call["kwargs"]["sqliteFile"].startswith("Logs/selection_")
    assert call["kwargs"]["sqliteFile"].endswith(".txt,")
    assert service.currentProject.launchedProtocols == [
        {"batchProtocol": True, "kwargs": call["kwargs"]}
    ]

    selectionFiles = list((tmp_path / "Logs").glob("selection_*.txt"))
    assert len(selectionFiles) == 1
    assert selectionFiles[0].read_text(encoding="utf-8") == "3 5 7 "


def test_RunMetadataTableActionServiceBuildsChildTableSelectionArgument(
    service,
    projectServiceModule,
    monkeypatch,
    tmp_path,
):
    outputFile = tmp_path / "metadata.sqlite"
    outputFile.write_text("placeholder", encoding="utf-8")

    output = FakeOutput(str(outputFile))
    protocol = FakeProtocol("outputParticles", output)
    service.currentProject = FakeCurrentProject(protocol, projectPath=tmp_path)

    table = FakeTable(
        name="Class001_Objects",
        alias="Class001_Particle",
        columns=[],
        actions=[FakeAction("Particle")],
    )
    dao = FakeDao(
        objectsType={"Particle": "SetOfParticles"},
        actionAliases={"Class001_Objects": "Class001_Particle"},
    )
    objMgr = FakeObjectManager(
        tables={"Class001_Objects": table},
        rowsByTable={"Class001_Objects": []},
        dao=dao,
    )

    patchOpenMetadataTable(service, monkeypatch, objMgr, table)
    monkeypatch.setattr(projectServiceModule, "OBJECT_TABLE", "objects")
    monkeypatch.setattr(projectServiceModule, "ProtUserSubSet", object())

    result = service.runMetadataTableActionService(
        projectId=1,
        protocolId=10,
        outputName="outputParticles",
        tableName="Class001_Objects",
        action="Particle",
        subsetName="class particles",
        ids=[1, 2],
        currentUser={"id": 1},
        mapper=object(),
    )

    assert result["success"] is True
    assert len(protocol.newProtocolCalls) == 1
    call = protocol.newProtocolCalls[0]
    assert call["kwargs"]["outputClassName"] == "SetOfParticles"
    assert call["kwargs"]["sqliteFile"].startswith("Logs/selection_")
    assert call["kwargs"]["sqliteFile"].endswith(".txt,Class001")