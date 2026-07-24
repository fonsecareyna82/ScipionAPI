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
from typing import Any, Dict

from pyworkflow.protocol.protocol import Protocol


logger = logging.getLogger(__name__)


class RuntimeProtocolExecutionDbService:
    """
    Build the native logs/run.db execution database directly from PostgreSQL.
    """

    SQLITE_SIDECAR_SUFFIXES = (
        "",
        "-journal",
        "-wal",
        "-shm",
    )

    def prepareExecutionDatabase(
            self,
            currentProject,
            protocol,
    ) -> Dict[str, Any]:
        if currentProject is None:
            raise ValueError("currentProject is required")

        if protocol is None:
            raise ValueError("protocol is required")

        runtimeMapper = (
            currentProject.getPostgresqlRuntimeMapper()
        )

        if runtimeMapper is None:
            raise RuntimeError(
                "PostgreSQL runtime mapper is not available."
            )

        protocolId = getattr(
            protocol,
            "getObjId",
            lambda: None,
        )()

        if protocolId in (None, ""):
            raise RuntimeError(
                "Cannot prepare execution database "
                "for a protocol without id."
            )

        executionDbPath = str(
            protocol.getDbPath()
        )

        if not os.path.isabs(executionDbPath):
            executionDbPath = os.path.abspath(
                os.path.join(
                    currentProject.path,
                    executionDbPath,
                )
            )

        os.makedirs(
            os.path.dirname(executionDbPath),
            exist_ok=True,
        )

        for suffix in self.SQLITE_SIDECAR_SUFFIXES:
            candidatePath = (
                executionDbPath + suffix
            )

            if os.path.isfile(candidatePath):
                os.remove(candidatePath)

        executionMapper = None

        try:
            # PostgresqlProject.createMapper() delegates non-project SQLite
            # databases to Scipion's regular SQLite mapper.
            executionMapper = currentProject.createMapper(
                executionDbPath
            )

            snapshotReport = (
                runtimeMapper
                .materializeProjectExecutionSnapshot(
                    sqliteMapper=executionMapper,
                    activeProtocol=protocol,
                )
            )

            storedProtocol = executionMapper.selectById(
                int(protocolId)
            )

            if not isinstance(storedProtocol, Protocol):
                raise RuntimeError(
                    "Protocol %s was not found in the generated run.db."
                    % protocolId
                )

            executionMapper.commit()

        except Exception:
            for suffix in self.SQLITE_SIDECAR_SUFFIXES:
                candidatePath = (
                    executionDbPath + suffix
                )

                try:
                    if os.path.isfile(candidatePath):
                        os.remove(candidatePath)
                except Exception:
                    logger.debug(
                        "Could not remove failed execution DB file: %s",
                        candidatePath,
                        exc_info=True,
                    )

            raise

        finally:
            if executionMapper is not None:
                try:
                    executionMapper.close()
                except Exception:
                    logger.debug(
                        "Could not close protocol execution mapper.",
                        exc_info=True,
                    )

        report = {
            "projectId": runtimeMapper.projectId,
            "protocolId": int(protocolId),
            "executionDbPath": executionDbPath,
            "projectSqliteUsed": False,
            "snapshot": snapshotReport,
        }

        logger.info(
            "Prepared protocol run.db directly from PostgreSQL. "
            "report=%s",
            report,
        )

        return report