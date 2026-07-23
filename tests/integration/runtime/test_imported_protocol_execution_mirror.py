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
from types import SimpleNamespace

import pyworkflow.object as pwobject
from pyworkflow.mapper.sqlite import SqliteMapper
from pyworkflow.protocol.protocol import Protocol

from app.backend.mapper.postgresql_runtime_mapper import (
    SQLITE_EXECUTION_CHILD_ID_START,
    PostgresqlRuntimeMapper,
)


class ExampleProtocol(Protocol):
    def _defineParams(self, form):
        pass


class FakeProject:
    def __init__(self, projectPath):
        self.path = str(projectPath)

    def getPath(self):
        return self.path

    def getDbPath(self):
        return str(self.path + "/project.sqlite")


class FakeFlatMapper:
    def __init__(self, protocolIds):
        self.db = SimpleNamespace()
        self.protocolIds = list(protocolIds)
        self.protocolAllocationCalls = []

    def allocateProjectProtocolId(self, projectId):
        self.protocolAllocationCalls.append(int(projectId))

        if not self.protocolIds:
            raise AssertionError("Unexpected protocol id allocation")

        return self.protocolIds.pop(0)


def buildClassesDictionary():
    classes = dict(vars(pwobject))
    classes["ExampleProtocol"] = ExampleProtocol
    return classes


def insertOccupiedObject(sqliteMapper, objId, parentId, name):
    sqliteMapper.db.executeCommand(
        """
        INSERT INTO Objects (
            id,
            parent_id,
            name,
            classname,
            value,
            label,
            comment,
            creation
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(objId),
            int(parentId),
            str(name),
            "String",
            "finished",
            "",
            "",
            None,
        ),
    )


def buildRuntimeMapper(project, sqliteMapper):
    flatMapper = FakeFlatMapper([
        602,
        603,
        604,
        605,
    ])

    mapper = object.__new__(PostgresqlRuntimeMapper)
    mapper.projectId = 31
    mapper.project = project
    mapper.flatMapper = flatMapper
    mapper.db = flatMapper.db
    mapper.dictClasses = buildClassesDictionary()
    mapper.readFallbackMapper = None
    mapper.writeFallbackMapper = sqliteMapper
    mapper._runtimeProtocolsById = {}
    mapper._sqliteProtocolMirrorIds = set()
    mapper._fallbackAuditEnabled = False
    mapper._fallbackAuditCounts = {}
    mapper._fallbackAuditContexts = {}

    return mapper


def test_DuplicatedImportedProtocolUsesFreeCompactIdAndMaterializesMirror(
        tmp_path,
):
    projectPath = tmp_path / "ImportedProject"
    projectPath.mkdir(parents=True)

    sqlitePath = projectPath / "project.sqlite"
    classes = buildClassesDictionary()
    sqliteMapper = SqliteMapper(str(sqlitePath), dictClasses=classes)

    try:
        insertOccupiedObject(
            sqliteMapper=sqliteMapper,
            objId=602,
            parentId=600,
            name="600.status",
        )

        insertOccupiedObject(
            sqliteMapper=sqliteMapper,
            objId=603,
            parentId=600,
            name="600.initTime",
        )

        insertOccupiedObject(
            sqliteMapper=sqliteMapper,
            objId=604,
            parentId=600,
            name="600.endTime",
        )

        sqliteMapper.commit()

        project = FakeProject(projectPath)
        runtimeMapper = buildRuntimeMapper(project, sqliteMapper)

        duplicatedProtocol = ExampleProtocol()
        duplicatedProtocol.setObjLabel("Duplicated protocol")

        duplicatedProtocolId = runtimeMapper._ensureObjId(
            duplicatedProtocol
        )

        assert duplicatedProtocolId == 605
        assert duplicatedProtocol.getObjId() == 605

        assert runtimeMapper.flatMapper.protocolAllocationCalls == [
            31,
            31,
            31,
            31,
        ]

        mirrorReport = runtimeMapper.ensureProtocolWriteFallbackMirror(
            duplicatedProtocol
        )

        assert mirrorReport == {
            "protocolId": 605,
            "created": True,
            "updated": False,
            "mirrorClassName": "ExampleProtocol",
        }

        rootRow = sqliteMapper.db.selectObjectById(605)

        assert rootRow is not None
        assert rootRow["id"] == 605
        assert rootRow["parent_id"] is None
        assert rootRow["classname"] == "ExampleProtocol"

        for occupiedId in (602, 603, 604):
            occupiedRow = sqliteMapper.db.selectObjectById(occupiedId)

            assert occupiedRow is not None
            assert occupiedRow["classname"] == "String"
            assert occupiedRow["parent_id"] == 600

        childRows = list(
            sqliteMapper.db.selectObjectsByAncestor("605")
        )

        assert childRows
        assert all(
            int(row["id"]) > SQLITE_EXECUTION_CHILD_ID_START
            for row in childRows
        )

        runtimeMapper._clearFallbackMapperCaches(sqliteMapper)

        openedProtocol = sqliteMapper.selectById(605)

        assert isinstance(openedProtocol, ExampleProtocol)
        assert openedProtocol.getObjId() == 605
        assert openedProtocol.getObjLabel() == "Duplicated protocol"

        secondMirrorReport = (
            runtimeMapper.ensureProtocolWriteFallbackMirror(
                openedProtocol
            )
        )

        assert secondMirrorReport == {
            "protocolId": 605,
            "created": False,
            "updated": True,
            "mirrorClassName": "ExampleProtocol",
        }

        assert runtimeMapper.flatMapper.protocolAllocationCalls == [
            31,
            31,
            31,
            31,
        ]

        finalRootRow = sqliteMapper.db.selectObjectById(605)

        assert finalRootRow is not None
        assert finalRootRow["parent_id"] is None
        assert finalRootRow["classname"] == "ExampleProtocol"

    finally:
        sqliteMapper.close()