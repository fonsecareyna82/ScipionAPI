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

from app.backend.runtime.project_lifecycle_service import (
    RuntimeProjectLifecycleService,
)


def test_RemoveLegacyRunDatabasesRemovesOnlyRuntimeDatabases(
        tmp_path,
):
    projectPath = tmp_path / "project"
    firstRunPath = (
        projectPath
        / "Runs"
        / "000001_ProtImport"
        / "logs"
    )
    secondRunPath = (
        projectPath
        / "Runs"
        / "000002_ProtProcess"
        / "logs"
    )

    firstRunPath.mkdir(
        parents=True,
        exist_ok=True,
    )
    secondRunPath.mkdir(
        parents=True,
        exist_ok=True,
    )

    runtimeFiles = [
        firstRunPath / "run.db",
        firstRunPath / "run.db-wal",
        firstRunPath / "run.db-shm",
        secondRunPath / "run.db",
        secondRunPath / "run.db-journal",
    ]

    for runtimeFile in runtimeFiles:
        runtimeFile.write_text("legacy")

    outputDatabase = (
        projectPath
        / "Runs"
        / "000001_ProtImport"
        / "output.sqlite"
    )
    stepsDatabase = secondRunPath / "steps.sqlite"

    outputDatabase.write_text("output")
    stepsDatabase.write_text("steps")

    report = (
        RuntimeProjectLifecycleService()
        .removeLegacyRunDatabases(
            projectPath=projectPath,
        )
    )

    assert report["legacyRunDatabasesRemoved"] is True
    assert report["deletedCount"] == len(runtimeFiles)
    assert report["remaining"] == []

    assert all(
        not runtimeFile.exists()
        for runtimeFile in runtimeFiles
    )

    assert outputDatabase.exists()
    assert stepsDatabase.exists()


def test_RemoveLegacyRunDatabasesDoesNotFollowSymlinkDirectories(
        tmp_path,
):
    projectPath = tmp_path / "project"
    runsPath = projectPath / "Runs"
    externalPath = tmp_path / "external-run"

    runsPath.mkdir(
        parents=True,
        exist_ok=True,
    )
    externalPath.mkdir(
        parents=True,
        exist_ok=True,
    )

    externalRunDatabase = externalPath / "run.db"
    externalRunDatabase.write_text("external")

    linkedRunPath = runsPath / "linked-run"
    linkedRunPath.symlink_to(
        externalPath,
        target_is_directory=True,
    )

    report = (
        RuntimeProjectLifecycleService()
        .removeLegacyRunDatabases(
            projectPath=projectPath,
        )
    )

    assert report["deletedCount"] == 0
    assert externalRunDatabase.exists()
    assert linkedRunPath.is_symlink()


def test_RemoveLegacyProjectDatabasesRemovesSettingsArtifacts(
        tmp_path,
):
    projectPath = (
        tmp_path
        / "project"
    )

    projectPath.mkdir(
        parents=True,
        exist_ok=True,
    )

    legacyFiles = [
        projectPath / "project.sqlite",
        projectPath / "project.sqlite-wal",
        projectPath / "project.sqlite-shm",
        projectPath / "settings.sqlite",
        projectPath / "settings.sqlite-wal",
        projectPath / "settings.sqlite-journal",
    ]

    for legacyFile in legacyFiles:
        legacyFile.write_text(
            "legacy"
        )

    outputDatabase = (
        projectPath
        / "output.sqlite"
    )

    outputDatabase.write_text(
        "output"
    )

    report = (
        RuntimeProjectLifecycleService()
        .removeLegacyProjectDatabase(
            projectPath=projectPath,
        )
    )

    assert (
        report["projectSqliteRemoved"]
        is True
    )

    assert (
        report["settingsSqliteRemoved"]
        is True
    )

    assert all(
        not legacyFile.exists()
        for legacyFile in legacyFiles
    )

    # Other SQLite outputs are not legacy
    # project infrastructure.
    assert outputDatabase.exists()


