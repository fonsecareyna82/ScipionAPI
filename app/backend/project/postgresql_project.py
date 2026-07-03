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

        readFallbackMapper = self._createFallbackMapper(
            sqlitePath=sqlitePath,
            enabled=self.enableReadFallback,
            label="read",
        )

        writeFallbackMapper = self._createFallbackMapper(
            sqlitePath=sqlitePath,
            enabled=self.enableWriteFallback,
            label="write",
        )

        self._readFallbackMapper = readFallbackMapper
        self._writeFallbackMapper = writeFallbackMapper

        runtimeMapper = PostgresqlRuntimeMapper(
            flatMapper=self.postgresqlFlatMapper,
            projectId=self.postgresqlProjectId,
            readFallbackMapper=readFallbackMapper,
            writeFallbackMapper=writeFallbackMapper,
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

        try:
            if runtimeMapper is not None:
                runtimeMapper.close()
        finally:
            self.mapper = None
            self._postgresqlRuntimeMapper = None
            self._readFallbackMapper = None
            self._writeFallbackMapper = None