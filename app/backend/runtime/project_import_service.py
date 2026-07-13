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
import shutil
from pathlib import Path
from typing import Any, Callable, Dict


class RuntimeProjectImportService:
    """Orchestrate project import with PostgreSQL and filesystem rollback."""

    def importProject(
            self,
            *,
            mapper,
            ownerId: int,
            sourcePath: Path,
            targetPath: Path,
            projectsPath: Path,
            copyProject: bool,
            description: str,
            statusValue: str,
            migrateProjectCallback: Callable[[int, str], Dict[str, Any]],
    ) -> Dict[str, Any]:
        sourcePath = Path(sourcePath).expanduser().resolve(strict=True)
        targetPath = Path(targetPath).expanduser()
        projectsPath = Path(projectsPath).expanduser().resolve(strict=True)

        self._validateTargetPath(
            targetPath=targetPath,
            projectsPath=projectsPath,
        )

        dbProjectId = None

        try:
            self._materializeProject(
                sourcePath=sourcePath,
                targetPath=targetPath,
                copyProject=copyProject,
            )

            dbProjectId = mapper.insertProject(
                ownerId=ownerId,
                name=str(targetPath),
                description=description,
                status=statusValue,
            )

            migrationReport = migrateProjectCallback(
                int(dbProjectId),
                str(targetPath),
            )

            dbProject = mapper.getProject(
                projectId=int(dbProjectId),
                userId=ownerId,
            )

            if not dbProject:
                raise RuntimeError(
                    "Imported project could not be read from PostgreSQL"
                )

            return {
                "projectId": int(dbProjectId),
                "project": dbProject,
                "migration": migrationReport,
                "projectPath": str(targetPath),
                "copyProject": bool(copyProject),
            }

        except Exception as error:
            rollbackErrors = []
            canRemoveTarget = dbProjectId is None

            if dbProjectId is not None:
                try:
                    deleted = mapper.deleteProject(
                        int(dbProjectId),
                        ownerId,
                    )

                    if deleted:
                        canRemoveTarget = True
                    else:
                        remainingProject = mapper.getProject(
                            projectId=int(dbProjectId),
                            userId=ownerId,
                        )

                        if remainingProject:
                            rollbackErrors.append(
                                "PostgreSQL rollback did not delete project %s"
                                % dbProjectId
                            )
                        else:
                            canRemoveTarget = True

                except Exception as rollbackError:
                    rollbackErrors.append(
                        "PostgreSQL rollback failed: %s"
                        % rollbackError
                    )

            if canRemoveTarget:
                try:
                    self._removeTargetPath(targetPath)
                except Exception as rollbackError:
                    rollbackErrors.append(
                        "Filesystem rollback failed: %s"
                        % rollbackError
                    )
            else:
                rollbackErrors.append(
                    "Filesystem rollback was skipped because "
                    "the PostgreSQL project row still exists"
                )

            detail = "Project import failed: %s" % error

            if rollbackErrors:
                detail += ". " + "; ".join(rollbackErrors)

            raise RuntimeError(detail) from error

    @staticmethod
    def _validateTargetPath(
            *,
            targetPath: Path,
            projectsPath: Path,
    ) -> None:
        targetParent = targetPath.parent.resolve(strict=False)

        if targetParent != projectsPath:
            raise RuntimeError(
                "Import target must be a direct child of PROJECTS_PATH: %s"
                % targetPath
            )

        if os.path.lexists(targetPath):
            raise RuntimeError(
                "Import target already exists: %s"
                % targetPath
            )

    @staticmethod
    def _materializeProject(
            *,
            sourcePath: Path,
            targetPath: Path,
            copyProject: bool,
    ) -> None:
        targetPath.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if copyProject:
            shutil.copytree(
                str(sourcePath),
                str(targetPath),
                symlinks=True,
            )
        else:
            targetPath.symlink_to(
                sourcePath,
                target_is_directory=True,
            )

    @staticmethod
    def _removeTargetPath(targetPath: Path) -> None:
        if not os.path.lexists(targetPath):
            return

        if targetPath.is_symlink():
            targetPath.unlink()
            return

        if targetPath.is_dir():
            shutil.rmtree(targetPath)
            return

        targetPath.unlink()
