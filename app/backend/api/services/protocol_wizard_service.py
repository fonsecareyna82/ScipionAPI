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

from app.backend.api.services.wizard_handlers import executeWizardHandler
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
        domain = self.currentProject.getDomain() if self.currentProject else pyworkflow.Config.getDomain()
        protocolClass = protocol.getClass() if hasattr(protocol, "getClass") else protocol.__class__

        wizardMap: Dict[str, List[Dict[str, Any]]] = {}

        for wizardClass in domain.getWizards().values():
            targets = getattr(wizardClass, "_targets", []) or []
            if not targets:
                continue

            for target in targets:
                if not isinstance(target, (list, tuple)) or len(target) != 2:
                    continue

                targetClass, targetParams = target

                if not isinstance(targetClass, type):
                    continue

                try:
                    if not issubclass(protocolClass, targetClass):
                        continue
                except TypeError:
                    continue

                targetParamsList = list(targetParams or [])
                if not targetParamsList:
                    continue

                descriptor = self._serializeWizardDescriptor(
                    wizardClass=wizardClass,
                    protocol=protocol,
                    targetParams=targetParamsList,
                )

                for paramName in targetParamsList:
                    wizardMap.setdefault(paramName, [])
                    if not any(
                        existing.get("id") == descriptor.get("id")
                        for existing in wizardMap[paramName]
                    ):
                        wizardMap[paramName].append(copy.deepcopy(descriptor))

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

    def _serializeWizardDescriptor(
            self,
            wizardClass,
            protocol,
            targetParams: List[str],
    ) -> Dict[str, Any]:
        wizardId = f"{wizardClass.__module__}.{wizardClass.__name__}"
        webView = self._safeGetWizardView(wizardClass)
        kind = self._classifyWizardKind(
            wizardClass=wizardClass,
            webView=webView,
            targetParams=targetParams,
        )

        computeKinds = {
            "compute",
            "box_size",
            "consensus_radius",
            "number_of_classes",
            "compute_lane_selector",
            "mask_radius",
            "mask_radii",
            "ctf_preview",
            "downsample_preview",
            "filter_preview",
            "gaussian_preview",
            "point_in_volume"
        }

        webSupported = kind in computeKinds
        interactive = kind not in computeKinds

        return {
            "id": wizardId,
            "className": wizardClass.__name__,
            "module": wizardClass.__module__,
            "targetParams": list(targetParams or []),
            "displayParam": targetParams[0] if targetParams else None,
            "kind": kind,
            "interactive": interactive,
            "webSupported": webSupported,
            "webView": webView,
        }

    def _getWizardBaseClassNames(self, wizardClass) -> List[str]:
        names: List[str] = []

        try:
            for cls in getattr(wizardClass, "__mro__", ()) or ():
                name = getattr(cls, "__name__", None)
                if not name:
                    continue
                token = str(name).strip()
                if token and token not in names:
                    names.append(token)
        except Exception:
            pass

        return names

    def _safeGetWizardView(self, wizardClass) -> Optional[str]:
        try:
            getViewFn = getattr(wizardClass, "getView", None)
            if callable(getViewFn):
                value = getViewFn()
                if value is None:
                    return None
                return str(value)
        except Exception:
            return None

        return None

    def _classifyWizardKind(
            self,
            wizardClass,
            webView: Optional[str],
            targetParams: Optional[List[str]] = None,
    ) -> str:
        className = getattr(wizardClass, "__name__", "") or ""
        classNameLower = className.lower()
        webViewLower = (webView or "").lower()

        normalizedTargetParams = [
            str(item).strip()
            for item in (targetParams or [])
            if str(item).strip()
        ]
        targetParamsLower = [item.lower() for item in normalizedTargetParams]
        targetParamsSet = set(targetParamsLower)

        baseClassNamesLower = {
            name.lower()
            for name in self._getWizardBaseClassNames(wizardClass)
        }

        explicitKinds = {
            "XmippBoxSizeWizard": "box_size",
            "XmippParticleConsensusRadiusWizard": "consensus_radius",
            "XmippCL2DNumberOfClassesWizard": "number_of_classes",
            "ProtCryo2DNumberOfClassesWizard": "number_of_classes",
            "ProtCryosparcLanesWizard": "compute_lane_selector",
        }
        if className in explicitKinds:
            return explicitKinds[className]

        baseKindMap = {
            "downsamplewizard": "downsample_preview",
            "ctfwizard": "ctf_preview",
            "particlemaskradiuswizard": "mask_radius",
            "volumemaskradiuswizard": "mask_radius",
            "particlesmaskradiiwizard": "mask_radii",
            "volumemaskradiiwizard": "mask_radii",
            "filterparticleswizard": "filter_preview",
            "filtervolumeswizard": "filter_preview",
            "gaussianparticleswizard": "gaussian_preview",
            "gaussianvolumeswizard": "gaussian_preview",
            "colorscalewizardbase": "viewer_color_scale",
        }

        for baseName, kind in baseKindMap.items():
            if baseName in baseClassNamesLower:
                return kind

        if {"xin", "yin", "zin"}.issubset(targetParamsSet):
            return "point_in_volume"

        if targetParamsSet in (
                {"innerradius", "outerradius"},
                {"particleradius", "noiseradius"},
        ):
            return "mask_radii"

        if len(targetParamsLower) == 1:
            onlyParam = targetParamsLower[0]
            if onlyParam in {
                "radius",
                "maskradius",
                "volumeradius",
                "volumeradiushalf",
                "cylinderouterradius",
                "cylinderinnerradius",
                "consensusradius",
                "cirmaskrad",
                "rmax",
            }:
                return "mask_radius"

        if (
                len(targetParamsLower) >= 2
                and all("radius" in item for item in targetParamsLower)
        ):
            return "mask_radii"

        if (
                len(targetParamsLower) == 1
                and any(token in targetParamsLower[0] for token in ("down", "factor"))
        ):
            return "downsample_preview"

        if {"ctfdownfactor", "lowres", "highres"}.issubset(targetParamsSet):
            return "ctf_preview"

        if any(item in targetParamsSet for item in {"freqsigma"}):
            return "gaussian_preview"

        if (
                any(item in targetParamsSet for item in {"lowfreqa", "lowfreqdig"})
                and any(item in targetParamsSet for item in {"highfreqa", "highfreqdig"})
                and any(item in targetParamsSet for item in {"freqdecaya", "freqdecaydig"})
        ):
            return "filter_preview"

        if "lane" in classNameLower and "wizard" in classNameLower:
            return "compute_lane_selector"

        if "colorscale" in classNameLower:
            return "viewer_color_scale"

        if "selectpointinvolwizard" in classNameLower or "pointinvol" in classNameLower:
            return "point_in_volume"

        if "ctf" in classNameLower and "wizard" in classNameLower:
            return "ctf_preview"

        if "downsample" in classNameLower and "wizard" in classNameLower:
            return "downsample_preview"

        if "maskradii" in classNameLower and "wizard" in classNameLower:
            return "mask_radii"

        if "maskradius" in classNameLower and "wizard" in classNameLower:
            return "mask_radius"

        if "gaussian" in classNameLower and "wizard" in classNameLower:
            return "gaussian_preview"

        if "filter" in classNameLower and "wizard" in classNameLower:
            return "filter_preview"

        if webViewLower:
            if "ctf" in webViewLower:
                return "ctf_preview"
            if "down" in webViewLower:
                return "downsample_preview"
            if "mask" in webViewLower and "radii" in webViewLower:
                return "mask_radii"
            if "mask" in webViewLower and "radius" in webViewLower:
                return "mask_radius"
            return "legacy_web_view"

        if classNameLower.endswith("wizard") and any(
                token in classNameLower for token in ("boxsize", "radius", "classes")
        ):
            return "compute"

        return "unknown"

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

            try:
                castedValue = castProtocolParamValue(param, value)
                errors = param.validate(castedValue) if hasattr(param, "validate") else []
                if errors:
                    errorList += ["**" + param.label.get() + "** " + error for error in errors]

                param.set(castedValue)
                protocol.setAttributeValue(key, castedValue)

                if key == "runName":
                    protocol.setObjLabel(castedValue)

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
    ):
        if protocolId:
            protocol = self.projectService._getScipionProtocolForRuntime(
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

    def _resolveWizardDescriptorForParam(
        self,
        protocol,
        paramName: str,
        wizardId: str,
    ) -> Optional[Dict[str, Any]]:
        wizardMap = self.findWizardsWeb(protocol) or {}
        paramWizards = wizardMap.get(paramName, []) or []

        for descriptor in paramWizards:
            if str(descriptor.get("id", "")).strip() == str(wizardId).strip():
                return descriptor

        return None

    def _getWizardClassById(self, wizardId: str):
        domain = self.currentProject.getDomain() if self.currentProject else pyworkflow.Config.getDomain()

        for wizardClass in domain.getWizards().values():
            currentId = f"{wizardClass.__module__}.{wizardClass.__name__}"
            if currentId == wizardId:
                return wizardClass

        return None

    def _normalizeExecutionResult(self, paramName: str, rawResult: Any):
        if not isinstance(rawResult, dict):
            return rawResult, None, {}

        if isinstance(rawResult.get("paramUpdates"), dict):
            paramUpdates = rawResult["paramUpdates"]
            message = rawResult.get("message")
            extra = {
                key: value
                for key, value in rawResult.items()
                if key not in {"paramUpdates", "message"}
            }
            return paramUpdates, message, extra

        return rawResult, None, {}

    def executeProtocolWizard(
        self,
        mapper,
        projectId: int,
        currentUser: dict,
        payload,
    ) -> Dict[str, Any]:
        if self.projectService is None:
            raise RuntimeError("projectService is required to execute protocol wizards")

        project = (
            self.projectService
            .loadPostgresqlRuntimeProjectForMutation(
                mapper=mapper,
                projectId=projectId,
                currentUser=currentUser,
            )
        )

        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        self.currentProject = project

        protocol = self._buildWizardReadyProtocol(
            protocolId=getattr(payload, "protocolId", None),
            protocolClassName=str(getattr(payload, "protocolClassName", "")).strip(),
            formValues=getattr(payload, "formValues", {}) or {},
            mapper=mapper,
            projectId=projectId,
        )

        paramName = str(getattr(payload, "paramName", "")).strip()
        wizardId = str(getattr(payload, "wizardId", "")).strip()

        if not paramName:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="paramName is required",
            )

        if not wizardId:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="wizardId is required",
            )

        descriptor = self._resolveWizardDescriptorForParam(protocol, paramName, wizardId)
        if descriptor is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Wizard '{wizardId}' not found for parameter '{paramName}'",
            )

        kind = str(descriptor.get("kind") or "unknown").strip()

        if kind in {
            "viewer_color_scale",
            "legacy_web_view",
            "unknown",
        }:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Wizard kind '{kind}' is not supported yet in web execution",
            )

        wizardClass = self._getWizardClassById(wizardId)
        if wizardClass is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Wizard class '{wizardId}' is not available in current domain",
            )

        try:
            rawResult = executeWizardHandler(
                kind=kind,
                wizardClass=wizardClass,
                protocol=protocol,
                paramName=paramName,
                descriptor=descriptor,
                wizardInputs=getattr(payload, "wizardInputs", {}) or {},
                currentProject=self.currentProject,
                projectId=projectId,
            )

            paramUpdates, message, extra = self._normalizeExecutionResult(paramName, rawResult)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Wizard execution failed: {e}",
            )

        response = {
            "success": True,
            "wizardId": wizardId,
            "kind": kind,
            "paramUpdates": paramUpdates,
            "message": message or "Wizard executed successfully",
        }

        if extra:
            response.update(extra)

        return response