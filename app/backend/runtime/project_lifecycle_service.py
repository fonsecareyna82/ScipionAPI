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
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class RuntimeProjectLifecycleService:
    """Finalize managed projects as PostgreSQL-only filesystem projects."""

    LEGACY_PROJECT_DATABASE_NAME = "project.sqlite"
    LEGACY_SETTINGS_DATABASE_NAME = "settings.sqlite"
    LEGACY_RUN_DATABASE_NAME = "run.db"

    LEGACY_DATABASE_SUFFIXES = (
        "",
        "-wal",
        "-shm",
        "-journal",
    )

    # Backward-compatible alias used by the run.db cleanup.
    LEGACY_PROJECT_DATABASE_SUFFIXES = (
        LEGACY_DATABASE_SUFFIXES
    )

    def _removeLegacyDatabaseArtifacts(
            self,
            *,
            projectRoot: Path,
            databasePath: Path,
            expectedName: str,
    ) -> Dict[str, Any]:
        databasePath = (
            self._normalizeLexicalPath(
                databasePath
            )
        )

        if databasePath.name != expectedName:
            raise RuntimeError(
                "Unexpected legacy project "
                "database name: %s"
                % databasePath
            )

        self._assertPathInsideProject(
            projectRoot=projectRoot,
            candidatePath=databasePath,
        )

        deletedPaths = []
        missingPaths = []

        for suffix in (
                self.LEGACY_DATABASE_SUFFIXES
        ):
            candidatePath = Path(
                str(databasePath) + suffix
            )

            self._assertPathInsideProject(
                projectRoot=projectRoot,
                candidatePath=candidatePath,
            )

            candidateText = str(
                candidatePath
            )

            if not os.path.lexists(
                    candidateText
            ):
                missingPaths.append(
                    candidateText
                )
                continue

            if (
                    not os.path.islink(
                        candidateText
                    )
                    and os.path.isdir(
                candidateText
            )
            ):
                raise RuntimeError(
                    "Legacy project database path "
                    "is unexpectedly a directory: %s"
                    % candidatePath
                )

            # Remove the link itself without following it.
            os.unlink(
                candidateText
            )

            deletedPaths.append(
                candidateText
            )

        remainingPaths = [
            str(databasePath) + suffix
            for suffix
            in self.LEGACY_DATABASE_SUFFIXES
            if os.path.lexists(
                str(databasePath) + suffix
            )
        ]

        if remainingPaths:
            raise RuntimeError(
                "Legacy project database cleanup "
                "was incomplete: %s"
                % remainingPaths
            )

        return {
            "database": str(
                databasePath
            ),
            "deleted": deletedPaths,
            "missing": missingPaths,
        }

    @staticmethod
    def _normalizeLexicalPath(
            pathValue: Union[str, os.PathLike],
    ) -> Path:
        return Path(
            os.path.abspath(
                os.path.expanduser(
                    str(pathValue)
                )
            )
        )

    @staticmethod
    def _assertPathInsideProject(
            *,
            projectRoot: Path,
            candidatePath: Path,
    ) -> None:
        try:
            commonPath = os.path.commonpath([
                str(projectRoot),
                str(candidatePath),
            ])
        except ValueError as error:
            raise RuntimeError(
                "Could not validate project filesystem path: %s"
                % candidatePath
            ) from error

        if commonPath != str(projectRoot):
            raise RuntimeError(
                "Refusing to remove a legacy project database "
                "outside the managed project directory: %s"
                % candidatePath
            )

    def _findLegacyRunDatabaseArtifacts(
            self,
            projectRoot: Path,
    ) -> List[Path]:
        artifactNames = {
            self.LEGACY_RUN_DATABASE_NAME + suffix
            for suffix in self.LEGACY_PROJECT_DATABASE_SUFFIXES
        }

        artifacts = []

        for rootPath, directoryNames, fileNames in os.walk(
                projectRoot,
                topdown=True,
                followlinks=False,
        ):
            safeDirectoryNames = []

            for directoryName in directoryNames:
                directoryPath = Path(rootPath) / directoryName

                if os.path.islink(directoryPath):
                    if directoryName in artifactNames:
                        artifacts.append(
                            self._normalizeLexicalPath(directoryPath)
                        )

                    continue

                if directoryName in artifactNames:
                    raise RuntimeError(
                        "Legacy protocol database path is unexpectedly "
                        "a directory: %s"
                        % directoryPath
                    )

                safeDirectoryNames.append(directoryName)

            directoryNames[:] = safeDirectoryNames

            for fileName in fileNames:
                if fileName not in artifactNames:
                    continue

                databasePath = self._normalizeLexicalPath(
                    Path(rootPath) / fileName
                )

                self._assertPathInsideProject(
                    projectRoot=projectRoot,
                    candidatePath=databasePath,
                )

                artifacts.append(databasePath)

        return sorted(
            {
                str(databasePath): databasePath
                for databasePath in artifacts
            }.values(),
            key=str,
        )

    def removeLegacyProjectDatabase(
            self,
            *,
            projectPath: Union[str, os.PathLike],
            projectDbPath: Optional[
                Union[str, os.PathLike]
            ] = None,
    ) -> Dict[str, Any]:
        projectRoot = self._normalizeLexicalPath(
            projectPath
        )

        if os.path.islink(projectRoot):
            raise RuntimeError(
                "Refusing to finalize a project whose root "
                "directory is a symbolic link: %s"
                % projectRoot
            )

        if (
                not projectRoot.exists()
                or not projectRoot.is_dir()
        ):
            raise RuntimeError(
                "Project directory does not exist: %s"
                % projectRoot
            )

        if projectDbPath in (None, ""):
            databasePath = (
                projectRoot
                / self.LEGACY_PROJECT_DATABASE_NAME
            )
        else:
            databasePath = Path(
                os.path.expanduser(
                    str(projectDbPath)
                )
            )

            if not databasePath.is_absolute():
                databasePath = (
                    projectRoot
                    / databasePath
                )

            databasePath = self._normalizeLexicalPath(
                databasePath
            )

        if (
                databasePath.name
                != self.LEGACY_PROJECT_DATABASE_NAME
        ):
            raise RuntimeError(
                "Unexpected legacy project database name: %s"
                % databasePath
            )

        self._assertPathInsideProject(
            projectRoot=projectRoot,
            candidatePath=databasePath,
        )

        deletedPaths: List[str] = []
        missingPaths: List[str] = []

        for suffix in (
                self.LEGACY_PROJECT_DATABASE_SUFFIXES
        ):
            candidatePath = Path(
                str(databasePath) + suffix
            )

            self._assertPathInsideProject(
                projectRoot=projectRoot,
                candidatePath=candidatePath,
            )

            candidateText = str(candidatePath)

            if not os.path.lexists(candidateText):
                missingPaths.append(candidateText)
                continue

            if (
                    not os.path.islink(candidateText)
                    and os.path.isdir(candidateText)
            ):
                raise RuntimeError(
                    "Legacy project database path is "
                    "unexpectedly a directory: %s"
                    % candidatePath
                )

            # os.unlink removes the link itself when project.sqlite
            # is a symlink. It never follows it into the source project.
            os.unlink(candidateText)

            deletedPaths.append(candidateText)

        remainingPaths = [
            str(databasePath) + suffix
            for suffix in (
                self.LEGACY_PROJECT_DATABASE_SUFFIXES
            )
            if os.path.lexists(
                str(databasePath) + suffix
            )
        ]

        if remainingPaths:
            raise RuntimeError(
                "Legacy project database cleanup was incomplete: %s"
                % remainingPaths
            )

        return {
            "projectPath": str(projectRoot),
            "database": str(databasePath),
            "deleted": deletedPaths,
            "missing": missingPaths,
            "projectSqliteRemoved": True,
            "postgresqlOnly": True,
        }

    def removeLegacyProjectDatabase(
            self,
            *,
            projectPath: Union[
                str,
                os.PathLike,
            ],
            projectDbPath: Optional[
                Union[
                    str,
                    os.PathLike,
                ]
            ] = None,
    ) -> Dict[str, Any]:
        """
        Remove project-level SQLite databases that are
        obsolete after migrating the project to PostgreSQL.

        This includes:

          - project.sqlite
          - settings.sqlite
          - their WAL, SHM and journal artifacts

        Protocol output SQLite databases are not affected.
        """
        projectRoot = (
            self._normalizeLexicalPath(
                projectPath
            )
        )

        if os.path.islink(
                projectRoot
        ):
            raise RuntimeError(
                "Refusing to finalize a project whose "
                "root directory is a symbolic link: %s"
                % projectRoot
            )

        if (
                not projectRoot.exists()
                or not projectRoot.is_dir()
        ):
            raise RuntimeError(
                "Project directory does not exist: %s"
                % projectRoot
            )

        # Resolve the legacy project.sqlite path.
        if projectDbPath in (
                None,
                "",
        ):
            projectDatabasePath = (
                    projectRoot
                    / self.LEGACY_PROJECT_DATABASE_NAME
            )

        else:
            projectDatabasePath = Path(
                os.path.expanduser(
                    str(projectDbPath)
                )
            )

            if not projectDatabasePath.is_absolute():
                projectDatabasePath = (
                        projectRoot
                        / projectDatabasePath
                )

            projectDatabasePath = (
                self._normalizeLexicalPath(
                    projectDatabasePath
                )
            )

        # settings.sqlite always belongs to the project root.
        settingsDatabasePath = (
                projectRoot
                / self.LEGACY_SETTINGS_DATABASE_NAME
        )

        projectDatabaseReport = (
            self._removeLegacyDatabaseArtifacts(
                projectRoot=projectRoot,
                databasePath=(
                    projectDatabasePath
                ),
                expectedName=(
                    self
                    .LEGACY_PROJECT_DATABASE_NAME
                ),
            )
        )

        settingsDatabaseReport = (
            self._removeLegacyDatabaseArtifacts(
                projectRoot=projectRoot,
                databasePath=(
                    settingsDatabasePath
                ),
                expectedName=(
                    self
                    .LEGACY_SETTINGS_DATABASE_NAME
                ),
            )
        )

        deletedPaths = (
                list(
                    projectDatabaseReport.get(
                        "deleted",
                        [],
                    )
                )
                + list(
            settingsDatabaseReport.get(
                "deleted",
                [],
            )
        )
        )

        missingPaths = (
                list(
                    projectDatabaseReport.get(
                        "missing",
                        [],
                    )
                )
                + list(
            settingsDatabaseReport.get(
                "missing",
                [],
            )
        )
        )

        return {
            "projectPath": str(
                projectRoot
            ),
            # Keep the previous response field for
            # backward compatibility.
            "database": (
                projectDatabaseReport[
                    "database"
                ]
            ),
            "settingsDatabase": (
                settingsDatabaseReport[
                    "database"
                ]
            ),
            "deleted": deletedPaths,
            "missing": missingPaths,
            "projectSqliteRemoved": True,
            "settingsSqliteRemoved": True,
            "postgresqlOnly": True,
        }
