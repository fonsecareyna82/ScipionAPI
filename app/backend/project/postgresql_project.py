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
import signal
import subprocess
import json
import logging
import os
import psutil
from typing import Any, Dict, Optional

import pyworkflow as pw
from pyworkflow import PROJECT_DBNAME
from pyworkflow.project import Project as ScipionProject
from pyworkflow.project.project import REGEX_NUMBER_ENDING
from pyworkflow.protocol.constants import (
    MODE_RESTART,
    STATUS_SAVED,
    STATUS_SCHEDULED,
)
from pyworkflow.protocol.protocol import Protocol
import pyworkflow.protocol as pwprot
import pyworkflow.utils as pwutils

from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.mapper.postgresql_runtime_mapper import PostgresqlRuntimeMapper
from app.backend.runtime.protocol_execution_db_service import RuntimeProtocolExecutionDbService

logger = logging.getLogger(__name__)


class PostgresqlProject(ScipionProject):
    """
    PostgreSQL-aware Scipion Project.

    This class keeps Scipion's normal project paths,
    hosts and protocol setup logic, while replacing
    Project.mapper with PostgresqlRuntimeMapper.

    Project data and effective runtime settings are
    PostgreSQL-backed. Project-local project.sqlite
    and settings.sqlite databases are not required.
    """

    def __init__(self, domain, path: str, projectId: int, flatMapper: PostgresqlFlatMapper):
        super().__init__(domain, path)

        if projectId is None:
            raise ValueError("projectId is required")
        if flatMapper is None:
            raise ValueError("flatMapper is required")

        self.postgresqlProjectId = int(projectId)
        self.postgresqlFlatMapper = flatMapper
        self._postgresqlRuntimeMapper: Optional[PostgresqlRuntimeMapper] = None

    def _loadDb(self, dbPath=None):
        """Load PostgreSQL for the project database and SQLite only for legacy runtime databases."""
        if dbPath is not None:
            self.setDbPath(dbPath)

        sqlitePath = self._normalizeSqlitePath(self.dbPath)

        if sqlitePath and os.path.basename(sqlitePath) != PROJECT_DBNAME:
            self.mapper = self.createMapper(sqlitePath)
            return

        self.mapper = self.createMapper(None)

    def createMapper(self, sqliteFn):
        """Use PostgreSQL for the project and SQLite only for legacy runtime databases."""
        sqlitePath = self._normalizeSqlitePath(sqliteFn)

        if sqlitePath and os.path.basename(sqlitePath) != PROJECT_DBNAME:
            logger.info("Creating legacy SQLite mapper for protocol runtime db: %s", sqlitePath)
            return ScipionProject.createMapper(self, sqlitePath)

        runtimeMapper = PostgresqlRuntimeMapper(
            flatMapper=self.postgresqlFlatMapper,
            projectId=self.postgresqlProjectId,
            project=self,
        )

        self._postgresqlRuntimeMapper = runtimeMapper
        return runtimeMapper

    def getPostgresqlRuntimeMapper(self) -> Optional[PostgresqlRuntimeMapper]:
        return self._postgresqlRuntimeMapper

    def usingPostgresqlRuntimeMapper(self) -> bool:
        return isinstance(self.mapper, PostgresqlRuntimeMapper)

    def _updateProtocol(
            self,
            protocol: Protocol,
            tries=0,
            checkPid=False,
    ):
        """
        Refresh a PostgreSQL runtime protocol from PostgreSQL only.

        Scipion's native implementation reads logs/run.db and checks the
        protocol PID or queue job. Those sources do not belong to protocols
        executed by the PostgreSQL worker and must never change their status.

        Reading or refreshing a project must therefore remain read-only with
        respect to protocol execution state.
        """
        if not self.usingPostgresqlRuntimeMapper():
            return super()._updateProtocol(
                protocol,
                tries=tries,
                checkPid=checkPid,
            )

        if protocol is None:
            return pw.NOT_UPDATED_UNNECESSARY

        previousStatus = str(
            protocol.getStatus()
            or ""
        ).strip().lower()

        try:
            self.mapper.updateFrom(
                protocol
            )
        except Exception:
            logger.exception(
                "Could not refresh PostgreSQL runtime protocol. "
                "projectId=%s protocolId=%s",
                self.postgresqlProjectId,
                getattr(
                    protocol,
                    "getObjId",
                    lambda: None,
                )(),
            )

            return pw.NOT_UPDATED_ERROR

        currentStatus = str(
            protocol.getStatus()
            or ""
        ).strip().lower()

        if currentStatus != previousStatus:
            return pw.PROTOCOL_UPDATED

        return pw.NOT_UPDATED_UNNECESSARY

    def _normalizeSqlitePath(self, sqliteFn) -> Optional[str]:
        if not sqliteFn:
            return None

        sqlitePath = str(sqliteFn)

        if os.path.isabs(sqlitePath):
            return sqlitePath

        return os.path.abspath(os.path.join(self.path, sqlitePath))

    def closeMapper(self):
        """Close the PostgreSQL runtime mapper."""
        runtimeMapper = self._postgresqlRuntimeMapper

        try:
            if runtimeMapper is not None:
                runtimeMapper.close()
        finally:
            self.mapper = None
            self._postgresqlRuntimeMapper = None

    def closeMapper(self):
        """
        Close the PostgreSQL runtime mapper and the SQLite write mirror.
        """
        runtimeMapper = self._postgresqlRuntimeMapper
        writeFallbackMapper = self._writeFallbackMapper

        try:
            if runtimeMapper is not None:
                runtimeMapper.close()

            if writeFallbackMapper is not None:
                try:
                    writeFallbackMapper.close()
                except Exception:
                    logger.debug(
                        "Could not close PostgreSQL project write fallback mapper.",
                        exc_info=True,
                    )
        finally:
            self.mapper = None
            self._postgresqlRuntimeMapper = None
            self._writeFallbackMapper = None

    # ---------------------------------------------------
    #               PROTOCOLS
    # --------------------------------------------------
    def _setPostgresqlProtocolLabel(self, protocol):
        defaultLabel = protocol.getClassLabel()
        maxSuffix = 0

        for otherLabel in self.mapper.getPostgresqlProtocolLabels():
            match = REGEX_NUMBER_ENDING.match(otherLabel)

            if (
                    match
                    and match.group("prefix").strip() == defaultLabel
            ):
                suffix = match.group("number").strip("()")

                try:
                    maxSuffix = max(
                        int(suffix),
                        maxSuffix,
                    )
                except (TypeError, ValueError):
                    logger.error(
                        "Could not calculate protocol label suffix: %s",
                        suffix,
                    )

            elif otherLabel == defaultLabel:
                maxSuffix = max(1, maxSuffix)

        if maxSuffix:
            label = "%s (%d)" % (
                defaultLabel,
                maxSuffix + 1,
            )
        else:
            label = defaultLabel

        protocol.setObjLabel(label)

    def newProtocol(self, protocolClass, **kwargs):
        if not self.usingPostgresqlRuntimeMapper():
            return super().newProtocol(
                protocolClass,
                **kwargs,
            )

        protocol = protocolClass(
            project=self,
            **kwargs,
        )

        if not protocol.getObjLabel():
            self._setPostgresqlProtocolLabel(protocol)

        protocol.setMapper(self.mapper)
        protocol.setProject(self)

        return protocol

    def _getProtocolsDependencies(
            self,
            protocols,
    ) -> str:
        """
        Check blocking protocol dependants using PostgreSQL instead of
        rebuilding Scipion's complete runs graph.

        This preserves the native Project semantics: a dependant protocol
        blocks relaunch unless it is saved, scheduled, or included in the
        same mutation group.
        """
        if not self.usingPostgresqlRuntimeMapper():
            return super()._getProtocolsDependencies(
                protocols
            )

        selectedProtocolIds = {
            str(protocolId)
            for protocolId in (
                getattr(
                    protocol,
                    "getObjId",
                    lambda: None,
                )()
                for protocol in protocols or []
            )
            if protocolId not in (None, "")
        }

        if not selectedProtocolIds:
            return ""

        adjacency = (
            self.postgresqlFlatMapper
            .getProjectProtocolAdjacencyMap(
                self.postgresqlProjectId
            )
        )

        protocolRows = (
            self.postgresqlFlatMapper
            .getProtocols(
                self.postgresqlProjectId
            )
            or []
        )

        rowsByProtocolId = {
            str(row.get("protocolId")): row
            for row in protocolRows
            if row.get("protocolId")
            not in (None, "")
        }

        nonBlockingStatuses = {
            str(STATUS_SAVED)
            .strip()
            .lower(),

            str(STATUS_SCHEDULED)
            .strip()
            .lower(),
        }

        errorParts = []

        for protocol in protocols or []:
            protocolId = getattr(
                protocol,
                "getObjId",
                lambda: None,
            )()

            if protocolId in (None, ""):
                continue

            protocolIdText = str(
                protocolId
            )

            childProtocolIds = (
                adjacency
                .get(
                    protocolIdText,
                    {},
                )
                .get(
                    "children",
                    [],
                )
                or []
            )

            blockingChildren = []

            for childProtocolId in childProtocolIds:
                childProtocolIdText = str(
                    childProtocolId
                )

                if (
                        childProtocolIdText
                        in selectedProtocolIds
                ):
                    continue

                childRow = rowsByProtocolId.get(
                    childProtocolIdText
                )

                if not childRow:
                    continue

                childStatus = str(
                    childRow.get("status")
                    or ""
                ).strip().lower()

                if (
                        childStatus
                        in nonBlockingStatuses
                ):
                    continue

                blockingChildren.append(
                    self._getPostgresqlProtocolLabel(
                        childRow
                    )
                )

            if not blockingChildren:
                continue

            try:
                protocolLabel = (
                    protocol.getRunName()
                )
            except Exception:
                protocolLabel = (
                    protocolIdText
                )

            errorParts.append(
                "\n *%s* is referenced from:\n   - %s"
                % (
                    protocolLabel,
                    "\n   - ".join(
                        blockingChildren
                    ),
                )
            )

        return "".join(errorParts)

    @staticmethod
    def _getPostgresqlProtocolLabel(
            protocolRow: Dict[str, Any],
    ) -> str:
        params = protocolRow.get(
            "params"
        ) or {}

        if isinstance(params, str):
            try:
                params = json.loads(
                    params
                )
            except Exception:
                params = {}

        if not isinstance(params, dict):
            params = {}

        for key in (
                "runName",
                "_runName",
                "title",
                "_title",
        ):
            value = params.get(key)

            if isinstance(value, dict):
                for valueKey in (
                        "value",
                        "editableValue",
                        "default",
                        "objValue",
                        "_value",
                ):
                    if valueKey in value:
                        value = value.get(
                            valueKey
                        )
                        break

            valueText = str(
                value or ""
            ).strip()

            if valueText:
                return valueText

        className = str(
            protocolRow.get(
                "protocolClassName"
            )
            or "Protocol"
        )

        protocolId = str(
            protocolRow.get(
                "protocolId"
            )
            or ""
        )

        return "%s (%s)" % (
            className,
            protocolId,
        )

    def _preparePostgresqlExecutionDatabase(
            self,
            protocol,
    ) -> Dict[str, Any]:
        service = RuntimeProtocolExecutionDbService()

        return service.prepareExecutionDatabase(
            currentProject=self,
            protocol=protocol,
        )

    def _startPostgresqlProtocolWorker(
            self,
            *,
            protocol,
            runMode: str,
            wait: bool = False,
    ):
        from app.backend.runtime.postgresql_protocol_worker import (
            buildPostgresqlWorkerCommand,
        )

        command = buildPostgresqlWorkerCommand(
            projectId=self.postgresqlProjectId,
            protocolId=int(
                protocol.getObjId()
            ),
            runMode=runMode,
        )

        process = subprocess.Popen(
            command,
            cwd=self.path,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )

        protocol.setPid(
            process.pid
        )

        self.mapper.store(
            protocol
        )

        self.mapper.commit()

        logger.info(
            "Started isolated PostgreSQL protocol worker. "
            "projectId=%s protocolId=%s pid=%s "
            "processGroupId=%s runMode=%s",
            self.postgresqlProjectId,
            protocol.getObjId(),
            process.pid,
            os.getpgid(
                process.pid
            ),
            runMode,
        )

        if wait:
            returnCode = process.wait()

            self.mapper.updateFrom(
                protocol
            )

            if returnCode != 0:
                raise RuntimeError(
                    "PostgreSQL protocol worker %s "
                    "finished with return code %s."
                    % (
                        protocol.getObjId(),
                        returnCode,
                    )
                )

        return process

    def launchProtocol(
            self,
            protocol: Protocol,
            wait=False,
            scheduled=False,
            force=False,
    ):
        if not self.usingPostgresqlRuntimeMapper():
            return super().launchProtocol(
                protocol,
                wait=wait,
                scheduled=scheduled,
                force=force,
            )

        if (
                protocol.getPrerequisites()
                and not scheduled
        ):
            return self.scheduleProtocol(
                protocol
            )

        isRestart = (
                protocol.getRunMode()
                == MODE_RESTART
        )

        if not force:
            if (
                    (
                            not protocol.isInteractive()
                            and not protocol.isInStreaming()
                    )
                    or isRestart
            ):
                self._checkModificationAllowed(
                    [protocol],
                    "Cannot RE-LAUNCH protocol",
                )

        previousStatus = (
                protocol.getStatus()
                or STATUS_SAVED
        )

        self._setupProtocol(
            protocol
        )

        if not scheduled:
            protocol.makePathsAndClean()

        if isRestart:
            self.mapper.deleteRelations(
                protocol
            )

        protocol.cleanExecutionAttributes()

        protocol.setStatus(
            STATUS_SCHEDULED
        )

        self.mapper.store(
            protocol
        )

        self.mapper.commit()

        runMode = (
            "restart"
            if isRestart
            else "resume"
        )

        try:
            return (
                self
                ._startPostgresqlProtocolWorker(
                    protocol=protocol,
                    runMode=runMode,
                    wait=wait,
                )
            )

        except Exception:
            protocol.setStatus(
                previousStatus
            )

            protocol.setPid(
                0
            )

            self.mapper.store(
                protocol
            )

            self.mapper.commit()

            raise

    def scheduleProtocol(
            self,
            protocol,
            prerequisites=None,
            initialSleepTime=0,
    ):
        if not self.usingPostgresqlRuntimeMapper():
            return super().scheduleProtocol(
                protocol,
                prerequisites=(
                        prerequisites or []
                ),
                initialSleepTime=(
                    initialSleepTime
                ),
            )

        prerequisites = (
                prerequisites or []
        )

        isRestart = (
                protocol.getRunMode()
                == MODE_RESTART
        )

        protocol.addPrerequisites(
            *prerequisites
        )

        self._setupProtocol(
            protocol
        )

        protocol.makePathsAndClean()

        if isRestart:
            self.mapper.deleteRelations(
                protocol
            )

        protocol.cleanExecutionAttributes()

        protocol.setStatus(
            STATUS_SCHEDULED
        )

        self.mapper.store(
            protocol
        )

        self.mapper.commit()

        runMode = (
            "restart"
            if isRestart
            else "resume"
        )

        try:
            return (
                self
                ._startPostgresqlProtocolWorker(
                    protocol=protocol,
                    runMode=runMode,
                    wait=False,
                )
            )

        except Exception:
            protocol.setStatus(
                STATUS_SAVED
            )

            protocol.setPid(
                0
            )

            self.mapper.store(
                protocol
            )

            self.mapper.commit()

            raise

    def resetProtocol(self, protocol):
        """
        Reset the PostgreSQL-runtime protocol through its SQLite execution
        mirror.

        Scipion's native resetProtocol() finishes by calling
        protocol._store(). That store must use the SQLite execution mapper,
        not PostgresqlRuntimeMapper.
        """
        if not self.usingPostgresqlRuntimeMapper():
            return super().resetProtocol(
                protocol
            )

        runtimeMapper = (
            self.getPostgresqlRuntimeMapper()
        )

        if runtimeMapper is None:
            raise RuntimeError(
                "Cannot reset PostgreSQL runtime protocol: "
                "runtime mapper is not available"
            )

        writeFallbackMapper = getattr(
            runtimeMapper,
            "writeFallbackMapper",
            None,
        )

        ownsWriteFallbackMapper = False

        if writeFallbackMapper is None:
            sqlitePath = self._normalizeSqlitePath(
                PROJECT_DBNAME
            )

            if (
                    not sqlitePath
                    or not os.path.exists(sqlitePath)
            ):
                raise RuntimeError(
                    "Cannot reset PostgreSQL runtime protocol: "
                    "SQLite execution mirror database is not available"
                )

            writeFallbackMapper = (
                ScipionProject.createMapper(
                    self,
                    sqlitePath,
                )
            )

            ownsWriteFallbackMapper = True

        protocolId = getattr(
            protocol,
            "getObjId",
            lambda: None,
        )()

        if protocolId in (None, ""):
            if ownsWriteFallbackMapper:
                writeFallbackMapper.close()

            raise RuntimeError(
                "Cannot reset PostgreSQL runtime protocol "
                "without protocol id"
            )

        protocolId = int(protocolId)

        sqliteProtocol = (
            writeFallbackMapper.selectById(
                protocolId
            )
        )

        if sqliteProtocol is None:
            if ownsWriteFallbackMapper:
                writeFallbackMapper.close()

            raise RuntimeError(
                "Protocol %s was not found in the "
                "SQLite execution mirror"
                % protocolId
            )

        originalMapper = self.mapper

        try:
            self.mapper = writeFallbackMapper

            sqliteProtocol.setMapper(
                writeFallbackMapper
            )

            sqliteProtocol.setProject(
                self
            )

            try:
                ScipionProject.resetProtocol(
                    self,
                    sqliteProtocol,
                )

            except psutil.NoSuchProcess as error:
                # Scipion resets the protocol inside resetProtocol()'s
                # finally block. A stale PID only means that the process
                # had already finished before the reset attempted to
                # stop it.
                if not sqliteProtocol.isSaved():
                    raise

                logger.info(
                    "Ignoring stale process PID during protocol reset. "
                    "projectId=%s protocolId=%s pid=%s",
                    self.postgresqlProjectId,
                    protocolId,
                    getattr(
                        error,
                        "pid",
                        None,
                    ),
                )

            writeFallbackMapper.commit()

        finally:
            self.mapper = originalMapper

            sqliteProtocol.setMapper(
                runtimeMapper
            )

            sqliteProtocol.setProject(
                self
            )

            if ownsWriteFallbackMapper:
                try:
                    writeFallbackMapper.close()
                except Exception:
                    logger.debug(
                        "Could not close isolated SQLite "
                        "reset mapper.",
                        exc_info=True,
                    )

        runtimeMapper._runtimeProtocolsById[
            protocolId
        ] = sqliteProtocol

        runtimeMapper._sqliteProtocolMirrorIds.add(
            protocolId
        )

        return sqliteProtocol

    def stopProtocol(self, protocol):
        """
        Stop a PostgreSQL-runtime protocol through the SQLite compatibility
        mapper.

        Scipion's native Project.stopProtocol() refreshes the protocol from
        logs/run.db before stopping it. During that refresh, Project._updateProtocol()
        temporarily assigns Project.mapper to the protocol.

        Using PostgresqlRuntimeMapper there makes Protocol.copy() persist a
        partially updated runtime object through both PostgreSQL and SQLite,
        which can produce circular object references.

        Temporarily using the project SQLite mapper preserves Scipion's native
        stop behaviour:

          - refresh PID and job ids from logs/run.db;
          - stop local or queue execution;
          - persist the aborted status to run.db;
          - mirror the final protocol into project.sqlite.

        PostgreSQL is synchronized afterwards by RuntimeProtocolStopService.
        """
        if not self.usingPostgresqlRuntimeMapper():
            return super().stopProtocol(protocol)

        runtimeMapper = self.getPostgresqlRuntimeMapper()

        if runtimeMapper is None:
            raise RuntimeError(
                "Cannot stop PostgreSQL runtime protocol: "
                "runtime mapper is not available"
            )

        writeFallbackMapper = getattr(
            runtimeMapper,
            "writeFallbackMapper",
            None,
        )

        ownsWriteFallbackMapper = False

        if writeFallbackMapper is None:
            sqlitePath = self._normalizeSqlitePath(PROJECT_DBNAME)

            if not sqlitePath or not os.path.exists(sqlitePath):
                raise RuntimeError(
                    "Cannot stop PostgreSQL runtime protocol: "
                    "SQLite execution mirror database is not available"
                )

            writeFallbackMapper = ScipionProject.createMapper(
                self,
                sqlitePath,
            )

            ownsWriteFallbackMapper = True

        protocolId = getattr(
            protocol,
            "getObjId",
            lambda: None,
        )()

        if protocolId in (None, ""):
            if ownsWriteFallbackMapper:
                writeFallbackMapper.close()

            raise RuntimeError(
                "Cannot stop PostgreSQL runtime protocol without protocol id"
            )

        sqliteProtocol = writeFallbackMapper.selectById(
            int(protocolId)
        )

        if sqliteProtocol is None:
            if ownsWriteFallbackMapper:
                writeFallbackMapper.close()

            raise RuntimeError(
                "Protocol %s was not found in the SQLite compatibility database"
                % protocolId
            )

        originalMapper = self.mapper

        try:
            logger.info(
                "Stopping PostgreSQL runtime protocol through isolated SQLite "
                "compatibility mapper. projectId=%s protocolId=%s",
                self.postgresqlProjectId,
                protocolId,
            )

            self.mapper = writeFallbackMapper

            sqliteProtocol.setMapper(
                writeFallbackMapper
            )

            sqliteProtocol.setProject(
                self
            )

            return ScipionProject.stopProtocol(
                self,
                sqliteProtocol,
            )

        finally:
            self.mapper = originalMapper

            if ownsWriteFallbackMapper:
                try:
                    writeFallbackMapper.close()
                except Exception:
                    logger.debug(
                        "Could not close isolated SQLite stop mapper.",
                        exc_info=True,
                    )

    def refreshProtocolFromRuntimeDbForResume(
            self,
            protocolId: int,
    ) -> Dict[str, Any]:
        protocolId = int(protocolId)

        if not self.usingPostgresqlRuntimeMapper():
            return {
                "protocolId": protocolId,
                "refreshed": False,
                "reason": "legacy_project",
            }

        runtimeMapper = (
            self.getPostgresqlRuntimeMapper()
        )

        if runtimeMapper is None:
            raise RuntimeError(
                "Cannot refresh protocol runtime state: "
                "PostgreSQL runtime mapper is not available."
            )

        postgresqlProtocol = (
            runtimeMapper.selectRuntimeProtocolById(
                protocolId,
                refreshCached=False,
            )
        )

        if postgresqlProtocol is None:
            raise RuntimeError(
                "Protocol %s was not found in PostgreSQL runtime."
                % protocolId
            )

        runDbPath = self._resolveProtocolRuntimeDbPath(
            postgresqlProtocol
        )

        if (
                not os.path.isfile(runDbPath)
                or os.path.getsize(runDbPath) == 0
        ):
            logger.info(
                "Skipping runtime DB refresh for first protocol launch. "
                "projectId=%s protocolId=%s runDbPath=%s",
                self.postgresqlProjectId,
                protocolId,
                runDbPath,
            )

            return {
                "protocolId": protocolId,
                "refreshed": False,
                "reason": "runtime_db_not_found",
                "runDbPath": runDbPath,
                "runtimeDbRefreshDeferred": True,
            }

        runtimeDbMapper = None

        try:
            # Non-project SQLite paths are delegated by createMapper() to
            # Scipion's native SQLite mapper.
            runtimeDbMapper = self.createMapper(
                runDbPath
            )

            runtimeProtocol = (
                runtimeDbMapper.selectById(
                    protocolId
                )
            )

            if not isinstance(
                    runtimeProtocol,
                    Protocol,
            ):
                raise RuntimeError(
                    "Invalid runtime protocol %s loaded from %s: %s"
                    % (
                        protocolId,
                        runDbPath,
                        (
                            runtimeProtocol
                            .__class__
                            .__name__
                            if runtimeProtocol is not None
                            else "None"
                        ),
                    )
                )

        finally:
            if runtimeDbMapper is not None:
                try:
                    runtimeDbMapper.close()
                except Exception:
                    logger.debug(
                        "Could not close isolated run.db mapper.",
                        exc_info=True,
                    )

        runtimeProtocol.setMapper(
            runtimeMapper
        )

        runtimeProtocol.setProject(
            self
        )

        runtimeMapper._runtimeProtocolsById[
            protocolId
        ] = runtimeProtocol

        logger.info(
            "Loaded PostgreSQL runtime protocol directly from run.db "
            "before resume. projectId=%s protocolId=%s runDbPath=%s",
            self.postgresqlProjectId,
            protocolId,
            runDbPath,
        )

        return {
            "protocolId": protocolId,
            "refreshed": True,
            "runDbPath": runDbPath,
            "source": "run_db",
        }

    def cleanupProtocolExecutionMirrors(self, protocolIds):
        protocolIds = [
            int(protocolId)
            for protocolId in protocolIds or []
            if protocolId not in (None, "",)
        ]

        report = {
            "requestedProtocolIds": protocolIds,
            "deletedProtocolIds": [],
            "missingProtocolIds": [],
            "errors": [],
        }

        if not protocolIds:
            return report

        runtimeMapper = self.getPostgresqlRuntimeMapper()

        if runtimeMapper is not None:
            runtimeMapper.evictRuntimeProtocols(
                protocolIds
            )

        sqlitePath = self._normalizeSqlitePath(PROJECT_DBNAME)

        if not sqlitePath or not os.path.exists(sqlitePath):
            report["missingDatabase"] = True
            return report

        sqliteMapper = None

        try:
            sqliteMapper = ScipionProject.createMapper(
                self,
                sqlitePath,
            )

            for protocolId in protocolIds:
                mirroredProtocol = sqliteMapper.selectById(
                    protocolId
                )

                if mirroredProtocol is None:
                    report["missingProtocolIds"].append(
                        protocolId
                    )
                    continue

                sqliteMapper.delete(
                    mirroredProtocol
                )

                report["deletedProtocolIds"].append(
                    protocolId
                )

            sqliteMapper.commit()

        except Exception as error:
            logger.warning(
                "Could not clean deleted protocols from SQLite execution mirror. "
                "projectId=%s protocolIds=%s error=%s",
                self.postgresqlProjectId,
                protocolIds,
                error,
                exc_info=True,
            )

            report["errors"].append(
                str(error)
            )

        finally:
            if sqliteMapper is not None:
                try:
                    sqliteMapper.close()
                except Exception:
                    logger.debug(
                        "Could not close SQLite execution cleanup mapper.",
                        exc_info=True,
                    )

        return report

    def _resolveProtocolRuntimeDbPath(
            self,
            protocol,
    ) -> str:
        runDbPath = getattr(
            protocol,
            "getDbPath",
            lambda: None,
        )()

        if runDbPath and os.path.isabs(
                str(runDbPath)
        ):
            return os.path.abspath(
                str(runDbPath)
            )

        workingDir = getattr(
            protocol,
            "getWorkingDir",
            lambda: None,
        )()

        if workingDir:
            workingDir = str(
                workingDir
            )

            if not os.path.isabs(
                    workingDir
            ):
                workingDir = os.path.join(
                    self.path,
                    workingDir,
                )

            return os.path.abspath(
                os.path.join(
                    workingDir,
                    "logs",
                    os.path.basename(
                        str(
                            runDbPath
                            or "run.db"
                        )
                    ),
                )
            )

        return os.path.abspath(
            os.path.join(
                self.path,
                str(
                    runDbPath
                    or ""
                ),
            )
        )

    def _storeProtocol(self, protocol):
        """
        Store protocol through the PostgreSQL runtime mapper and make sure the
        Scipion filesystem layout exists.

        Scipion's Project._setupProtocol stores first to allocate an id, then
        assigns the workingDir and stores again. By hooking here, the first
        store does nothing filesystem-related, and the second store creates the
        logical run folder once workingDir is available.
        """
        super()._storeProtocol(protocol)
        self._ensureProtocolFilesystem(protocol)

    # ---------------------------------------------------
    #               HELPERS
    # --------------------------------------------------

    def _ensureProtocolFilesystem(self, protocol) -> None:
        """
        Ensure Scipion's logical protocol folder exists.

        PostgreSQL can persist the protocol row, but protocol execution and
        outputs still need the filesystem layout:
            Runs/000123_ProtClass/
            Runs/000123_ProtClass/extra/
            Runs/000123_ProtClass/logs/
            Runs/000123_ProtClass/tmp or scratch
        """
        workingDir = self._getProtocolWorkingDir(protocol)
        if not workingDir:
            return

        logsDir = self._getProtocolSubPath(protocol, "_getLogsPath", "logs")
        extraDir = self._getProtocolSubPath(protocol, "_getExtraPath", "extra")

        if (
                os.path.isdir(workingDir)
                and os.path.isdir(logsDir)
                and os.path.isdir(extraDir)
        ):
            return

        makeWorkingDir = getattr(protocol, "makeWorkingDir", None)
        if not callable(makeWorkingDir):
            raise RuntimeError(
                "Cannot create Scipion protocol filesystem layout: "
                "protocol does not provide makeWorkingDir(). "
                "protocolId=%s protocolClass=%s workingDir=%s"
                % (
                    getattr(protocol, "getObjId", lambda: None)(),
                    getattr(protocol, "getClassName", lambda: protocol.__class__.__name__)(),
                    workingDir,
                )
            )

        try:
            makeWorkingDir()
        except Exception as exc:
            raise RuntimeError(
                "Could not create Scipion protocol filesystem layout. "
                "protocolId=%s protocolClass=%s workingDir=%s"
                % (
                    getattr(protocol, "getObjId", lambda: None)(),
                    getattr(protocol, "getClassName", lambda: protocol.__class__.__name__)(),
                    workingDir,
                )
            ) from exc

        logger.info(
            "Created Scipion protocol filesystem layout. protocolId=%s workingDir=%s",
            getattr(protocol, "getObjId", lambda: None)(),
            workingDir,
        )

    def _getProtocolWorkingDir(self, protocol) -> Optional[str]:
        getWorkingDir = getattr(protocol, "getWorkingDir", None)
        if callable(getWorkingDir):
            try:
                value = getWorkingDir()
                if value:
                    return str(value)
            except Exception:
                pass

        workingDir = getattr(protocol, "workingDir", None)
        getter = getattr(workingDir, "get", None)
        if callable(getter):
            try:
                value = getter()
                if value:
                    return str(value)
            except Exception:
                pass

        return None

    def _getProtocolSubPath(self, protocol, methodName: str, fallbackName: str) -> str:
        method = getattr(protocol, methodName, None)
        if callable(method):
            try:
                value = method()
                if value:
                    return str(value)
            except Exception:
                pass

        workingDir = self._getProtocolWorkingDir(protocol)
        if not workingDir:
            return fallbackName

        return os.path.join(workingDir, fallbackName)