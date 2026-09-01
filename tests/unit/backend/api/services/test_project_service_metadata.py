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


class FakeRuntimeMapper:
    def __init__(self, events):
        self.events = events
        self.storeCalls = []
        self.commitCalls = 0

    def store(self, protocol):
        self.storeCalls.append(protocol)
        self.events.append(("store", protocol))

    def commit(self):
        self.commitCalls += 1
        self.events.append(("commit", None))


class FakeCurrentProject:
    # fakeCurrentProject
    def __init__(self, protocol, projectPath=None):
        self._protocol = protocol
        self._projectPath = projectPath
        self.launchedProtocols = []
        self.events = []
        self.mapper = FakeRuntimeMapper(self.events)

    def getProtocol(self, protocolId):
        return self._protocol

    def getPath(self):
        if self._projectPath is None:
            raise AttributeError("Project path is not set")
        return str(self._projectPath)

    def newProtocol(self, *args, **kwargs):
        return self._protocol.newProtocol(*args, **kwargs)

    def launchProtocol(self, protocol):
        self.events.append(("launch", protocol))
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


def test_GetPostgresqlDAOIfAvailableUsesResolvedProtocolDbId(
    service,
    monkeypatch,
):
    createdDaos = []

    class FakeDb:
        # fakeDb
        pass

    class FakeMapper:
        # fakeMapper
        def __init__(self):
            self.db = FakeDb()

    class FakePostgresqlDAO:
        # fakePostgresqlDAO
        def __init__(self, db, projectId, protocolId, outputName):
            self.db = db
            self.projectId = projectId
            self.protocolId = protocolId
            self.outputName = outputName
            createdDaos.append(self)

        def hasOutput(self):
            return True

    daoModule = importlib.import_module(
        "app.backend.viewers.postgresql_dao"
    )

    monkeypatch.setattr(
        daoModule,
        "PostgresqlDAO",
        FakePostgresqlDAO,
    )
    monkeypatch.setattr(
        service,
        "_resolvePostgresqlProtocolDbId",
        lambda mapper, projectId, protocolId: 852,
    )

    mapper = FakeMapper()

    dao = service._getPostgresqlDAOIfAvailable(
        projectId=1,
        protocolId=10,
        outputName="outputParticles",
        mapper=mapper,
    )

    assert dao is createdDaos[0]
    assert createdDaos[0].db is mapper.db
    assert createdDaos[0].projectId == 1
    assert createdDaos[0].protocolId == 852
    assert createdDaos[0].outputName == "outputParticles"


def test_GetMetadataObjectManagerForOutputRequiresPostgresqlWhenMapperIsPresent(
    service,
    monkeypatch,
):
    class FakeDb:
        # fakeDb
        pass

    class FakeMapper:
        # fakeMapper
        def __init__(self):
            self.db = FakeDb()

    monkeypatch.setattr(
        service,
        "_getPostgresqlDAOIfAvailable",
        lambda **kwargs: None,
    )

    def failRuntimeFallback(**kwargs):
        raise AssertionError("Legacy metadata fallback should not be used")

    monkeypatch.setattr(service, "_resolveOutputForMetadata", failRuntimeFallback)

    with pytest.raises(Exception) as exc:
        service._getMetadataObjectManagerForOutput(
            projectId=1,
            protocolId=10,
            outputName="outputParticles",
            mapper=FakeMapper(),
        )

    assert exc.value.status_code == 404
    assert "Metadata output is not available in PostgreSQL metadata" in exc.value.detail
    assert "dao_not_available" in exc.value.detail


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


