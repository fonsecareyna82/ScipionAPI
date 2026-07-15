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
from typing import Any, Callable, Optional

from pyworkflow.protocol.protocol import getProtocolFromDb

logger = logging.getLogger(__name__)


class RuntimeProtocolLoaderService:
    """Resolve Scipion project paths and load runtime protocols from run.db."""

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
    ):
        """
        Load the real runtime protocol from logs/run.db.

        This is the source of truth after launch, because the external Scipion
        runner updates that database while the protocol is executing.
        """
        if currentProject is None:
            return None

        if protocol is None:
            try:
                protocol = getProtocolByRuntimeIdCallback(
                    protocolId
                )
            except Exception:
                protocol = None

        if protocol is None:
            return None

        projectPath = self.resolveCurrentProjectPath(currentProject)

        runDbPath = self.resolveProtocolRunDbPath(
            protocol=protocol,
            projectPath=projectPath,
        )

        if not runDbPath:
            return protocol

        if not os.path.exists(str(runDbPath)):
            logger.debug(
                "Runtime db does not exist yet. protocolId=%s runDbPath=%s",
                protocolId,
                runDbPath,
            )
            return protocol

        if not projectPath:
            return protocol

        try:
            runtimeProtocol = getProtocolFromDb(
                projectPath,
                str(runDbPath),
                int(protocolId),
                chdir=False,
            )

            if runtimeProtocol is not None:
                return runtimeProtocol

        except Exception:
            logger.debug(
                "Could not load protocol from runtime db. protocolId=%s runDbPath=%s",
                protocolId,
                runDbPath,
                exc_info=True,
            )

        return protocol