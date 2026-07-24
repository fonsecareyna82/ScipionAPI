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


class FakeRuntimeDbMapper:
    def __init__(
            self,
            protocol=None,
            selectError=None,
    ):
        self.protocol = protocol
        self.selectError = selectError

        self.selectedIds = []
        self.closeCalls = 0

    def selectById(
            self,
            protocolId,
    ):
        self.selectedIds.append(
            protocolId
        )

        if self.selectError is not None:
            raise self.selectError

        return self.protocol

    def close(self):
        self.closeCalls += 1


def buildProject(
        tmpPath,
        protocol,
):
    staleProtocol = object()

    runtimeMapper = SimpleNamespace(
        selectRuntimeProtocolById=(
            lambda protocolId, refreshCached=False: protocol
        ),
        _runtimeProtocolsById={
            10: staleProtocol,
        },
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

    runDbPath.write_bytes(
        b"fake-runtime-db"
    )

    return str(
        runDbPath
    )


def test_RefreshProtocolForResumeLoadsProtocolDirectlyFromRunDbAndReplacesCache(
        monkeypatch,
        tmp_path,
):
    protocol = FakeProtocol()

    (
        project,
        runtimeMapper,
        staleProtocol,
    ) = buildProject(
        tmpPath=tmp_path,
        protocol=protocol,
    )

    runDbPath = createRuntimeDb(
        tmpPath=tmp_path,
        protocol=protocol,
    )

    runtimeDbMapper = FakeRuntimeDbMapper(
        protocol=protocol
    )

    createdMapperPaths = []

    def createMapper(dbPath):
        createdMapperPaths.append(
            dbPath
        )

        return runtimeDbMapper

    monkeypatch.setattr(
        project,
        "createMapper",
        createMapper,
    )

    # refreshProtocolFromRuntimeDbForResume validates that the object loaded
    # from run.db is a Protocol. FakeProtocol represents that contract here.
    monkeypatch.setattr(
        projectModule,
        "Protocol",
        FakeProtocol,
    )

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
        "source": "run_db",
    }

    assert createdMapperPaths == [
        runDbPath,
    ]

    assert runtimeDbMapper.selectedIds == [
        10,
    ]

    assert runtimeDbMapper.closeCalls == 1

    assert project.mapper is runtimeMapper

    assert protocol.mapper is runtimeMapper
    assert protocol.project is project

    assert runtimeMapper._runtimeProtocolsById[
        10
    ] is protocol

    assert runtimeMapper._runtimeProtocolsById[
        10
    ] is not staleProtocol

    assert protocol.mapperHistory == [
        runtimeMapper,
    ]

    assert protocol.projectHistory == [
        project,
    ]


def test_RefreshProtocolForResumeClosesRunDbMapperAndKeepsCacheOnFailure(
        monkeypatch,
        tmp_path,
):
    protocol = FakeProtocol()

    (
        project,
        runtimeMapper,
        staleProtocol,
    ) = buildProject(
        tmpPath=tmp_path,
        protocol=protocol,
    )

    runDbPath = createRuntimeDb(
        tmpPath=tmp_path,
        protocol=protocol,
    )

    runtimeDbMapper = FakeRuntimeDbMapper(
        selectError=RuntimeError(
            "forced runtime refresh failure"
        )
    )

    createdMapperPaths = []

    def createMapper(dbPath):
        createdMapperPaths.append(
            dbPath
        )

        return runtimeDbMapper

    monkeypatch.setattr(
        project,
        "createMapper",
        createMapper,
    )

    with pytest.raises(
            RuntimeError,
            match="forced runtime refresh failure",
    ):
        project.refreshProtocolFromRuntimeDbForResume(
            10
        )

    assert createdMapperPaths == [
        runDbPath,
    ]

    assert runtimeDbMapper.selectedIds == [
        10,
    ]

    assert runtimeDbMapper.closeCalls == 1

    assert project.mapper is runtimeMapper

    assert protocol.mapper is None
    assert protocol.project is None

    assert runtimeMapper._runtimeProtocolsById == {
        10: staleProtocol,
    }

    assert protocol.mapperHistory == []
    assert protocol.projectHistory == []


def test_RefreshProtocolForResumeDefersWhenRunDbIsMissingAndKeepsCache(
        monkeypatch,
        tmp_path,
):
    protocol = FakeProtocol()

    (
        project,
        runtimeMapper,
        staleProtocol,
    ) = buildProject(
        tmpPath=tmp_path,
        protocol=protocol,
    )

    def unexpectedCreateMapper(dbPath):
        raise AssertionError(
            "run.db mapper must not be created when run.db is missing"
        )

    monkeypatch.setattr(
        project,
        "createMapper",
        unexpectedCreateMapper,
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
        "reason": "runtime_db_not_found",
        "runDbPath": expectedRunDbPath,
        "runtimeDbRefreshDeferred": True,
    }

    assert project.mapper is runtimeMapper

    assert protocol.mapper is None
    assert protocol.project is None

    assert runtimeMapper._runtimeProtocolsById == {
        10: staleProtocol,
    }

    assert protocol.mapperHistory == []
    assert protocol.projectHistory == []


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