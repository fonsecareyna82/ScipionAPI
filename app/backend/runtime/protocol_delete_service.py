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

from typing import Any, Dict, List, Optional
from fastapi import HTTPException, status

from pyworkflow.protocol import (
    STATUS_LAUNCHED,
    STATUS_RUNNING,
    STATUS_SCHEDULED,
)

from app.backend.runtime.protocol_graph_repository import ProtocolGraphRepository
from app.backend.runtime.protocol_identity import ProtocolIdentityResolver


class RuntimeProtocolDeleteService:
    """PostgreSQL runtime protocol delete orchestration."""

    @staticmethod
    def getRuntimeBlockedStatusTexts() -> set:
        blockedStatuses = {
            STATUS_RUNNING,
            STATUS_LAUNCHED,
            STATUS_SCHEDULED,
        }

        return {
            str(statusValue).strip().lower()
            for statusValue in blockedStatuses
        }

    def buildBlockedProtocolReports(
        self,
        mapper,
        projectId: int,
        protocols: List[Any],
        protocolGraphRepository: Optional[ProtocolGraphRepository] = None,
    ) -> List[Dict[str, str]]:
        blockedStatusTexts = self.getRuntimeBlockedStatusTexts()
        blockedProtocols = []

        for protocol in protocols or []:
            protocolId = getattr(protocol, "getObjId", lambda: None)()
            protocolStatus = None

            if protocolGraphRepository is not None:
                protocolStatus = protocolGraphRepository.getProtocolStatusByScipionProtocolId(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=protocolId,
                )

            if protocolStatus is None:
                try:
                    protocolStatus = protocol.getStatus()
                except Exception:
                    statusAttr = getattr(protocol, "status", None)

                    try:
                        protocolStatus = statusAttr.get() if statusAttr is not None else None
                    except Exception:
                        protocolStatus = None

            protocolStatusText = str(protocolStatus or "").strip().lower()

            if protocolStatusText in blockedStatusTexts:
                blockedProtocols.append({
                    "protocolId": str(protocolId),
                    "status": protocolStatusText,
                })

        return blockedProtocols

    def resolveProtocolDeleteIdentity(
        self,
        mapper,
        projectId: int,
        protocols: List[Any],
    ) -> Dict[str, Any]:
        protocolIdentityResolver = ProtocolIdentityResolver(
            mapper=mapper,
            projectId=projectId,
            db=mapper.db,
        )

        return protocolIdentityResolver.resolveProtocolDbIdsFromProtocols(
            protocols
        )

    def preparePostgresqlRuntimeProtocolDelete(
        self,
        mapper,
        projectId: int,
        protocols: List[Any],
        protocolGraphRepository: Optional[ProtocolGraphRepository] = None,
    ) -> Dict[str, Any]:
        protocolIdentityData = self.resolveProtocolDeleteIdentity(
            mapper=mapper,
            projectId=projectId,
            protocols=protocols,
        )

        selectedProtocolDbIds = protocolIdentityData.get("protocolDbIds") or []
        missingPostgresqlProtocols = protocolIdentityData.get("missingProtocolIds") or []
        selectedProtocolIds = protocolIdentityData.get("protocolIds") or []

        deleteValidationInfo = None

        if not missingPostgresqlProtocols:
            deleteValidationInfo = self.validatePostgresqlRuntimeProtocolDelete(
                mapper=mapper,
                projectId=projectId,
                selectedProtocolDbIds=selectedProtocolDbIds,
                protocolGraphRepository=protocolGraphRepository,
            )

        return {
            "protocolIdentityData": protocolIdentityData,
            "selectedProtocolDbIds": selectedProtocolDbIds,
            "missingPostgresqlProtocols": missingPostgresqlProtocols,
            "selectedProtocolIds": selectedProtocolIds,
            "deleteValidationInfo": deleteValidationInfo,
        }

    def validatePostgresqlRuntimeProtocolDelete(
        self,
        mapper,
        projectId: int,
        selectedProtocolDbIds: List[int],
        protocolGraphRepository: Optional[ProtocolGraphRepository] = None,
    ) -> Dict[str, Any]:
        """
        Validate PostgreSQL runtime delete constraints.

        A selected protocol can be deleted with its outputs if it is part of the
        selected deletion set. What is not allowed is deleting a protocol while
        leaving downstream protocols outside the selection that are active or
        already have outputs.

        protocolGraphRepository can be passed by callers that already created
        one for the current delete flow.
        """
        if not selectedProtocolDbIds:
            return {
                "blocked": False,
                "externalDescendants": [],
            }

        blockedStatusTexts = self.getRuntimeBlockedStatusTexts()

        if protocolGraphRepository is None:
            protocolGraphRepository = ProtocolGraphRepository()

        rows = protocolGraphRepository.loadExternalDescendantsForDeleteValidation(
            mapper=mapper,
            projectId=projectId,
            selectedProtocolDbIds=selectedProtocolDbIds,
        )

        blockedDescendants = []

        for row in rows or []:
            statusText = str(row.get("status") or "").strip().lower()
            setsCount = int(row.get("setsCount") or 0)
            objectsCount = int(row.get("objectsCount") or 0)

            isActive = statusText in blockedStatusTexts
            hasOutputs = setsCount > 0 or objectsCount > 0

            if not isActive and not hasOutputs:
                continue

            reasons = []

            if isActive:
                reasons.append("active")

            if hasOutputs:
                reasons.append("has_outputs")

            blockedDescendants.append({
                "protocolDbId": int(row.get("protocolDbId")),
                "protocolId": str(row.get("protocolId")),
                "status": statusText,
                "setsCount": setsCount,
                "objectsCount": objectsCount,
                "reasons": reasons,
            })

        return {
            "blocked": bool(blockedDescendants),
            "externalDescendants": blockedDescendants,
        }

    def deletePostgresqlRuntimeProtocols(
        self,
        mapper,
        projectId: int,
        protocols: List[Any],
        protocolDbIds: Optional[List[int]] = None,
        protocolIds: Optional[List[str]] = None,
        protocolGraphRepository: Optional[ProtocolGraphRepository] = None,
    ) -> Dict[str, Any]:
        """
        Delete PostgreSQL runtime protocol rows and refresh affected children.

        In the normal deleteProtocol flow, protocolDbIds and protocolIds are
        already resolved before this helper is called. The fallback resolution is
        kept for compatibility with direct/internal calls.
        """
        if protocolDbIds is None:
            protocolIdentityResolver = ProtocolIdentityResolver(
                mapper=mapper,
                projectId=projectId,
                db=mapper.db,
            )
            protocolIdentityData = protocolIdentityResolver.resolveProtocolDbIdsFromProtocols(
                protocols
            )

            protocolIds = protocolIdentityData.get("protocolIds") or []
            protocolDbIds = protocolIdentityData.get("protocolDbIds") or []
        else:
            protocolIds = (
                protocolIds
                or ProtocolIdentityResolver.extractProtocolIdsFromProtocols(protocols)
            )

        if not protocolDbIds:
            return {
                "deletedProtocolIds": protocolIds or [],
                "deletedProtocolDbIds": [],
                "affectedChildren": [],
                "parentsRefresh": {
                    "refreshed": [],
                    "count": 0,
                },
            }

        if protocolGraphRepository is None:
            protocolGraphRepository = ProtocolGraphRepository()

        deleteGraphInfo = protocolGraphRepository.deleteProtocolsAndRefreshChildren(
            mapper=mapper,
            projectId=projectId,
            protocolDbIds=protocolDbIds,
        )

        return {
            "deletedProtocolIds": protocolIds,
            "deletedProtocolDbIds": deleteGraphInfo.get("deletedProtocolDbIds") or [],
            "affectedChildren": deleteGraphInfo.get("affectedChildren") or [],
            "parentsRefresh": deleteGraphInfo.get("parentsRefresh") or {
                "refreshed": [],
                "count": 0,
            },
        }

    @staticmethod
    def buildPostgresqlRuntimeDeleteResult(
        deleteInfo: Dict[str, Any],
        deleteValidationInfo: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "status": 0,
            "message": "Protocol deleted successfully",
            "protocolsCount": len(deleteInfo.get("deletedProtocolDbIds", [])),
            "dependenciesCount": sum(
                int(item.get("dependenciesSaved", 0) or 0)
                for item in deleteInfo.get("parentsRefresh", {}).get("refreshed", [])
            ),
            "postgresqlRuntimeDelete": True,
            "deleteValidationInfo": deleteValidationInfo,
            "deleteInfo": deleteInfo,
        }

    def executePostgresqlRuntimeProtocolDelete(
        self,
        mapper,
        projectId: int,
        protocols: List[Any],
        protocolDbIds: Optional[List[int]] = None,
        protocolIds: Optional[List[str]] = None,
        protocolGraphRepository: Optional[ProtocolGraphRepository] = None,
        deleteValidationInfo: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        deleteInfo = self.deletePostgresqlRuntimeProtocols(
            mapper=mapper,
            projectId=projectId,
            protocols=protocols,
            protocolDbIds=protocolDbIds,
            protocolIds=protocolIds,
            protocolGraphRepository=protocolGraphRepository,
        )

        return self.buildPostgresqlRuntimeDeleteResult(
            deleteInfo=deleteInfo,
            deleteValidationInfo=deleteValidationInfo,
        )

    def deleteProtocols(
            self,
            *,
            mapper,
            projectId: int,
            protocols,
            usingPostgresqlRuntime: bool,
            getScipionProtocolForRuntimeCallback,
            currentProjectDeleteProtocolCallback,
            mapperDeleteProtocolCallback,
            syncProjectProtocolsAndDependenciesCallback,
    ):
        try:
            protList = []

            for protocolId in protocols or []:
                protocol = getScipionProtocolForRuntimeCallback(
                    mapper=mapper,
                    projectId=projectId,
                    protocolId=protocolId,
                )

                protList.append(protocol)

            if not protList:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="No valid protocols to delete",
                )

            protocolGraphRepository = (
                ProtocolGraphRepository()
                if usingPostgresqlRuntime
                else None
            )

            blockedProtocols = self.buildBlockedProtocolReports(
                mapper=mapper,
                projectId=projectId,
                protocols=protList,
                protocolGraphRepository=protocolGraphRepository,
            )

            if blockedProtocols:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "message": (
                            "Running, launched or scheduled protocols cannot be deleted. "
                            "Stop them first and delete them afterwards."
                        ),
                        "blockedProtocols": blockedProtocols,
                    },
                )

            deleteValidationInfo = None
            selectedProtocolDbIds = []
            selectedProtocolIds = []

            if usingPostgresqlRuntime:
                deletePreparationInfo = self.preparePostgresqlRuntimeProtocolDelete(
                    mapper=mapper,
                    projectId=projectId,
                    protocols=protList,
                    protocolGraphRepository=protocolGraphRepository,
                )

                selectedProtocolDbIds = deletePreparationInfo.get("selectedProtocolDbIds") or []
                missingPostgresqlProtocols = deletePreparationInfo.get("missingPostgresqlProtocols") or []
                selectedProtocolIds = deletePreparationInfo.get("selectedProtocolIds") or []
                deleteValidationInfo = deletePreparationInfo.get("deleteValidationInfo")

                if missingPostgresqlProtocols:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail={
                            "message": (
                                "Some selected protocols exist in the execution runtime but "
                                "were not found in PostgreSQL. Delete was aborted to avoid "
                                "leaving the runtime graph inconsistent."
                            ),
                            "protocolIds": missingPostgresqlProtocols,
                        },
                    )

                if deleteValidationInfo and deleteValidationInfo.get("blocked"):
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail={
                            "message": (
                                "The selected protocols cannot be deleted because there are "
                                "downstream protocols outside the selection that are active "
                                "or already have outputs. Select the full affected subworkflow "
                                "or stop/reset the downstream protocols first."
                            ),
                            "blockedDescendants": (
                                    deleteValidationInfo.get("externalDescendants") or []
                            ),
                        },
                    )

            currentProjectDeleteProtocolCallback(*protList)

            if usingPostgresqlRuntime:
                return self.executePostgresqlRuntimeProtocolDelete(
                    mapper=mapper,
                    projectId=projectId,
                    protocols=protList,
                    protocolDbIds=selectedProtocolDbIds,
                    protocolIds=selectedProtocolIds,
                    protocolGraphRepository=protocolGraphRepository,
                    deleteValidationInfo=deleteValidationInfo,
                )

            mapperDeleteProtocolCallback(projectId, protList)

            syncInfo = syncProjectProtocolsAndDependenciesCallback(
                mapper,
                projectId,
                refresh=True,
                checkPid=True,
            )

            return {
                "status": 0,
                "message": "Protocol deleted successfully",
                "protocolsCount": syncInfo.get("protocols"),
                "dependenciesCount": syncInfo.get("dependencies"),
            }

        except HTTPException:
            raise

        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))