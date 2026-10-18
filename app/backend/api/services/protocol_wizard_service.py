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

from __future__ import annotations

import copy
import logging
import re
from typing import Any, Dict, List, Optional

import pyworkflow
from fastapi import HTTPException, status
from pyworkflow.protocol.params import MultiPointerParam, PointerParam, RelationParam

from app.backend.runtime.protocol_save_service import RuntimeProtocolSaveService
from app.utils.protocol_param import castProtocolParamValue

logger = logging.getLogger(__name__)


def findProtocolWizardsWeb(currentProject, protocol) -> Dict[str, List[Dict[str, Any]]]:
    service = ProtocolWizardService(
        currentProject=currentProject,
        projectService=None,
    )
    return service.findWizardsWeb(protocol)


class ProtocolWizardService:
    def __init__(self, currentProject=None, projectService=None):
        self.currentProject = currentProject
        self.projectService = projectService

    def findWizardsWeb(self, protocol) -> Dict[str, List[Dict[str, Any]]]:
        """The wizard of each param, exactly as the desktop form finds it.

        The web runs the wizard's own show() (protocol_wizard_runtime), so any
        wizard the desktop offers is offered on the web too.
        """
        from app.backend.api.services.protocol_wizard_runtime_worker import (
            desktopWizards, wizardIdentity)

        domain = self.currentProject.getDomain() if self.currentProject else pyworkflow.Config.getDomain()
        try:
            wizards = desktopWizards(domain, protocol)
        except Exception as exc:
            logger.warning("Could not find the wizards of %s: %s", type(protocol).__name__, exc)
            return {}
        baseClasses = {cls.__name__ for cls in type(protocol).mro()}
        wizardMap: Dict[str, List[Dict[str, Any]]] = {}
        for paramName, wizardClass in wizards.items():
            targetParams = [paramName]
            for target in getattr(wizardClass, "_targets", []) or []:
                if (isinstance(target, (list, tuple)) and len(target) == 2
                        and getattr(target[0], "__name__", None) in baseClasses
                        and paramName in (target[1] or [])):
                    targetParams = list(target[1])
                    break
            wizardMap[paramName] = [{
                "id": wizardIdentity(wizardClass),
                "className": wizardClass.__name__,
                "module": wizardClass.__module__,
                "targetParams": targetParams,
                "displayParam": paramName,
                "kind": "runtime",
                "runtime": True,
                "interactive": True,
                "webSupported": True,
                "webView": None,
            }]
        return wizardMap

    def _sanitizeWizardFormValues(
            self,
            params: Dict[str, Any],
    ) -> Dict[str, Any]:
        cleaned: Dict[str, Any] = {}

        for key, value in (params or {}).items():
            if value is None:
                continue

            if isinstance(value, str) and value.strip() == "":
                continue

            cleaned[key] = value

        return cleaned

    def _applyFormValuesToProtocolInstance(
            self,
            protocol,
            params: Dict[str, Any],
            mapper=None,
            projectId: Optional[int] = None,
    ) -> List[str]:
        if self.projectService is None:
            raise RuntimeError("projectService is required to apply wizard form values")

        errorList: List[str] = []

        protectedParams = [
            "_objComment",
            "_useQueue",
            "_prerequisites",
            "gpuList",
            "numberOfThreads",
        ]

        for paramName in protectedParams:
            protVar = getattr(protocol, paramName, None)
            if protVar is None or paramName not in params:
                continue

            value = params[paramName]
            try:
                protVar.set(value)
            except Exception:
                try:
                    setattr(protocol, paramName, value)
                except Exception as e:
                    logger.warning("Could not assign protected param %s: %s", paramName, e)

        for key, value in (params or {}).items():
            param = protocol.getParam(key)
            if param is None:
                continue

            if isinstance(param, (PointerParam, MultiPointerParam, RelationParam)):
                continue

            # Scalars that may point to an output come as {"pointerMode", "value"}:
            # a pointer is resolved with the pointer params below.
            if RuntimeProtocolSaveService._isScalarPointerPayload(value):
                continue
            value = RuntimeProtocolSaveService._getScalarPayloadValue(value)
            if value is None or (isinstance(value, str) and not value.strip()):
                continue

            try:
                castedValue = castProtocolParamValue(param, value)
                errors = param.validate(castedValue) if hasattr(param, "validate") else []
                if errors:
                    errorList += ["**" + param.label.get() + "** " + error for error in errors]

                param.set(castedValue)
                protocol.setAttributeValue(key, castedValue)

            except Exception as e:
                cleaned = re.sub(r"[^A-Za-z0-9\s+\-*/=<>\!&|^%()\[\]{}_,.;:]", "", str(e))
                errorList.append("**" + param.label.get() + "** " + cleaned)

        errorList += self.projectService.applyParamsToProtocol(
            mapper=mapper,
            projectId=projectId,
            protocol=protocol,
            params=params,
        )
        return errorList

    def _buildWizardReadyProtocol(
            self,
            protocolId: Optional[int],
            protocolClassName: str,
            formValues: Dict[str, Any],
            mapper=None,
            projectId: Optional[int] = None,
            protocolIdIsScipionId=False,
    ):
        if protocolId:
            protocolLoader = (
                self.projectService._getScipionProtocolByScipionId
                if protocolIdIsScipionId
                else self.projectService._getScipionProtocolForRuntime
            )

            protocol = protocolLoader(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )
        else:
            protClass = self.currentProject.getDomain().getProtocols().get(str(protocolClassName))
            if protClass is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Protocol class '{protocolClassName}' not found",
                )
            protocol = self.currentProject.newProtocol(protClass)

        self.currentProject._fixProtParamsConfiguration(protocol)

        sanitizedFormValues = self._sanitizeWizardFormValues(formValues or {})
        errors = self._applyFormValuesToProtocolInstance(
            protocol,
            sanitizedFormValues,
            mapper=mapper,
            projectId=projectId,
        )
        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=errors,
            )

        return protocol
