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

from typing import Any, Dict


class RuntimeOutputProxyService:
    """Build PostgreSQL-backed output proxies without mutating protocols."""

    def attachPostgresqlRuntimeOutputProxy(
            self,
            parentProtocol,
            outputName: str,
            outputInfo: Dict[str, Any],
            mapper=None,
    ):
        """
        Build and return a PostgreSQL-backed proxy for a persisted output.

        The owner protocol is strictly read-only. The proxy may keep a reference
        to that protocol, but this method never attaches, replaces or removes
        any output attribute.
        """
        db = getattr(mapper, "db", None)

        if db is None:
            raise ValueError(
                "PostgreSQL mapper/db is required to attach runtime output proxy"
            )

        if outputInfo.get("setId") is not None:
            factory = self._getRuntimeSetFactory(mapper)
            proxy = self._getCachedRuntimeSet(factory, mapper, outputInfo)

            if proxy is None:
                proxy = factory.build(
                    db=db,
                    parent=parentProtocol,
                    outputName=outputName,
                    outputInfo=outputInfo,
                    classes=getattr(mapper, "dictClasses", None),
                )
        else:
            from app.backend.utils.postgresql_runtime_output_adapter import (
                PostgresqlRuntimeOutputProxy,
            )

            proxy = PostgresqlRuntimeOutputProxy(
                db=db,
                parent=parentProtocol,
                outputName=outputName,
                outputInfo=outputInfo,
            )

        return proxy

    @staticmethod
    def _getRuntimeSetFactory(mapper):
        factory = getattr(mapper, "runtimeSetFactory", None)

        if callable(getattr(factory, "build", None)):
            return factory

        from app.backend.runtime.postgresql_runtime_set_factory import (
            PostgresqlRuntimeSetFactory,
        )

        return PostgresqlRuntimeSetFactory()

    @staticmethod
    def _getCachedRuntimeSet(factory, mapper, outputInfo):
        getCachedSet = getattr(factory, "_getCachedRuntimeSet", None)

        if not callable(getCachedSet):
            return None

        projectId = outputInfo.get("projectId")

        if projectId in (None, ""):
            projectId = getattr(mapper, "projectId", None)

        runtimeObjectId = outputInfo.get("runtimeObjectId")

        if projectId in (None, "") or runtimeObjectId in (None, ""):
            return None

        try:
            projectId = int(projectId)
            runtimeObjectId = int(runtimeObjectId)
        except (TypeError, ValueError):
            return None

        return getCachedSet(
            projectId=projectId,
            runtimeObjectId=runtimeObjectId,
        )