def test_RenderMetadataImageCellServiceResolvesProtocolIdForRelativeImagePaths(
    service,
    monkeypatch,
    tmp_path,
):
    protocolPath = tmp_path / "Runs" / "000010_Prot"
    protocolPath.mkdir(parents=True)

    imagePath = protocolPath / "thumb.png"

    try:
        from PIL import Image

        Image.new("L", (4, 4), 128).save(imagePath)
    except Exception:
        imagePath.write_bytes(b"")

    class PathRenderer:
        # pathRenderer
        def render(self, rawValue, rowValues):
            return rawValue

    class FakeProtocolWithPath:
        # fakeProtocolWithPath
        def getPath(self):
            return str(protocolPath)

    class FakeProjectWithoutProtocolLookup:
        # fakeProjectWithoutProtocolLookup
        def getPath(self):
            return str(tmp_path)

        def getProtocol(self, protocolId):
            raise AssertionError("currentProject.getProtocol should not be used directly")

    columns = [FakeColumn("image", "Image", PathRenderer())]
    table = FakeTable(name="objects", alias="Particles", columns=columns)
    objMgr = FakeObjectManager(
        tables={"objects": table},
        rowsByTable={"objects": [FakeRow(1, ["thumb.png"])]},
        rowCounts={"objects": 1},
        fileName="postgresql://project/1/protocol/500/output/outputParticles",
    )

    class FakeDb:
        # fakeDb
        pass

    class FakeMapper:
        # fakeMapper
        def __init__(self):
            self.db = FakeDb()

    mapper = FakeMapper()
    resolverCalls = []

    def getScipionProtocolForRuntime(mapper, projectId, protocolId):
        resolverCalls.append(
            {
                "mapper": mapper,
                "projectId": projectId,
                "protocolId": protocolId,
            }
        )
        return FakeProtocolWithPath()

    service.currentProject = FakeProjectWithoutProtocolLookup()
    patchOpenMetadataTable(service, monkeypatch, objMgr, table)
    monkeypatch.setattr(
        service,
        "_getScipionProtocolForRuntime",
        getScipionProtocolForRuntime,
    )

    response = service.renderMetadataImageCellService(
        projectId=1,
        protocolId=500,
        outputName="outputParticles",
        tableName="objects",
        rowId=1,
        rowIndex=None,
        columnName="image",
        size=64,
        applyTransform=False,
        inline=True,
        fmt="png",
        mapper=mapper,
    )

    assert response.media_type == "image/png"
    assert response.headers.get("x-image-placeholder") is None
    assert resolverCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "protocolId": 500,
        }
    ]


