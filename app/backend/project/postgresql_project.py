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
from typing import Optional

from pyworkflow import PROJECT_DBNAME
from pyworkflow.project import Project as ScipionProject

from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.mapper.postgresql_runtime_mapper import PostgresqlRuntimeMapper

logger = logging.getLogger(__name__)


class PostgresqlProject(ScipionProject):
    """
    PostgreSQL-aware Scipion Project.

    This class keeps the normal Scipion Project lifecycle, paths, settings,
    hosts and protocol setup logic, but replaces Project.mapper with a
    PostgresqlRuntimeMapper.

    During the migration phase, reads can still fallback to the legacy
    SqliteMapper. Writes go to PostgreSQL.
    """

    def __init__(
            self,
            domain,
            path: str,
            projectId: int,
            flatMapper: PostgresqlFlatMapper,
            enableReadFallback: bool = True,
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

        writeFallbackMapper = readFallbackMapper if self.enableWriteFallback else None

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