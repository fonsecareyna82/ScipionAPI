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
from typing import Any, Dict, List

from fastapi import HTTPException, status
from pyworkflow.protocol.params import (
    MultiPointerParam,
    PointerParam,
    RelationParam,
)

from app.backend.runtime.protocol_graph_repository import (
    ProtocolGraphRepository,
)
from app.utils.protocol_param import (
    castProtocolParamValue,
)


class ProtocolRelationService:
    """Resolve Scipion RelationParam candidates for the web form."""

    def __init__(
            self,
            currentProject=None,
            projectService=None,
    ):
        self.currentProject = currentProject
        self.projectService = projectService

    @staticmethod
    def _sanitizeFormValues(
            params: Dict[str, Any],
    ) -> Dict[str, Any]:
        cleaned = {}

        for key, value in (
                params
                or {}
        ).items():
            if value is None:
                continue

            if (
                    isinstance(value, str)
                    and not value.strip()
            ):
                continue

            cleaned[key] = value

        return cleaned

    def _buildRelationReadyProtocol(
            self,
            *,
            protocolClassName: str,
            formValues: Dict[str, Any],
            mapper,
            projectId: int,
    ):
        if self.currentProject is None:
            raise RuntimeError(
                "currentProject is required "
                "to resolve RelationParam candidates"
            )

        if self.projectService is None:
            raise RuntimeError(
                "projectService is required "
                "to resolve RelationParam candidates"
            )

        protClass = (
            self.currentProject
            .getDomain()
            .getProtocols()
            .get(
                str(
                    protocolClassName
                )
            )
        )

        if protClass is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "Protocol class "
                    f"'{protocolClassName}' "
                    "not found"
                ),
            )

        protocol = (
            self.currentProject
            .newProtocol(
                protClass
            )
        )

        self.currentProject._fixProtParamsConfiguration(
            protocol
        )

        params = (
            self
            ._sanitizeFormValues(
                formValues
            )
        )

        errors = []

        for key, value in params.items():
            param = protocol.getParam(
                key
            )

            if param is None:
                continue

            if isinstance(
                    param,
                    (
                        PointerParam,
                        MultiPointerParam,
                        RelationParam,
                    ),
            ):
                continue

            try:
                castedValue = (
                    castProtocolParamValue(
                        param,
                        value,
                    )
                )

                validationErrors = (
                    param.validate(
                        castedValue
                    )
                    if hasattr(
                        param,
                        "validate",
                    )
                    else []
                )

                if validationErrors:
                    errors.extend(
                        [
                            "**"
                            + param.label.get()
                            + "** "
                            + error
                            for error
                            in validationErrors
                        ]
                    )

                param.set(
                    castedValue
                )

                protocol.setAttributeValue(
                    key,
                    castedValue,
                )

            except Exception as error:
                errors.append(
                    "**"
                    + param.label.get()
                    + "** "
                    + str(error)
                )

        errors.extend(
            self.projectService
            .applyParamsToProtocol(
                mapper=mapper,
                projectId=projectId,
                protocol=protocol,
                params=params,
            )
        )

        if errors:
            raise HTTPException(
                status_code=(
                    status.HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail=errors,
            )

        return protocol

    @staticmethod
    def _toOptionalInt(
            value,
    ):
        if value in (
                None,
                "",
        ):
            return None

        try:
            return int(
                value
            )
        except Exception:
            return None

    @staticmethod
    def _normalizeOutputName(
            value,
    ) -> str:
        value = str(
            value
            or ""
        ).strip()

        if not value:
            return ""

        return value.split(
            ".",
            1,
        )[0]

    def _serializeRelatedPointer(
            self,
            *,
            pointer,
            mapper,
            projectId: int,
    ):
        if pointer is None:
            return None

        try:
            pointedObject = (
                pointer.getObjValue()
            )
        except Exception:
            pointedObject = None

        if pointedObject is None:
            return None

        try:
            runtimeObjectId = (
                pointedObject.getObjId()
            )
        except Exception:
            runtimeObjectId = None

        runtimeObjectId = (
            self._toOptionalInt(
                runtimeObjectId
            )
        )

        try:
            extended = (
                pointer.getExtended()
                or ""
            )
        except Exception:
            extended = ""

        outputName = (
            self._normalizeOutputName(
                extended
            )
        )

        # Relations may use:
        #
        #     protocolId + extended output
        #
        # instead of pointing directly to the
        # persisted output object.
        if (
                runtimeObjectId is not None
                and outputName
        ):
            protocolRow = (
                mapper
                .getProjectProtocolByProtocolId(
                    projectId=projectId,
                    protocolId=runtimeObjectId,
                )
            )

            if protocolRow:
                return (
                    f"{runtimeObjectId}."
                    f"{outputName}"
                )

        if runtimeObjectId is None:
            return None

        persistedObject = (
            ProtocolGraphRepository()
            .getPersistedOutputObjectByRuntimeId(
                mapper=mapper,
                projectId=projectId,
                runtimeObjectId=runtimeObjectId,
                extended=extended,
            )
        )

        if not persistedObject:
            return None

        producerProtocolId = (
            self._toOptionalInt(
                persistedObject.get(
                    "protocolId"
                )
            )
        )

        persistedOutputName = (
            self._normalizeOutputName(
                persistedObject.get(
                    "outputName"
                )
            )
        )

        if (
                producerProtocolId is None
                or not persistedOutputName
        ):
            return None

        return (
            f"{producerProtocolId}."
            f"{persistedOutputName}"
        )

    def resolveRelationCandidates(
            self,
            *,
            mapper,
            projectId: int,
            currentUser: dict,
            protocolClassName: str,
            paramName: str,
            formValues: Dict[str, Any],
    ) -> Dict[str, Any]:
        projectRow = (
            self.projectService
            .loadPostgresqlRuntimeProjectForMutation(
                mapper=mapper,
                projectId=projectId,
                currentUser=currentUser,
            )
        )

        if not projectRow:
            raise HTTPException(
                status_code=(
                    status.HTTP_404_NOT_FOUND
                ),
                detail="Project not found",
            )

        self.currentProject = (
            self.projectService
            .currentProject
        )

        protocol = (
            self
            ._buildRelationReadyProtocol(
                protocolClassName=(
                    protocolClassName
                ),
                formValues=(
                    formValues
                ),
                mapper=mapper,
                projectId=projectId,
            )
        )

        relationParam = (
            protocol.getParam(
                paramName
            )
        )

        if not isinstance(
                relationParam,
                RelationParam,
        ):
            raise HTTPException(
                status_code=(
                    status.HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail=(
                    f"Parameter '{paramName}' "
                    "is not a RelationParam"
                ),
            )

        relationName = str(
            relationParam.getName()
            or ""
        ).strip()

        attributeName = str(
            relationParam.getAttributeName()
            or ""
        ).strip()

        if not relationName:
            raise HTTPException(
                status_code=(
                    status.HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail=(
                    f"RelationParam '{paramName}' "
                    "has no relationName"
                ),
            )

        if not attributeName:
            raise HTTPException(
                status_code=(
                    status.HTTP_422_UNPROCESSABLE_ENTITY
                ),
                detail=(
                    f"RelationParam '{paramName}' "
                    "has no attributeName"
                ),
            )

        sourceObject = (
            protocol.getAttributeValue(
                attributeName
            )
        )

        if sourceObject is None:
            return {
                "paramName": paramName,
                "relationName": relationName,
                "values": [],
            }

        relatedPointers = (
            self.currentProject
            .getRelatedObjects(
                relationName,
                sourceObject,
                relationParam.getDirection(),
            )
            or []
        )

        values: List[str] = []
        seen = set()

        for pointer in relatedPointers:
            value = (
                self
                ._serializeRelatedPointer(
                    pointer=pointer,
                    mapper=mapper,
                    projectId=projectId,
                )
            )

            if (
                    not value
                    or value in seen
            ):
                continue

            seen.add(
                value
            )

            values.append(
                value
            )

        return {
            "paramName": paramName,
            "relationName": relationName,
            "values": values,
        }
