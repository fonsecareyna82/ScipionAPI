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
import logging
import os
from typing import Any, Callable, Iterable, Optional

from pyworkflow.protocol.protocol import getProtocolFromDb

logger = logging.getLogger(__name__)


class LegacyRuntimeProtocolLoaderService:
    """Load protocol snapshots from legacy run.db files during project import."""

    def resolveCurrentProjectPath(self, project: Any) -> Optional[str]:
        if project is None:
            return None

        for attrName in ("path", "_path"):
            value = getattr(project, attrName, None)

            if value:
                return str(value)

        try:
            value = project.getPath()

            if value:
                return str(value)

        except Exception:
            pass

        return None

    def resolveProtocolRunDbPath(
            self,
            protocol,
            projectPath: Optional[str] = None,
    ) -> Optional[str]:
        try:
            runDbPath = protocol.getDbPath()
        except Exception:
            runDbPath = None

        if not runDbPath:
            return None

        if os.path.isabs(str(runDbPath)):
            return os.path.abspath(str(runDbPath))

        workingDir = None

        try:
            workingDir = protocol.getWorkingDir()
        except Exception:
            workingDir = None

        if workingDir:
            workingDir = str(workingDir)

            if projectPath and not os.path.isabs(workingDir):
                workingDir = os.path.join(str(projectPath), workingDir)

            return os.path.abspath(
                os.path.join(
                    workingDir,
                    "logs",
                    os.path.basename(str(runDbPath)),
                )
            )

        if projectPath:
            return os.path.abspath(
                os.path.join(
                    str(projectPath),
                    str(runDbPath),
                )
            )

        return os.path.abspath(str(runDbPath))

    def loadProtocolFromRuntimeDb(
            self,
            protocolId: int,
            currentProject,
            getProtocolByRuntimeIdCallback: Callable,
            protocol=None,
            projectPaths: Optional[
                Iterable[str]
            ] = None,
    ):
        """
        Load a protocol snapshot from a legacy logs/run.db during project import.

        Explicit project paths are checked first so imports can read runtime
        databases from both the managed copy and the untouched source project.
        """
        if currentProject is None:
            return None

        if protocol is None:
            try:
                protocol = (
                    getProtocolByRuntimeIdCallback(
                        protocolId
                    )
                )
            except Exception:
                protocol = None

        if protocol is None:
            return None

        candidateProjectPaths = []

        def addProjectPath(value):
            if not value:
                return

            normalizedPath = os.path.abspath(
                os.path.expanduser(
                    str(value)
                )
            )

            if (
                    normalizedPath
                    not in candidateProjectPaths
            ):
                candidateProjectPaths.append(
                    normalizedPath
                )

        if isinstance(
                projectPaths,
                (
                        str,
                        os.PathLike,
                ),
        ):
            projectPaths = [
                projectPaths,
            ]

        for projectPath in (
                projectPaths or []
        ):
            addProjectPath(
                projectPath
            )

        addProjectPath(
            self.resolveCurrentProjectPath(
                currentProject
            )
        )

        for projectPath in candidateProjectPaths:
            runDbPath = (
                self.resolveProtocolRunDbPath(
                    protocol=protocol,
                    projectPath=projectPath,
                )
            )

            if (
                    not runDbPath
                    or not os.path.exists(
                str(runDbPath)
            )
            ):
                continue

            try:
                runtimeProtocol = getProtocolFromDb(
                    projectPath,
                    str(runDbPath),
                    int(protocolId),
                    chdir=False,
                )

                if runtimeProtocol is not None:
                    logger.debug(
                        "Loaded protocol snapshot from "
                        "legacy runtime database during import. "
                        "protocolId=%s projectPath=%s "
                        "runDbPath=%s",
                        protocolId,
                        projectPath,
                        runDbPath,
                    )

                    return runtimeProtocol

            except Exception:
                logger.debug(
                    "Could not load protocol from legacy runtime "
                    "database. protocolId=%s "
                    "projectPath=%s runDbPath=%s",
                    protocolId,
                    projectPath,
                    runDbPath,
                    exc_info=True,
                )

        return protocol