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

import pytest

import app.backend.project.postgresql_project as projectModule

from app.backend.project.postgresql_project import (
    PostgresqlProject,
)


class FakeProtocol:
    def __init__(
            self,
            dbPath="logs/run.db",
            workingDir="Runs/000010_FakeProtocol",
    ):
        self.dbPath = dbPath
        self.workingDir = workingDir

        self.mapper = None
        self.project = None

        self.mapperHistory = []
        self.projectHistory = []

    def getDbPath(self):
        return self.dbPath

    def getWorkingDir(self):
        return self.workingDir

    def setMapper(self, mapper):
        self.mapper = mapper
        self.mapperHistory.append(
            mapper
        )

    def setProject(self, project):
        self.project = project
        self.projectHistory.append(
            project
        )


class FakeFallbackMapper:
    def __init__(
            self,
            protocol,
    ):
        self.protocol = protocol

        self.selectedIds = []
        self.commitCalls = 0

    def selectById(
            self,
            protocolId,
    ):
        self.selectedIds.append(
            protocolId
        )

        return self.protocol

    def commit(self):
        self.commitCalls += 1


def buildProject(
        tmpPath,
        protocol,
):
    fallbackMapper = FakeFallbackMapper(
        protocol
    )

    staleProtocol = object()

    runtimeMapper = SimpleNamespace(
        writeFallbackMapper=fallbackMapper,
        _runtimeProtocolsById={
            10: staleProtocol,
        },
        _sqliteProtocolMirrorIds=set(),
    )

    project = PostgresqlProject.__new__(
        PostgresqlProject
    )

    project.path = str(
        tmpPath
    )

    project.postgresqlProjectId = 7
    project.mapper = runtimeMapper

    project._postgresqlRuntimeMapper = (
        runtimeMapper
    )

    project.usingPostgresqlRuntimeMapper = (
        lambda: True
    )

    project.getPostgresqlRuntimeMapper = (
        lambda: runtimeMapper
    )

    return (
        project,
        runtimeMapper,
        fallbackMapper,
        staleProtocol,
    )


def createRuntimeDb(
        tmpPath,
        protocol,
):
    runDbPath = (
        tmpPath
        / protocol.getWorkingDir()
        / "logs"
        / "run.db"
    )

    runDbPath.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    runDbPath.touch()

    return str(
        runDbPath
    )


def test_RefreshProtocolForResumeUsesSqliteMapperAndReplacesCache(
        monkeypatch,
        tmp_path,
):
    protocol = FakeProtocol()

    (
        project,
        runtimeMapper,
        fallbackMapper,
        staleProtocol,
    ) = buildProject(
        tmpPath=tmp_path,
        protocol=protocol,
    )

    runDbPath = createRuntimeDb(
        tmpPath=tmp_path,
        protocol=protocol,
    )

    operations = []

    def updateProtocol(
            currentProject,
            currentProtocol,
    ):
        operations.append({
            "operation": "update",
            "projectMapper": (
                currentProject.mapper
            ),
            "protocolMapper": (
                currentProtocol.mapper
            ),
        })

        currentProtocol.runtimeState = (
            "hydrated"
        )

        return {
            "updated": True,
        }

    def commit():
        operations.append({
            "operation": "commit",
        })

        fallbackMapper.commitCalls += 1

    monkeypatch.setattr(
        projectModule.ScipionProject,
        "_updateProtocol",
        updateProtocol,
    )

    fallbackMapper.commit = commit

    result = (
        project
        .refreshProtocolFromRuntimeDbForResume(
            10
        )
    )

    assert result == {
        "protocolId": 10,
        "refreshed": True,
        "runDbPath": runDbPath,
        "updateResult": {
            "updated": True,
        },
    }

    assert fallbackMapper.selectedIds == [
        10,
    ]

    assert operations == [
        {
            "operation": "update",
            "projectMapper": fallbackMapper,
            "protocolMapper": fallbackMapper,
        },
        {
            "operation": "commit",
        },
    ]

    assert fallbackMapper.commitCalls == 1

    assert project.mapper is runtimeMapper

    assert protocol.mapper is runtimeMapper
    assert protocol.project is project
    assert protocol.runtimeState == "hydrated"

    assert runtimeMapper._runtimeProtocolsById[
        10
    ] is protocol

    assert runtimeMapper._runtimeProtocolsById[
        10
    ] is not staleProtocol

    assert runtimeMapper._sqliteProtocolMirrorIds == {
        10,
    }

    assert protocol.mapperHistory == [
        fallbackMapper,
        runtimeMapper,
    ]