def test_RenderMetadataImageCellServiceResolvesProjectRelativePostgresqlImagePaths(
    service,
    monkeypatch,
    tmp_path,
):
    projectPath = tmp_path / "project"
    imagePath = (
            projectPath
            / "Runs"
            / "000002_ProtImportMicrographs"
            / "extra"
            / "016.png"
    )
    imagePath.parent.mkdir(parents=True)

    try:
        from PIL import Image

        Image.new("L", (4, 4), 128).save(imagePath)
    except Exception:
        imagePath.write_bytes(b"")

    class PathRenderer:
        def render(self, rawValue, rowValues):
            return rawValue

    class FakeProjectWithoutRuntimeProtocolLookup:
        def getPath(self):
            raise AssertionError("currentProject.getPath should not be needed for PostgreSQL project-relative paths")

        def getProtocol(self, protocolId):
            raise AssertionError("currentProject.getProtocol should not be used")

    columns = [FakeColumn("stack", "Stack", PathRenderer())]
    table = FakeTable(name="objects", alias="Micrographs", columns=columns)
    objMgr = FakeObjectManager(
        tables={"objects": table},
        rowsByTable={
            "objects": [
                FakeRow(
                    1,
                    ["Runs/000002_ProtImportMicrographs/extra/016.png"],
                )
            ],
        },
        rowCounts={"objects": 1},
        fileName="postgresql://project/247/protocol/2/output/outputMicrographs",
    )

    class FakeDb:
        def fetchOne(self, query, params):
            if "FROM projects" in query:
                return {"name": str(projectPath)}
            return None

    class FakeMapper:
        def __init__(self):
            self.db = FakeDb()

    mapper = FakeMapper()
    service.currentProject = FakeProjectWithoutRuntimeProtocolLookup()
    patchOpenMetadataTable(service, monkeypatch, objMgr, table)

    def failRuntimeProtocolLookup(*args, **kwargs):
        raise AssertionError("_getScipionProtocolForRuntime should not be used")

    monkeypatch.setattr(
        service,
        "_getScipionProtocolForRuntime",
        failRuntimeProtocolLookup,
    )

    response = service.renderMetadataImageCellService(
        projectId=247,
        protocolId=2,
        outputName="outputMicrographs",
        tableName="objects",
        rowId=None,
        rowIndex=0,
        columnName="stack",
        size=64,
        applyTransform=False,
        inline=True,
        fmt="png",
        mapper=mapper,
    )

    assert response.status_code == 200
    assert response.media_type == "image/png"
    assert response.headers.get("x-image-placeholder") is None


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
    inputOutputCalls = []
    protocolSyncCalls = []
    inputSyncCalls = []
    syncResult = {
        "protocols": 1,
        "dependencies": 1,
        "inputRefs": 1,
        "protocolId": "900",
    }

    def resolveMetadataActionInputContext(**kwargs):
        inputOutputCalls.append(kwargs)
        return {
            "output": output,
            "parentProtocolId": 10,
        }

    def syncPostgresqlRuntimeProtocol(**kwargs):
        protocolSyncCalls.append(kwargs)
        service.currentProject.events.append(("protocol-sync", kwargs["protocol"]))
        return {"protocols": 1}

    def syncPostgresqlRuntimeProtocolInputsAndDependencies(**kwargs):
        inputSyncCalls.append(kwargs)
        service.currentProject.events.append(("input-sync", kwargs["protocol"]))
        return {
            "dependencies": 1,
            "inputRefsSaved": 1,
            "parentProtocolIds": [10],
        }

    def failGlobalSync(*args, **kwargs):
        raise AssertionError("Subset creation must not synchronize parent protocols or outputs")

    patchOpenMetadataTable(service, monkeypatch, objMgr, table, calls=calls)
    monkeypatch.setattr(projectServiceModule, "OBJECT_TABLE", "objects")
    monkeypatch.setattr(projectServiceModule, "ProtUserSubSet", object())
    monkeypatch.setattr(service, "_resolveMetadataActionInputContext", resolveMetadataActionInputContext)
    monkeypatch.setattr(service, "_getScipionObjectId", lambda protocolArg: 900)
    monkeypatch.setattr(service, "syncPostgresqlRuntimeProtocol", syncPostgresqlRuntimeProtocol)
    monkeypatch.setattr(service, "syncPostgresqlRuntimeProtocolInputsAndDependencies",
                        syncPostgresqlRuntimeProtocolInputsAndDependencies)
    monkeypatch.setattr(
        service,
        "_syncLegacyProjectGraphToPostgresql",
        failGlobalSync,
    )

    executionUserCalls = []

    class RuntimeProtocolStatusSyncServiceStub:
        def persistProtocolExecutionUser(
                self,
                **kwargs,
        ):
            executionUserCalls.append(
                kwargs
            )

            service.currentProject.events.append(
                (
                    "execution-user",
                    kwargs,
                )
            )

            return kwargs

    monkeypatch.setattr(
        projectServiceModule,
        "RuntimeProtocolStatusSyncService",
        RuntimeProtocolStatusSyncServiceStub,
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
    launchedProtocol = service.currentProject.launchedProtocols[0]

    assert inputOutputCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "protocolId": 10,
            "outputName": "outputParticles",
        }
    ]
    assert protocolSyncCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "protocolId": 900,
            "registerOutputs": False,
            "syncRelations": False,
            "protocol": launchedProtocol,
            "authoritativeProtocolState": True,
        }
    ]
    assert inputSyncCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "protocol": launchedProtocol,
            "params": {
                "inputObject": "10.outputParticles",
            },
        },
        {
            "mapper": mapper,
            "projectId": 1,
            "protocol": launchedProtocol,
            "params": {
                "inputObject": "10.outputParticles",
            },
        },
    ]
    assert [event[0] for event in service.currentProject.events] == [
        "store",
        "commit",
        "input-sync",
        "execution-user",
        "launch",
        "protocol-sync",
        "input-sync",
    ]
    assert len(
        executionUserCalls
    ) == 1

    executionUserCall = (
        executionUserCalls[0]
    )

    assert executionUserCall[
        "mapper"
    ] is mapper

    assert executionUserCall[
        "projectId"
    ] == 1

    assert executionUserCall[
        "protocolId"
    ] == 900

    assert executionUserCall[
        "userId"
    ] == 1

    assert isinstance(
        executionUserCall[
            "executionId"
        ],
        str,
    )

    assert len(
        executionUserCall[
            "executionId"
        ]
    ) == 32
    assert service.currentProject.mapper.storeCalls == [launchedProtocol]
    assert service.currentProject.mapper.commitCalls == 1
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


