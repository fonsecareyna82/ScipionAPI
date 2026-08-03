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

from pathlib import Path

import pytest

import app.backend.api.services.project_service as projectServiceModule
from app.backend.api.services.project_service import (
    ProjectService,
)


class FakeProtocol:
    def __init__(
            self,
            protocolId,
            workingDir,
    ):
        self.protocolId = int(protocolId)
        self.workingDir = str(
            workingDir
        )

    def getObjId(self):
        return self.protocolId

    def getWorkingDir(self):
        return self.workingDir


class FakeRuntimeMapper:
    def __init__(self):
        self.evictCalls = []

    def evictDeletedRuntimeArtifacts(
            self,
            *,
            protocolIds,
            runtimeSetObjectIds=None,
    ):
        call = {
            "protocolIds": list(
                protocolIds
            ),
            "runtimeSetObjectIds": list(
                runtimeSetObjectIds or []
            ),
        }
        self.evictCalls.append(
            call
        )

        return {
            "protocols": {
                "evictedProtocolIds": [
                    int(protocolId)
                    for protocolId
                    in protocolIds
                ],
                "count": len(
                    protocolIds
                ),
            },
            "runtimeSetObjectIds": list(
                runtimeSetObjectIds or []
            ),
            "runtimeSetCachesCleared": True,
        }


class FakeCurrentProject:
    def __init__(
            self,
            runtimeMapper=None,
    ):
        self.runtimeMapper = (
            runtimeMapper
            or FakeRuntimeMapper()
        )
        self.deleteCalls = []
        self.executionMirrorCleanupCalls = []

    def getPostgresqlRuntimeMapper(self):
        return self.runtimeMapper

    def deleteProtocol(
            self,
            *protocols,
    ):
        self.deleteCalls.append(
            list(protocols)
        )

    def cleanupProtocolExecutionMirrors(
            self,
            *args,
            **kwargs,
    ):
        self.executionMirrorCleanupCalls.append({
            "args": args,
            "kwargs": kwargs,
        })

        raise AssertionError(
            "project.sqlite cleanup must not "
            "be used by PostgreSQL-only delete"
        )


class FakeFlatMapper:
    def __init__(self):
        self.deleteCalls = []

    def deleteProtocol(
            self,
            projectId,
            protocols,
    ):
        self.deleteCalls.append({
            "projectId": int(projectId),
            "protocols": list(
                protocols
            ),
        })


def makeService(
        projectPath,
        runtimeMapper=None,
):
    service = object.__new__(
        ProjectService
    )
    service.projectsPath = Path(
        projectPath
    )
    service.manager = None
    service.objectManager = None
    service.currentProject = (
        FakeCurrentProject(
            runtimeMapper=runtimeMapper,
        )
    )
    service.tomoList = {}
    service._getCurrentProjectPath = (
        lambda: str(
            projectPath
        )
    )

    return service


def makeProtocolDirectory(
        projectPath,
        directoryName,
):
    workingDir = (
        Path(projectPath)
        / "Runs"
        / directoryName
    )
    workingDir.mkdir(
        parents=True,
        exist_ok=True,
    )
    (
        workingDir
        / "payload.txt"
    ).write_text(
        "runtime-data",
        encoding="utf-8",
    )

    logsDir = (
        workingDir
        / "logs"
    )
    logsDir.mkdir()
    (
        logsDir
        / "run.db"
    ).write_text(
        "sqlite-runtime",
        encoding="utf-8",
    )

    return workingDir


def test_ResolveProtocolWorkingDirectoryAcceptsRelativeRunsPath(
        tmp_path,
):
    service = makeService(
        tmp_path
    )
    workingDir = makeProtocolDirectory(
        tmp_path,
        "000010_FakeProtocol",
    )
    protocol = FakeProtocol(
        10,
        "Runs/000010_FakeProtocol",
    )

    result = (
        service
        ._resolveProtocolWorkingDirectoryForDelete(
            protocol
        )
    )

    assert result == workingDir


def test_ResolveProtocolWorkingDirectoryRejectsPathOutsideRuns(
        tmp_path,
):
    service = makeService(
        tmp_path
    )
    outsideDir = (
        tmp_path
        / "outside"
    )
    outsideDir.mkdir()
    protocol = FakeProtocol(
        10,
        outsideDir,
    )

    with pytest.raises(
            RuntimeError,
            match="outside the project Runs directory",
    ):
        service._resolveProtocolWorkingDirectoryForDelete(
            protocol
        )


