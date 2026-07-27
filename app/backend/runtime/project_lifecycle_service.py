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

    LEGACY_PROJECT_DATABASE_SUFFIXES = (
        "",
        "-wal",
        "-shm",
        "-journal",
    )

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