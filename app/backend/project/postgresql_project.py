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
import json
import logging
import os
from typing import Any, Dict, Optional

from pyworkflow import PROJECT_DBNAME
from pyworkflow.project import Project as ScipionProject
from pyworkflow.project.project import REGEX_NUMBER_ENDING
from pyworkflow.protocol.constants import (
    STATUS_SAVED,
    STATUS_SCHEDULED,
)
from pyworkflow.protocol.protocol import Protocol

from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.mapper.postgresql_runtime_mapper import PostgresqlRuntimeMapper

logger = logging.getLogger(__name__)


class PostgresqlProject(ScipionProject):
    """
    PostgreSQL-aware Scipion Project.

    This class keeps the normal Scipion Project lifecycle, paths, settings,
    hosts and protocol setup logic, but replaces Project.mapper with a
    PostgresqlRuntimeMapper.

    Reads are PostgreSQL-only by default.

    A legacy SqliteMapper fallback can still be enabled explicitly while
    diagnosing incomplete PostgreSQL mapper operations. Runtime execution
    databases remain independent from this project-level read fallback.
    """

    def __init__(
            self,
            domain,
            path: str,
            projectId: int,
            flatMapper: PostgresqlFlatMapper,
            enableReadFallback: bool = False,
            enableWriteFallback: bool = False,
    ):
        super().__init__(domain, path)

        if projectId is None:
            raise ValueError("projectId is required")
        if flatMapper is None:
            raise ValueError("flatMapper is required")

        self.postgresqlProjectId = int(projectId)
        self.postgresqlFlatMapper = flatMapper

        self.enableReadFallback = bool(enableReadFallback)
        self.enableWriteFallback = bool(enableWriteFallback)

        self._postgresqlRuntimeMapper: Optional[PostgresqlRuntimeMapper] = None
        self._readFallbackMapper = None
        self._writeFallbackMapper = None

    def createMapper(self, sqliteFn):
        """
        Return the mapper used by Project.

        Scipion Project._loadDb() calls this method and assigns the result to
        self.mapper. By overriding it, all Project/Protocol calls that delegate
        to self.mapper can go to PostgreSQL.
        """
        sqlitePath = self._normalizeSqlitePath(sqliteFn)
        # Scipion still executes protocols from their own logs/run.db.
        # Only the project mapper is replaced by PostgreSQL. Protocol run
        # databases must remain regular SQLite databases because
        # runProtocolMain() loads them with the standard Project class.
        if sqlitePath and os.path.basename(sqlitePath) != PROJECT_DBNAME:
            logger.info(
                "Creating legacy SQLite mapper for protocol runtime db: %s",
                sqlitePath,
            )
            return ScipionProject.createMapper(self, sqlitePath)

        readFallbackMapper = self._createFallbackMapper(
            sqlitePath=sqlitePath,
            enabled=self.enableReadFallback,
            label="read",
        )

        # Read and write compatibility are independent.
        #
        # Disabling the project.sqlite read fallback must not disable the
        # temporary SQLite write mirror required by Scipion's native runner.
        #
        # When reads are enabled, reuse the same mapper to avoid opening two
        # SQLite connections to project.sqlite.
        writeFallbackMapper = None

        if self.enableWriteFallback:
            if readFallbackMapper is not None:
                writeFallbackMapper = readFallbackMapper
            else:
                writeFallbackMapper = self._createFallbackMapper(
                    sqlitePath=sqlitePath,
                    enabled=True,
                    label="write",
                )

        self._readFallbackMapper = readFallbackMapper
        self._writeFallbackMapper = writeFallbackMapper

        runtimeMapper = PostgresqlRuntimeMapper(
            flatMapper=self.postgresqlFlatMapper,
            projectId=self.postgresqlProjectId,
            readFallbackMapper=readFallbackMapper,
            writeFallbackMapper=writeFallbackMapper,
            project=self,
        )
        self._postgresqlRuntimeMapper = runtimeMapper
        return runtimeMapper

    def getPostgresqlRuntimeMapper(self) -> Optional[PostgresqlRuntimeMapper]:
        return self._postgresqlRuntimeMapper

    def usingPostgresqlRuntimeMapper(self) -> bool:
        return isinstance(self.mapper, PostgresqlRuntimeMapper)

    def _normalizeSqlitePath(self, sqliteFn) -> Optional[str]:
        if not sqliteFn:
            return None

        sqlitePath = str(sqliteFn)

        if os.path.isabs(sqlitePath):
            return sqlitePath

        return os.path.abspath(os.path.join(self.path, sqlitePath))

    def _createFallbackMapper(self, sqlitePath: Optional[str], enabled: bool, label: str):
        if not enabled:
            return None

        if not sqlitePath:
            logger.debug(
                "PostgreSQL Project %s fallback mapper disabled: empty sqlite path.",
                label,
            )
            return None

        if not os.path.exists(sqlitePath):
            logger.warning(
                "PostgreSQL Project %s fallback mapper disabled: sqlite db does not exist: %s",
                label,
                sqlitePath,
            )
            return None

        try:
            # Call the original Scipion implementation directly. Do not call
            # self.createMapper(), because that would recurse into this method.
            return ScipionProject.createMapper(self, sqlitePath)
        except Exception:
            logger.exception(
                "Could not create %s fallback mapper for sqlite db: %s",
                label,
                sqlitePath,
            )
            raise

    def closeMapper(self):
        """
            Close runtime mapper and fallback mappers.

            PostgresqlRuntimeMapper.close() already closes readFallbackMapper.
            This method is defensive and avoids leaking sqlite connections during
            tests or repeated project loads.
            """
        runtimeMapper = self._postgresqlRuntimeMapper
        readFallbackMapper = self._readFallbackMapper
        writeFallbackMapper = self._writeFallbackMapper

        try:
            if runtimeMapper is not None:
                runtimeMapper.close()

            if writeFallbackMapper is not None and writeFallbackMapper is not readFallbackMapper:
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
            self._readFallbackMapper = None
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

        if writeFallbackMapper is None:
            raise RuntimeError(
                "Cannot stop PostgreSQL runtime protocol: "
                "SQLite write fallback mapper is not available"
            )

        protocolId = getattr(
            protocol,
            "getObjId",
            lambda: None,
        )()

        if protocolId in (None, ""):
            raise RuntimeError(
                "Cannot stop PostgreSQL runtime protocol without protocol id"
            )

        sqliteProtocol = writeFallbackMapper.selectById(
            int(protocolId)
        )

        if sqliteProtocol is None:
            raise RuntimeError(
                "Protocol %s was not found in the SQLite compatibility database"
                % protocolId
            )

        originalMapper = self.mapper

        try:
            logger.info(
                "Stopping PostgreSQL runtime protocol through SQLite "
                "compatibility mapper. projectId=%s protocolId=%s",
                self.postgresqlProjectId,
                protocolId,
            )

            # Project._updateProtocol() uses self.mapper directly.
            # It must temporarily see the classic project.sqlite mapper.
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
            # Restore PostgreSQL as the authoritative project mapper even if
            # Scipion's native stop operation raises an exception.
            self.mapper = originalMapper

    def refreshProtocolFromRuntimeDbForResume(
            self,
            protocolId: int,
    ) -> Dict[str, Any]:
        """
        Refresh a previously launched protocol from its run.db before resume.

        For a first launch there is no run.db yet. In that case this method must
        not materialize the SQLite execution mirror. The mirror will be created
        later by RuntimeProtocolLaunchService, after launch parameters and input
        pointers have been fully restored.
        """
        protocolId = int(protocolId)

        if not self.usingPostgresqlRuntimeMapper():
            return {
                "protocolId": protocolId,
                "refreshed": False,
                "reason": "legacy_project",
            }

        runtimeMapper = self.getPostgresqlRuntimeMapper()

        if runtimeMapper is None:
            raise RuntimeError(
                "Cannot refresh protocol runtime state: "
                "PostgreSQL runtime mapper is not available."
            )

        writeFallbackMapper = getattr(
            runtimeMapper,
            "writeFallbackMapper",
            None,
        )

        if writeFallbackMapper is None:
            raise RuntimeError(
                "Cannot refresh protocol runtime state: "
                "SQLite write fallback mapper is not available."
            )

        # Resolve the authoritative PostgreSQL protocol first.
        #
        # Do not create the SQLite mirror yet: at this point input pointers may
        # still contain their serialized PostgreSQL representation.
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

        # First launch:
        # no run.db exists, so there is nothing to refresh.
        #
        # Most importantly, do not call
        # ensureProtocolWriteFallbackMirror() here. The launch service will call
        # it later after saveProtocolCallback() and pointer preparation.
        if not os.path.exists(runDbPath):
            logger.info(
                "Skipping runtime DB refresh for first protocol launch. "
                "SQLite execution mirror will be created after pointer "
                "preparation. projectId=%s protocolId=%s runDbPath=%s",
                self.postgresqlProjectId,
                protocolId,
                runDbPath,
            )

            return {
                "protocolId": protocolId,
                "refreshed": False,
                "reason": "runtime_db_not_found",
                "runDbPath": runDbPath,
                "sqliteMirrorDeferred": True,
            }

        # From here onward this is a real resume. A protocol with a run.db should
        # normally already have its persistent SQLite execution mirror.
        sqliteProtocol = writeFallbackMapper.selectById(
            protocolId
        )

        if sqliteProtocol is None:
            # Compatibility fallback for a missing execution mirror.
            ensureMirror = getattr(
                runtimeMapper,
                "ensureProtocolWriteFallbackMirror",
                None,
            )

            if not callable(ensureMirror):
                raise RuntimeError(
                    "Protocol %s has a run.db but its SQLite execution "
                    "mirror is missing."
                    % protocolId
                )

            mirrorReport = ensureMirror(
                postgresqlProtocol
            )

            writeFallbackMapper.commit()

            clearCaches = getattr(
                runtimeMapper,
                "_clearFallbackMapperCaches",
                None,
            )

            if callable(clearCaches):
                clearCaches(
                    writeFallbackMapper
                )

            sqliteProtocol = writeFallbackMapper.selectById(
                protocolId
            )

            logger.info(
                "Materialized missing SQLite execution mirror before resume. "
                "projectId=%s protocolId=%s report=%s",
                self.postgresqlProjectId,
                protocolId,
                mirrorReport,
            )

        if sqliteProtocol is None:
            raise RuntimeError(
                "Protocol %s was not found in the SQLite execution "
                "mirror after materialization."
                % protocolId
            )

        if not isinstance(
                sqliteProtocol,
                Protocol,
        ):
            raise RuntimeError(
                "Invalid SQLite execution mirror for protocol %s: "
                "expected Protocol, found %s."
                % (
                    protocolId,
                    sqliteProtocol.__class__.__name__,
                )
            )

        originalMapper = self.mapper
        updateResult = None

        try:
            # Native Scipion refresh must operate through the SQLite execution
            # mapper because run.db and steps.sqlite belong to that runtime.
            self.mapper = writeFallbackMapper

            sqliteProtocol.setMapper(
                writeFallbackMapper
            )

            sqliteProtocol.setProject(
                self
            )

            updateResult = ScipionProject._updateProtocol(
                self,
                sqliteProtocol,
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

        # For a real resume, use the fully hydrated SQLite protocol, which
        # contains the native runtime/step state recovered from run.db.
        runtimeMapper._runtimeProtocolsById[
            protocolId
        ] = sqliteProtocol

        runtimeMapper._sqliteProtocolMirrorIds.add(
            protocolId
        )

        logger.info(
            "Refreshed PostgreSQL runtime protocol from run.db "
            "before resume. projectId=%s protocolId=%s "
            "runDbPath=%s updateResult=%s",
            self.postgresqlProjectId,
            protocolId,
            runDbPath,
            updateResult,
        )

        return {
            "protocolId": protocolId,
            "refreshed": True,
            "runDbPath": runDbPath,
            "updateResult": updateResult,
        }

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