def test_ResolveProtocolWorkingDirectoryRejectsRunsRoot(
        tmp_path,
):
    service = makeService(
        tmp_path
    )
    runsDir = (
        tmp_path
        / "Runs"
    )
    runsDir.mkdir()
    protocol = FakeProtocol(
        10,
        runsDir,
    )

    with pytest.raises(
            RuntimeError,
            match="complete project Runs directory",
    ):
        service._resolveProtocolWorkingDirectoryForDelete(
            protocol
        )


def test_CleanupDeletesOnlyConfirmedProtocolDirectoriesAndEvictsCaches(
        tmp_path,
):
    runtimeMapper = FakeRuntimeMapper()
    service = makeService(
        tmp_path,
        runtimeMapper=runtimeMapper,
    )

    firstDir = makeProtocolDirectory(
        tmp_path,
        "000010_First",
    )
    secondDir = makeProtocolDirectory(
        tmp_path,
        "000011_Second",
    )
    untouchedDir = makeProtocolDirectory(
        tmp_path,
        "000012_Untouched",
    )

    protocols = [
        FakeProtocol(
            10,
            "Runs/000010_First",
        ),
        FakeProtocol(
            11,
            "Runs/000011_Second",
        ),
        FakeProtocol(
            12,
            "Runs/000012_Untouched",
        ),
    ]

    result = (
        service
        ._cleanupPostgresqlRuntimeProtocolDelete(
            projectId=1,
            protocols=protocols,
            deleteInfo={
                "deletedProtocolIds": [
                    "10",
                    "11",
                ],
                "runtimeSetObjectIds": [
                    9001,
                    9002,
                ],
            },
        )
    )

    assert firstDir.exists() is False
    assert secondDir.exists() is False
    assert untouchedDir.exists() is True

    assert len(
        result[
            "deletedDirectories"
        ]
    ) == 2
    assert result[
        "missingDirectories"
    ] == []
    assert result["errors"] == []
    assert result["postgresqlOnly"] is True
    assert result["usesProjectSqlite"] is False
    assert result["usesRunDb"] is False
    assert result["usesStepsSqlite"] is False

    assert len(
        runtimeMapper.evictCalls
    ) == 1
    assert set(
        runtimeMapper
        .evictCalls[0][
            "protocolIds"
        ]
    ) == {
        "10",
        "11",
    }
    assert runtimeMapper.evictCalls[0][
        "runtimeSetObjectIds"
    ] == [
        9001,
        9002,
    ]
    assert (
        service
        .currentProject
        .executionMirrorCleanupCalls
        == []
    )


def test_CleanupReportsMissingDirectoryWithoutFailure(
        tmp_path,
):
    service = makeService(
        tmp_path
    )
    protocol = FakeProtocol(
        10,
        "Runs/000010_Missing",
    )

    result = (
        service
        ._cleanupPostgresqlRuntimeProtocolDelete(
            projectId=1,
            protocols=[
                protocol,
            ],
            deleteInfo={
                "deletedProtocolIds": [
                    "10",
                ],
                "runtimeSetObjectIds": [],
            },
        )
    )

    assert result[
        "deletedDirectories"
    ] == []
    assert result["errors"] == []
    assert result[
        "missingDirectories"
    ] == [
        {
            "protocolId": "10",
            "path": str(
                tmp_path
                / "Runs"
                / "000010_Missing"
            ),
        },
    ]