def test_RefreshProtocolForResumeRestoresMapperAndKeepsCacheOnFailure(
        monkeypatch,
        tmp_path,
):
    protocol = FakeProtocol()

    (
        project,
        runtimeMapper,
        fallbackMapper,
        staleProtocol,
    ) = buildProject(
        tmpPath=tmp_path,
        protocol=protocol,
    )

    createRuntimeDb(
        tmpPath=tmp_path,
        protocol=protocol,
    )

    def updateProtocol(
            currentProject,
            currentProtocol,
    ):
        assert (
            currentProject.mapper
            is fallbackMapper
        )

        assert (
            currentProtocol.mapper
            is fallbackMapper
        )

        raise RuntimeError(
            "forced runtime refresh failure"
        )

    monkeypatch.setattr(
        projectModule.ScipionProject,
        "_updateProtocol",
        updateProtocol,
    )

    with pytest.raises(
            RuntimeError,
            match=(
                "forced runtime refresh failure"
            ),
    ):
        project.refreshProtocolFromRuntimeDbForResume(
            10
        )

    assert fallbackMapper.selectedIds == [
        10,
    ]

    assert fallbackMapper.commitCalls == 0

    assert project.mapper is runtimeMapper

    assert protocol.mapper is runtimeMapper
    assert protocol.project is project

    assert runtimeMapper._runtimeProtocolsById == {
        10: staleProtocol,
    }

    assert (
        runtimeMapper
        ._sqliteProtocolMirrorIds
        == set()
    )

    assert protocol.mapperHistory == [
        fallbackMapper,
        runtimeMapper,
    ]


def test_RefreshProtocolForResumeAdoptsSqliteProtocolWhenRunDbIsMissing(
        monkeypatch,
        tmp_path,
):
    protocol = FakeProtocol()

    (
        project,
        runtimeMapper,
        fallbackMapper,
        staleProtocol,
    ) = buildProject(
        tmpPath=tmp_path,
        protocol=protocol,
    )

    updateCalls = []

    monkeypatch.setattr(
        projectModule.ScipionProject,
        "_updateProtocol",
        lambda *args, **kwargs: (
            updateCalls.append(
                (
                    args,
                    kwargs,
                )
            )
        ),
    )

    expectedRunDbPath = str(
        (
            tmp_path
            / protocol.getWorkingDir()
            / "logs"
            / "run.db"
        ).resolve()
    )

    result = (
        project
        .refreshProtocolFromRuntimeDbForResume(
            10
        )
    )

    assert result == {
        "protocolId": 10,
        "refreshed": False,
        "reason": (
            "runtime_db_not_found"
        ),
        "runDbPath": expectedRunDbPath,
    }

    assert updateCalls == []
    assert fallbackMapper.commitCalls == 0

    assert project.mapper is runtimeMapper

    assert protocol.mapper is runtimeMapper
    assert protocol.project is project

    assert runtimeMapper._runtimeProtocolsById[
        10
    ] is protocol

    assert runtimeMapper._runtimeProtocolsById[
        10
    ] is not staleProtocol

    assert runtimeMapper._sqliteProtocolMirrorIds == {
        10,
    }


def test_RefreshProtocolForResumeDoesNothingForLegacyProject(
        tmp_path,
):
    project = PostgresqlProject.__new__(
        PostgresqlProject
    )

    project.path = str(
        tmp_path
    )

    project.usingPostgresqlRuntimeMapper = (
        lambda: False
    )

    result = (
        project
        .refreshProtocolFromRuntimeDbForResume(
            10
        )
    )

    assert result == {
        "protocolId": 10,
        "refreshed": False,
        "reason": "legacy_project",
    }