def test_ResolveMetadataActionInputContextBuildsReadOnlyPostgresqlProxy(
    service,
    projectServiceModule,
    monkeypatch,
):
    parentProtocol = object()
    proxyOutput = object()
    runtimeMapper = object()
    outputInfo = {
        "exists": True,
        "projectId": 1,
        "setId": 77,
        "runtimeObjectId": 9001,
        "outputName": "outputSet",
        "className": "SetOfParticles",
    }

    class FakeRuntimeProject:
        pass

    service.currentProject = FakeRuntimeProject()
    service.currentProject.mapper = runtimeMapper

    class FakeDb:
        def __init__(self):
            self.fetchCalls = []

        def fetchOne(self, query, params):
            self.fetchCalls.append({"query": query, "params": params})

            if '"protocolId" = %s' in query:
                assert params == (1, "6115")
                return {"id": 852, "protocolId": "6115"}

            if "AND id = %s" in query:
                assert params == (1, 852)
                return {"id": 852, "protocolId": "6115"}

            raise AssertionError("Unexpected protocol identity query")

    class FakeMapper:
        def __init__(self):
            self.db = FakeDb()

    mapper = FakeMapper()
    protocolCalls = []
    outputInfoCalls = []
    proxyCalls = []

    def getScipionProtocolByRuntimeId(protocolId):
        protocolCalls.append(protocolId)
        return parentProtocol

    def getPostgresqlRuntimeOutputInfo(**kwargs):
        outputInfoCalls.append(kwargs)
        return outputInfo

    class FakeRuntimeOutputProxyService:
        def attachPostgresqlRuntimeOutputProxy(self, parentProtocol, outputName, outputInfo, mapper=None):
            proxyCalls.append({
                "parentProtocol": parentProtocol,
                "outputName": outputName,
                "outputInfo": outputInfo,
                "mapper": mapper,
            })
            return proxyOutput

    monkeypatch.setattr(service, "_getScipionProtocolByRuntimeId", getScipionProtocolByRuntimeId)
    monkeypatch.setattr(service, "_getPostgresqlRuntimeOutputInfo", getPostgresqlRuntimeOutputInfo)
    monkeypatch.setattr(projectServiceModule, "RuntimeOutputProxyService", FakeRuntimeOutputProxyService)

    result = service._resolveMetadataActionInputContext(mapper=mapper, projectId=1, protocolId=6115,
                                                        outputName="outputSet")

    assert result == {
        "output": proxyOutput,
        "parentProtocolId": 6115,
    }
    assert protocolCalls == [6115]
    assert outputInfoCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "parentProtocolDbId": 852,
            "outputName": "outputSet",
        }
    ]
    assert proxyCalls == [
        {
            "parentProtocol": parentProtocol,
            "outputName": "outputSet",
            "outputInfo": outputInfo,
            "mapper": runtimeMapper,
        }
    ]
    assert not hasattr(parentProtocol, "outputSet")


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
    monkeypatch.setattr(
        service,
        "_resolveMetadataActionInputContext",
        lambda **kwargs: {
            "output": output,
            "parentProtocolId": 10,
        },
    )
    monkeypatch.setattr(service, "_getScipionObjectId", lambda protocolArg: 900)
    monkeypatch.setattr(service, "syncPostgresqlRuntimeProtocol", lambda **kwargs: {"protocols": 1})
    monkeypatch.setattr(
                        service,
                        "syncPostgresqlRuntimeProtocolInputsAndDependencies",
                        lambda **kwargs: {
                            "dependencies": 1,
                            "inputRefsSaved": 1,
                            "parentProtocolIds": [10],
                        },
                    )

    class RuntimeProtocolStatusSyncServiceStub:
        def persistProtocolExecutionUser(
                self,
                **kwargs,
        ):
            return kwargs

    monkeypatch.setattr(
        projectServiceModule,
        "RuntimeProtocolStatusSyncService",
        RuntimeProtocolStatusSyncServiceStub,
    )

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


