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
from typing import Any, Dict, Optional

from pyworkflow.protocol.params import (
    MultiPointerParam,
    PointerParam,
    RelationParam,
)

from app.backend.runtime.pointer_resolver import RuntimePointerResolver
from app.backend.runtime.protocol_graph_repository import ProtocolGraphRepository
from app.backend.runtime.protocol_identity import ProtocolIdentityResolver

logger = logging.getLogger(__name__)


class RuntimeProtocolInputSyncService:
    """Synchronize PostgreSQL runtime input refs and dependency edges."""

    @staticmethod
    def _getScipionObjectId(obj) -> Optional[int]:
        if obj is None:
            return None

        for methodName in ("getObjId", "getId"):
            method = getattr(obj, methodName, None)

            if method is None:
                continue

            try:
                value = method()
            except Exception:
                continue

            if value not in (None, ""):
                try:
                    return int(value)
                except Exception:
                    return None

        for attrName in ("objId", "_objId", "id"):
            value = getattr(obj, attrName, None)

            if value not in (None, ""):
                try:
                    return int(value)
                except Exception:
                    return None

        return None

    @staticmethod
    def _emptySyncReport(
            protocolId=None,
            protocolDbId=None,
            reason: str = "",
    ) -> Dict[str, Any]:
        return {
            "protocolId": str(protocolId) if protocolId is not None else None,
            "protocolDbId": protocolDbId,
            "parents": [],
            "parentProtocolIds": [],
            "inputRefs": [],
            "detectedPointerParams": [],
            "dependencies": 0,
            "inputRefsSaved": 0,
            "skipped": True,
            "reason": reason,
        }

    def syncProtocolInputsAndDependencies(
            self,
            mapper,
            projectId: int,
            protocol,
            params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Sync input refs and dependency edges for one PostgreSQL-runtime protocol.

        Dependency edges are resolved from raw params, not only from Scipion
        Pointer objects. The workflow graph loaded from PostgreSQL uses
        protocol_dependencies.
        """
        protocolIdentityResolver = ProtocolIdentityResolver(
            mapper=mapper,
            projectId=projectId,
        )

        protocolId = protocolIdentityResolver.resolveScipionProtocolId(
            self._getScipionObjectId(protocol),
        )

        if protocolId is None:
            return self._emptySyncReport(
                reason="protocol_without_id",
            )

        protocolDbId = protocolIdentityResolver.resolvePostgresqlProtocolDbId(
            protocolId,
        )

        if protocolDbId is None:
            return self._emptySyncReport(
                protocolId=protocolId,
                reason="protocol_not_found",
            )

        rawParams = params or {}

        pointerResolver = RuntimePointerResolver()

        params = pointerResolver.mergePointerParamsWithProtocolState(
            protocol=protocol,
            params=rawParams,
        )

        logger.debug(
            "Runtime dependency sync merged pointer params. projectId=%s protocolId=%s "
            "rawParams=%s mergedParams=%s",
            projectId,
            protocolId,
            rawParams,
            params,
        )

        pointerSyncData = pointerResolver.buildInputRefsFromPointerParams(
            mapper=mapper,
            projectId=projectId,
            protocolDbId=int(protocolDbId),
            protocolId=protocolId,
            params=params,
            getParamCallback=protocol.getParam,
            isPointerParamCallback=lambda param: isinstance(
                param,
                (PointerParam, MultiPointerParam, RelationParam),
            ),
        )

        parentProtocolDbIds = pointerSyncData.get("parentProtocolDbIds") or []
        parentProtocolIds = pointerSyncData.get("parentProtocolIds") or []
        inputRefs = pointerSyncData.get("inputRefs") or []
        detectedPointerParams = pointerSyncData.get("detectedPointerParams") or []

        protocolGraphRepository = ProtocolGraphRepository()

        inputGraphSync = protocolGraphRepository.replaceInputGraphForProtocol(
            mapper=mapper,
            projectId=projectId,
            protocolDbId=int(protocolDbId),
            parentProtocolDbIds=parentProtocolDbIds,
            parentProtocolIds=parentProtocolIds,
            inputRefs=inputRefs,
        )

        dependenciesSaved = inputGraphSync.get("dependencies", 0)
        inputRefsSaved = inputGraphSync.get("inputRefsSaved", 0)

        return {
            "protocolId": str(protocolId),
            "protocolDbId": int(protocolDbId),
            "parents": parentProtocolDbIds,
            "parentProtocolIds": parentProtocolIds,
            "inputRefs": inputRefs,
            "detectedPointerParams": detectedPointerParams,
            "dependencies": dependenciesSaved,
            "inputRefsSaved": inputRefsSaved,
            "skipped": False,
        }