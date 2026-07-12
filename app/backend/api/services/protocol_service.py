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
# * All comments concerning this program package may be sent to the
# * e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************
from typing import Any, Callable, Dict


class ProtocolService:
    """Orchestrate protocol retrieval and context operations."""

    def getProtocolParams(
            self,
            *,
            mapper,
            projectId: int,
            protocolId: int,
            usingPostgresqlRuntime: bool,
            syncPostgresqlRuntimeProtocolCallback: Callable,
            getScipionProtocolForRuntimeCallback: Callable,
            fixProtocolParamsConfigurationCallback: Callable,
            buildProtocolContextCallback: Callable,
    ) -> Dict[str, Any]:
        """
        Return the web context of an existing protocol.

        PostgreSQL-runtime protocols reuse the context built from the real
        run.db protocol, preserving runtime outputs and avoiding a second
        protocol reconstruction.
        """
        if usingPostgresqlRuntime:
            syncResult = syncPostgresqlRuntimeProtocolCallback(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
                registerOutputs=False,
                returnProtocolContext=True,
            )

            return syncResult["protocolContext"]

        protocol = getScipionProtocolForRuntimeCallback(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        protocol.getPlugin()
        fixProtocolParamsConfigurationCallback(protocol)

        return buildProtocolContextCallback(
            projectId,
            protocol,
            mapper,
        )