def test_RenderMetadataImageCellServicePrefersPillowForTiffFiles(
    service,
    projectServiceModule,
    monkeypatch,
    tmp_path,
):
    from PIL import Image as PILImage

    imagePath = tmp_path / "frame.tif"
    imagePath.write_bytes(b"fake tiff content")

    class PathRenderer:
        def render(self, rawValue, rowValues):
            return rawValue

    columns = [
        FakeColumn(
            "stack",
            "Stack",
            PathRenderer(),
        )
    ]

    table = FakeTable(
        name="objects",
        alias="Images",
        columns=columns,
    )

    objMgr = FakeObjectManager(
        tables={
            "objects": table,
        },
        rowsByTable={
            "objects": [
                FakeRow(
                    1,
                    [str(imagePath)],
                )
            ],
        },
        rowCounts={
            "objects": 1,
        },
        fileName=(
            "postgresql://project/8/"
            "protocol/2/output/outputTiltSeriesM"
        ),
    )

    patchOpenMetadataTable(
        service,
        monkeypatch,
        objMgr,
        table,
    )

    sourceImage = PILImage.new(
        "L",
        (32, 32),
        128,
    )

    pilOpenCalls = []

    def pilOpen(path):
        pilOpenCalls.append(str(path))
        return sourceImage.copy()

    monkeypatch.setattr(
        PILImage,
        "open",
        pilOpen,
    )

    class FailOutputsPreview:
        def __init__(self, *args, **kwargs):
            raise AssertionError(
                "Pillow-supported TIFF files must not "
                "use Scipion preview first"
            )

    monkeypatch.setattr(
        projectServiceModule,
        "OutputsPreview",
        FailOutputsPreview,
    )

    response = service.renderMetadataImageCellService(
        projectId=8,
        protocolId=2,
        outputName="outputTiltSeriesM",
        tableName="objects",
        rowId=None,
        rowIndex=0,
        columnName="stack",
        size=200,
        applyTransform=False,
        inline=True,
        fmt="png",
        mapper=None,
    )

    assert response.status_code == 200
    assert response.media_type == "image/png"
    assert response.headers.get(
        "x-image-placeholder"
    ) is None

    assert pilOpenCalls == [
        str(imagePath.resolve())
    ]

def test_RenderMetadataImageCellServiceFallsBackToScipionPreviewForMrcFiles(
    service,
    projectServiceModule,
    monkeypatch,
    tmp_path,
):
    from starlette.responses import Response
    from PIL import Image as PILImage

    pilOpenCalls = []

    def pilOpen(*args, **kwargs):
        pilOpenCalls.append(args)
        raise AssertionError(
            "PIL must not be tried for registered MRC formats"
        )

    monkeypatch.setattr(
        PILImage,
        "open",
        pilOpen,
    )

    projectPath = tmp_path / "project"
    imagePath = (
        projectPath
        / "Runs"
        / "000077_XmippProtPreprocessMicrographs"
        / "extra"
        / "008.mrc"
    )
    imagePath.parent.mkdir(parents=True)
    imagePath.write_bytes(b"fake mrc content")

    class PathRenderer:
        def render(self, rawValue, rowValues):
            return rawValue

    class FakeDb:
        def fetchOne(self, query, params):
            if "FROM projects" in query:
                return {"name": str(projectPath)}
            return None

    class FakeMapper:
        def __init__(self):
            self.db = FakeDb()

    class FakeOutputsPreview:
        instances = []

        def __init__(self, currentProject, protocol, output, requestHeaders=None):
            self.currentProject = currentProject
            self.protocol = protocol
            self.output = output
            self.requestHeaders = requestHeaders
            self.lastRenderCall = None
            FakeOutputsPreview.instances.append(self)

        def renderImageFromFilePath(
            self,
            filePath,
            size,
            fmt,
            index,
            applyTransform,
            inline,
            rot,
            shifts,
        ):
            self.lastRenderCall = {
                "filePath": filePath,
                "size": size,
                "fmt": fmt,
                "index": index,
                "applyTransform": applyTransform,
                "inline": inline,
                "rot": rot,
                "shifts": shifts,
            }
            return Response(content=b"fake-webp", media_type="image/webp")

    columns = [FakeColumn("stack", "Stack", PathRenderer())]
    table = FakeTable(name="objects", alias="Micrographs", columns=columns)
    objMgr = FakeObjectManager(
        tables={"objects": table},
        rowsByTable={
            "objects": [
                FakeRow(
                    1,
                    ["Runs/000077_XmippProtPreprocessMicrographs/extra/008.mrc"],
                )
            ],
        },
        rowCounts={"objects": 1},
        fileName="postgresql://project/247/protocol/77/output/outputMicrographs",
    )

    mapper = FakeMapper()
    patchOpenMetadataTable(service, monkeypatch, objMgr, table)
    monkeypatch.setattr(projectServiceModule, "OutputsPreview", FakeOutputsPreview)

    response = service.renderMetadataImageCellService(
        projectId=247,
        protocolId=77,
        outputName="outputMicrographs",
        tableName="objects",
        rowId=None,
        rowIndex=0,
        columnName="stack",
        size=200,
        applyTransform=False,
        inline=True,
        fmt="webp",
        mapper=mapper,
    )

    assert response.status_code == 200
    assert response.media_type == "image/webp"
    assert response.headers.get("x-image-placeholder") is None

    assert FakeOutputsPreview.instances[0].lastRenderCall == {
        "filePath": str(imagePath.resolve()),
        "size": 200,
        "fmt": "webp",
        "index": 0,
        "applyTransform": False,
        "inline": True,
        "rot": None,
        "shifts": None,
    }
    assert pilOpenCalls == []