def test_CleanupUnlinksProtocolDirectorySymlinkWithoutFollowingIt(
        tmp_path,
):
    service = makeService(
        tmp_path
    )
    runsDir = (
        tmp_path
        / "Runs"
    )
    runsDir.mkdir()

    externalTarget = (
        tmp_path
        / "external-target"
    )
    externalTarget.mkdir()
    (
        externalTarget
        / "keep.txt"
    ).write_text(
        "keep",
        encoding="utf-8",
    )

    linkPath = (
        runsDir
        / "000010_Link"
    )
    linkPath.symlink_to(
        externalTarget,
        target_is_directory=True,
    )

    protocol = FakeProtocol(
        10,
        "Runs/000010_Link",
    )

    result = (
        service
        ._cleanupPostgresqlRuntimeProtocolDelete(
            projectId=1,
            protocols=[
                protocol,
            ],
            deleteInfo={
                "deletedProtocolIds": [
                    "10",
                ],
                "runtimeSetObjectIds": [],
            },
        )
    )

    assert linkPath.exists() is False
    assert externalTarget.exists() is True
    assert (
        externalTarget
        / "keep.txt"
    ).exists() is True
    assert result[
        "deletedDirectories"
    ][0]["kind"] == "symlink"
    assert result["errors"] == []


def test_CleanupReportsUnsafeFilesystemPathAndDoesNotDeleteIt(
        tmp_path,
):
    service = makeService(
        tmp_path
    )
    outsideDir = (
        tmp_path
        / "outside"
    )
    outsideDir.mkdir()
    (
        outsideDir
        / "keep.txt"
    ).write_text(
        "keep",
        encoding="utf-8",
    )

    protocol = FakeProtocol(
        10,
        outsideDir,
    )

    result = (
        service
        ._cleanupPostgresqlRuntimeProtocolDelete(
            projectId=1,
            protocols=[
                protocol,
            ],
            deleteInfo={
                "deletedProtocolIds": [
                    "10",
                ],
                "runtimeSetObjectIds": [],
            },
        )
    )

    assert outsideDir.exists() is True
    assert (
        outsideDir
        / "keep.txt"
    ).exists() is True
    assert result[
        "deletedDirectories"
    ] == []
    assert len(
        result["errors"]
    ) == 1
    assert result["errors"][0][
        "protocolId"
    ] == "10"
    assert "outside the project Runs directory" in (
        result["errors"][0][
            "error"
        ]
    )


def test_CleanupReportsWorkingPathThatIsAFile(
        tmp_path,
):
    service = makeService(
        tmp_path
    )
    runsDir = (
        tmp_path
        / "Runs"
    )
    runsDir.mkdir()
    filePath = (
        runsDir
        / "000010_File"
    )
    filePath.write_text(
        "not-a-directory",
        encoding="utf-8",
    )

    protocol = FakeProtocol(
        10,
        "Runs/000010_File",
    )

    result = (
        service
        ._cleanupPostgresqlRuntimeProtocolDelete(
            projectId=1,
            protocols=[
                protocol,
            ],
            deleteInfo={
                "deletedProtocolIds": [
                    "10",
                ],
                "runtimeSetObjectIds": [],
            },
        )
    )

    assert filePath.exists() is True
    assert result[
        "deletedDirectories"
    ] == []
    assert "not a directory" in (
        result["errors"][0][
            "error"
        ]
    )


def test_DeleteProtocolWiresPostgresqlCleanupWithoutProjectSqlite(
        monkeypatch,
        tmp_path,
):
    service = makeService(
        tmp_path
    )
    mapper = FakeFlatMapper()
    captured = {}

    class FakeDeleteService:
        def deleteProtocols(
                self,
                **kwargs,
        ):
            captured.update(
                kwargs
            )

            return {
                "status": 0,
                "errors": [],
            }

    monkeypatch.setattr(
        projectServiceModule,
        "RuntimeProtocolDeleteService",
        FakeDeleteService,
    )
    service._currentProjectUsesPostgresqlRuntimeMapper = (
        lambda: True
    )
    service._getScipionProtocolForRuntime = (
        lambda **kwargs: None
    )
    service.syncProjectProtocolsAndDependencies = (
        lambda *args, **kwargs: None
    )

    result = service.deleteProtocol(
        mapper=mapper,
        projectId=1,
        protocols=[
            10,
        ],
    )

    assert result == {
        "status": 0,
        "errors": [],
    }
    assert captured[
        "usingPostgresqlRuntime"
    ] is True
    assert callable(
        captured[
            "cleanupPostgresqlRuntimeDeleteCallback"
        ]
    )
    assert (
        captured[
            "cleanupPostgresqlRuntimeDeleteCallback"
        ].__self__
        is service
    )
    assert (
        service
        .currentProject
        .executionMirrorCleanupCalls
        == []
    )