def test_PostgresqlMovieOutputPreviewUsesMetadataImageFastPath(
        service,
        projectServiceModule,
        monkeypatch,
):
    from fastapi.responses import Response

    mapper = object()

    currentUser = {
        "id": 7,
    }

    repositoryCalls = []
    renderCalls = []

    monkeypatch.setattr(
        service,
        "getProjectDbRow",
        lambda mapperArg,
               projectIdArg,
               currentUserArg: {
            "id": projectIdArg,
        },
    )

    monkeypatch.setattr(
        service,
        "_resolvePostgresqlProtocolDbId",
        lambda **kwargs: 77,
    )

    class ProtocolGraphRepositoryStub:
        def getPersistedOutputInfoForInputRef(
                self,
                **kwargs,
        ):
            repositoryCalls.append(
                kwargs
            )

            return {
                "className": (
                    "SetOfMovies"
                ),
            }

    monkeypatch.setattr(
        projectServiceModule,
        "ProtocolGraphRepository",
        ProtocolGraphRepositoryStub,
    )

    monkeypatch.setattr(
        service,
        "listOutputMetadataTablesService",
        lambda **kwargs: [
            {
                "name": "objects",
                "rowCount": 10,
            },
            {
                "name": "Properties",
                "rowCount": 5,
            },
        ],
    )

    monkeypatch.setattr(
        service,
        "getMetadataTableSchemaService",
        lambda **kwargs: {
            "columns": [
                {
                    "name": "id",
                    "rendererType": "int",
                },
                {
                    "name": "image",
                    "rendererType": "image",
                },
            ],
        },
    )

    expectedResponse = Response(
        content=b"movie-preview",
        media_type="image/webp",
    )

    def renderMetadataImageCell(
            **kwargs,
    ):
        renderCalls.append(
            kwargs
        )

        return expectedResponse

    monkeypatch.setattr(
        service,
        "renderMetadataImageCellService",
        renderMetadataImageCell,
    )

    result = (
        service
        .tryRenderPostgresqlMovieOutputPreviewService(
            mapper=mapper,
            projectId=12,
            protocolId=3486,
            outputName="outputMovies",
            currentUser=currentUser,
        )
    )

    assert result is expectedResponse

    assert repositoryCalls == [{
        "mapper": mapper,
        "projectId": 12,
        "parentProtocolDbId": 77,
        "outputName": "outputMovies",
    }]

    assert renderCalls == [{
        "projectId": 12,
        "protocolId": 3486,
        "outputName": "outputMovies",
        "tableName": "objects",
        "rowId": None,
        "rowIndex": 0,
        "columnName": "image",
        "size": 400,
        "applyTransform": False,
        "inline": True,
        "fmt": "webp",
        "mapper": mapper,
    }]

    assert (
        result.headers[
            "x-preview-type"
        ]
        == "movie"
    )

    assert (
        result.headers[
            "x-preview-fast-path"
        ]
        == "postgresql-metadata-movie"
    )


def test_PostgresqlMovieOutputPreviewFastPathSkipsOtherOutputTypes(
        service,
        projectServiceModule,
        monkeypatch,
):
    mapper = object()

    monkeypatch.setattr(
        service,
        "getProjectDbRow",
        lambda *args, **kwargs: {
            "id": 12,
        },
    )

    monkeypatch.setattr(
        service,
        "_resolvePostgresqlProtocolDbId",
        lambda **kwargs: 77,
    )

    class ProtocolGraphRepositoryStub:
        def getPersistedOutputInfoForInputRef(
                self,
                **kwargs,
        ):
            return {
                "className": (
                    "SetOfMicrographs"
                ),
            }

    monkeypatch.setattr(
        projectServiceModule,
        "ProtocolGraphRepository",
        ProtocolGraphRepositoryStub,
    )

    def failMetadataLookup(
            **kwargs,
    ):
        raise AssertionError(
            "Non-Movie outputs must not "
            "use the Movie metadata fast path."
        )

    monkeypatch.setattr(
        service,
        "listOutputMetadataTablesService",
        failMetadataLookup,
    )

    result = (
        service
        .tryRenderPostgresqlMovieOutputPreviewService(
            mapper=mapper,
            projectId=12,
            protocolId=3486,
            outputName="outputMicrographs",
            currentUser={
                "id": 7,
            },
        )
    )

    assert result is None


