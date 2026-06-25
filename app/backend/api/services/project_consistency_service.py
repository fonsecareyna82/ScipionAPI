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
from datetime import datetime

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from fastapi import HTTPException, status
from pyworkflow.object import PointerList
from pyworkflow.protocol.params import PointerParam, MultiPointerParam, RelationParam

from app.backend.mapper.postgresql import PostgresqlFlatMapper

if TYPE_CHECKING:
    from app.backend.api.services.project_service import ProjectService

logger = logging.getLogger(__name__)


class ProjectConsistencyService:
    def __init__(self, projectService: "ProjectService"):
        self.projectService = projectService

    @property
    def currentProject(self):
        return self.projectService.currentProject

    @currentProject.setter
    def currentProject(self, value):
        self.projectService.currentProject = value

    def __getattr__(self, name: str) -> Any:
        return getattr(self.projectService, name)

    def normalizeStatus(self, value: Any) -> str:
        return str(value or "").strip().lower()

    def normalizeClassName(self, value: Any) -> str:
        return str(value or "").strip()

    def normalizeProtocolId(self, value: Any) -> str:
        return str(value).strip()

    def normalizeOptionalText(self, value: Any) -> Optional[str]:
        if value is None or value == "":
            return None

        text = str(value).strip()
        return text or None

    def toOptionalInt(self, value: Any) -> Optional[int]:
        try:
            if value is None or value == "":
                return None
            return int(value)
        except Exception:
            return None

    def protocolSortKey(self, value: Any):
        text = self.normalizeProtocolId(value)
        try:
            return 0, int(text)
        except Exception:
            return 1, text

    def dependencySortKey(self, item: Tuple[str, str]):
        parentId, childId = item
        return self.protocolSortKey(parentId), self.protocolSortKey(childId)

    def stepSortKey(self, item: Tuple[str, int]):
        protocolId, stepIndex = item
        return self.protocolSortKey(protocolId), int(stepIndex)

    def inputRefSortKey(self, item: Tuple[str, str, int]):
        protocolId, inputName, itemIndex = item
        return self.protocolSortKey(protocolId), str(inputName), int(itemIndex)

    def paramSortKey(self, item: Tuple[str, str]):
        protocolId, paramName = item
        return self.protocolSortKey(protocolId), str(paramName)

    def buildDependency(self, parentId: Any, childId: Any) -> Dict[str, str]:
        return {
            "parentId": self.normalizeProtocolId(parentId),
            "childId": self.normalizeProtocolId(childId),
        }

    def buildStep(self, protocolId: Any, stepIndex: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "protocolId": self.normalizeProtocolId(protocolId),
            "index": int(stepIndex),
            "name": str(payload.get("name") or ""),
            "status": self.normalizeStatus(payload.get("status")),
        }

    def buildInputRef(
            self,
            key: Tuple[str, str, int],
            payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        protocolId, inputName, itemIndex = key
        return {
            "protocolId": self.normalizeProtocolId(protocolId),
            "inputName": str(inputName),
            "itemIndex": int(itemIndex),
            "parentProtocolId": self.normalizeOptionalText(payload.get("parentProtocolId")),
            "parentOutputName": self.normalizeOptionalText(payload.get("parentOutputName")),
            "objectClassName": self.normalizeOptionalText(payload.get("objectClassName")),
        }

    def buildParamIssue(
            self,
            key: Tuple[str, str],
            payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        protocolId, paramName = key
        return {
            "protocolId": self.normalizeProtocolId(protocolId),
            "paramName": str(paramName),
            "value": payload.get("value"),
        }

    def expectedOutputMapperKind(self, className: Any) -> Optional[str]:
        classNameText = self.normalizeOptionalText(className)
        if classNameText is None:
            return None

        if classNameText.startswith("SetOf"):
            return "flat_set"

        return "tree"

    def getRuntimeOutputItemsCount(self, outputObj: Any) -> Optional[int]:
        if outputObj is None:
            return None

        for methodName in ("getSize", "getDim", "__len__"):
            try:
                if methodName == "__len__":
                    value = len(outputObj)
                else:
                    method = getattr(outputObj, methodName, None)
                    if method is None:
                        continue
                    value = method()

                if value is None or value == "":
                    continue

                return int(value)
            except Exception:
                continue

        return None

    def iterPointerItems(self, attr: Any) -> List[Tuple[int, Any]]:
        try:
            if isinstance(attr, PointerList):
                return [
                    (index, pointer)
                    for index, pointer in enumerate(attr)
                ]
        except Exception:
            pass

        return [(0, attr)]

    def dependencyKeyFromInputRef(self, payload: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        parentProtocolId = self.normalizeOptionalText(payload.get("parentProtocolId"))
        childProtocolId = self.normalizeOptionalText(payload.get("protocolId"))

        if not parentProtocolId or not childProtocolId:
            return None

        if parentProtocolId == "PROJECT" or childProtocolId == "PROJECT":
            return None

        if parentProtocolId == childProtocolId:
            return None

        return parentProtocolId, childProtocolId

    def normalizeParamValue(self, value: Any) -> Any:
        if value is None:
            return None

        if isinstance(value, bool):
            return value

        if isinstance(value, (int, float)):
            return value

        if isinstance(value, str):
            text = value.strip()
            if text == "":
                return ""
            lowerText = text.lower()
            if lowerText in ("true", "false"):
                return lowerText == "true"

            try:
                if "." not in text:
                    return int(text)
            except Exception:
                pass

            try:
                return float(text)
            except Exception:
                return text

        if isinstance(value, (list, tuple)):
            return [self.normalizeParamValue(item) for item in value]

        if isinstance(value, dict):
            return {
                str(key): self.normalizeParamValue(itemValue)
                for key, itemValue in value.items()
            }

        try:
            if hasattr(value, "get"):
                return self.normalizeParamValue(value.get())
        except Exception:
            pass

        return str(value)

    def isPointerParam(self, param: Any) -> bool:
        return isinstance(param, (PointerParam, MultiPointerParam, RelationParam))

    def stepValue(self, step: Any, attrName: str, fallback: Any = None) -> Any:
        try:
            value = getattr(step, attrName, None)
            if hasattr(value, "get"):
                return value.get()
            return value if value is not None else fallback
        except Exception:
            return fallback

    def getStepName(self, step: Any) -> str:
        name = self.stepValue(step, "funcName", None)
        if name:
            return str(name)

        className = self._safeCall(step, "getClassName", None)
        return str(className or "")

    def extractRuntimeInputRef(
            self,
            protocolId: str,
            inputName: str,
            itemIndex: int,
            pointer: Any,
    ) -> Optional[Dict[str, Any]]:
        parentProtocolId = None
        parentOutputName = None
        objectClassName = None
        objectId = None

        try:
            parentObj = pointer.getObjValue()
            parentProtocolId = self.normalizeOptionalText(
                self._safeCall(parentObj, "getObjId", None)
            )
        except Exception:
            parentProtocolId = None

        try:
            parentOutputName = self.normalizeOptionalText(pointer.getExtended())
        except Exception:
            parentOutputName = None

        try:
            targetObj = pointer.get()
            if targetObj is not None:
                objectClassName = self.normalizeOptionalText(
                    self._getScipionClassName(targetObj)
                )
                objectId = self.normalizeOptionalText(
                    self._safeCall(targetObj, "getObjId", None)
                )
        except Exception:
            objectClassName = None
            objectId = None

        if parentProtocolId is None and parentOutputName is None:
            return None

        return {
            "protocolId": self.normalizeProtocolId(protocolId),
            "inputName": str(inputName),
            "itemIndex": int(itemIndex),
            "parentProtocolId": parentProtocolId,
            "parentOutputName": parentOutputName,
            "objectClassName": objectClassName,
            "objectId": objectId,
        }

    def extractRuntimeParams(self, protocol: Any) -> Dict[str, Dict[str, Any]]:
        paramsByName: Dict[str, Dict[str, Any]] = {}

        try:
            self.currentProject._fixProtParamsConfiguration(protocol)
        except Exception:
            pass

        try:
            for paramName, param in protocol.iterParams():
                paramNameText = str(paramName or "").strip()
                if not paramNameText:
                    continue

                if self.isPointerParam(param):
                    continue

                rawValue = None
                try:
                    rawValue = protocol.getAttributeValue(paramNameText)
                except Exception:
                    try:
                        rawValue = getattr(protocol, paramNameText, None)
                    except Exception:
                        rawValue = None

                paramsByName[paramNameText] = {
                    "value": self.normalizeParamValue(rawValue),
                }
        except Exception:
            logger.debug(
                "Could not inspect runtime protocol params during consistency check.",
                exc_info=True,
            )

        return paramsByName

    def extractPostgresqlParams(self, row: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        rawParams = row.get("params")
        if not isinstance(rawParams, dict):
            return {}

        paramsByName: Dict[str, Dict[str, Any]] = {}
        for paramName, rawValue in rawParams.items():
            paramNameText = str(paramName or "").strip()
            if not paramNameText:
                continue

            paramsByName[paramNameText] = {
                "value": self.normalizeParamValue(rawValue),
            }

        return paramsByName

    def collectRuntimeSnapshot(
            self,
            projectId: int,
            refresh: bool,
            checkPid: bool,
    ) -> Dict[str, Any]:
        runtimeStatuses: Dict[str, str] = {}
        runtimeClassNames: Dict[str, str] = {}
        runtimeDependencies: Set[Tuple[str, str]] = set()
        runtimeOutputsByProtocolId: Dict[str, Dict[str, Dict[str, Any]]] = {}
        runtimeStepsByProtocolId: Dict[str, Dict[int, Dict[str, Any]]] = {}
        runtimeInputRefsByKey: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
        runtimeParamsByProtocolId: Dict[str, Dict[str, Dict[str, Any]]] = {}

        try:
            runs = self.currentProject.getRunsGraph(refresh=refresh, checkPids=checkPid)
            nodesDict = getattr(runs, "_nodesDict", {}) or {}
        except Exception as e:
            logger.exception(
                "Failed to load Scipion runtime graph for consistency check. projectId=%s",
                projectId,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to load Scipion runtime graph: {e}",
            )

        for nodeId, nodeObj in nodesDict.items():
            protocolId = self.normalizeProtocolId(nodeId)
            if not protocolId or protocolId == "PROJECT":
                continue

            protocol = getattr(nodeObj, "run", None)
            runtimeStatuses[protocolId] = self.normalizeStatus(
                self._safeCall(protocol, "getStatus", None)
            )
            runtimeClassNames[protocolId] = self.normalizeClassName(
                self._safeCall(protocol, "getClassName", None)
            )
            runtimeOutputsByProtocolId.setdefault(protocolId, {})

            if protocol is not None:
                try:
                    for outputItem in protocol.iterOutputAttributes():
                        outputName = None
                        outputObj = None

                        if isinstance(outputItem, (tuple, list)) and len(outputItem) >= 2:
                            outputName = outputItem[0]
                            outputObj = outputItem[1]
                        else:
                            outputName = self._safeCall(outputItem, "getName", None)
                            outputObj = outputItem

                        outputName = str(outputName or "").strip()
                        if not outputName or outputObj is None:
                            continue

                        outputClassName = self._getScipionClassName(outputObj)
                        runtimeOutputsByProtocolId[protocolId][outputName] = {
                            "outputName": outputName,
                            "className": outputClassName,
                            "itemsCount": self.getRuntimeOutputItemsCount(outputObj)
                            if self.expectedOutputMapperKind(outputClassName) == "flat_set"
                            else None,
                        }
                except Exception:
                    logger.debug(
                        "Could not inspect runtime protocol outputs during consistency check. "
                        "projectId=%s protocolId=%s",
                        projectId,
                        protocolId,
                        exc_info=True,
                    )

                runtimeStepsByProtocolId.setdefault(protocolId, {})

                try:
                    for step in protocol.loadSteps() or []:
                        stepIndex = self.toOptionalInt(self._safeCall(step, "getIndex", None))
                        if stepIndex is None:
                            continue

                        runtimeStepsByProtocolId[protocolId][stepIndex] = {
                            "index": stepIndex,
                            "name": self.getStepName(step),
                            "status": self.normalizeStatus(self._safeCall(step, "getStatus", None)),
                        }
                except Exception:
                    logger.debug(
                        "Could not inspect runtime protocol steps during consistency check. "
                        "projectId=%s protocolId=%s",
                        projectId,
                        protocolId,
                        exc_info=True,
                    )

                try:
                    for inputName, attr in protocol.iterInputAttributes():
                        inputNameText = str(inputName or "").strip()
                        if not inputNameText:
                            continue

                        for itemIndex, pointer in self.iterPointerItems(attr):
                            inputRef = self.extractRuntimeInputRef(
                                protocolId=protocolId,
                                inputName=inputNameText,
                                itemIndex=int(itemIndex),
                                pointer=pointer,
                            )
                            if inputRef is None:
                                continue

                            key = (
                                inputRef["protocolId"],
                                inputRef["inputName"],
                                inputRef["itemIndex"],
                            )
                            runtimeInputRefsByKey[key] = inputRef
                except Exception:
                    logger.debug(
                        "Could not inspect runtime protocol input refs during consistency check. "
                        "projectId=%s protocolId=%s",
                        projectId,
                        protocolId,
                        exc_info=True,
                    )

                runtimeParamsByProtocolId[protocolId] = self.extractRuntimeParams(protocol)

            for parent in getattr(nodeObj, "_parents", []) or []:
                try:
                    parentId = self.normalizeProtocolId(parent.getName())
                except Exception:
                    parentId = self.normalizeProtocolId(parent)

                if not parentId or parentId == "PROJECT":
                    continue

                runtimeDependencies.add((parentId, protocolId))

        return {
            "statuses": runtimeStatuses,
            "classNames": runtimeClassNames,
            "dependencies": runtimeDependencies,
            "outputsByProtocolId": runtimeOutputsByProtocolId,
            "stepsByProtocolId": runtimeStepsByProtocolId,
            "inputRefsByKey": runtimeInputRefsByKey,
            "paramsByProtocolId": runtimeParamsByProtocolId,
        }

    def validateProjectPostgresqlConsistency(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            currentUser: dict,
            refresh: bool = True,
            checkPid: bool = True,
    ) -> Dict[str, Any]:
        dbProj = self.getProjectDbRow(mapper, projectId, currentUser)
        if not dbProj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        self.loadProjectForThumbnails(dbProj)

        runtimeSnapshot = self.collectRuntimeSnapshot(
            projectId=projectId,
            refresh=refresh,
            checkPid=checkPid,
        )

        runtimeStatuses = runtimeSnapshot["statuses"]
        runtimeClassNames = runtimeSnapshot["classNames"]
        runtimeDependencies = runtimeSnapshot["dependencies"]
        runtimeOutputsByProtocolId = runtimeSnapshot["outputsByProtocolId"]
        runtimeStepsByProtocolId = runtimeSnapshot["stepsByProtocolId"]
        runtimeInputRefsByKey = runtimeSnapshot["inputRefsByKey"]
        runtimeParamsByProtocolId = runtimeSnapshot["paramsByProtocolId"]

        try:
            protocolRows = mapper.getProtocols(projectId) or []
        except Exception as e:
            logger.exception(
                "Failed to load PostgreSQL protocols for consistency check. projectId=%s",
                projectId,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to load PostgreSQL protocols: {e}",
            )

        postgresqlStatuses: Dict[str, str] = {}
        postgresqlClassNames: Dict[str, str] = {}
        postgresqlParamsByProtocolId: Dict[str, Dict[str, Dict[str, Any]]] = {}

        for row in protocolRows:
            protocolId = self.normalizeProtocolId(row.get("protocolId"))
            if not protocolId:
                continue

            postgresqlStatuses[protocolId] = self.normalizeStatus(row.get("status"))
            postgresqlClassNames[protocolId] = self.normalizeClassName(row.get("protocolClassName"))
            postgresqlParamsByProtocolId[protocolId] = self.extractPostgresqlParams(row)

        try:
            adjacencyMap = mapper.getProjectProtocolAdjacencyMap(projectId) or {}
        except Exception as e:
            logger.exception(
                "Failed to load PostgreSQL protocol dependencies for consistency check. projectId=%s",
                projectId,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to load PostgreSQL protocol dependencies: {e}",
            )

        postgresqlDependencies: Set[Tuple[str, str]] = set()
        for childId, refs in adjacencyMap.items():
            childProtocolId = self.normalizeProtocolId(childId)
            if not childProtocolId or childProtocolId == "PROJECT":
                continue

            for parentIdValue in refs.get("parents") or []:
                parentProtocolId = self.normalizeProtocolId(parentIdValue)
                if not parentProtocolId or parentProtocolId == "PROJECT":
                    continue

                postgresqlDependencies.add((parentProtocolId, childProtocolId))

        try:
            persistedOutputsByProtocolId = self._loadPersistedOutputsByProtocolId(
                mapper,
                projectId,
            )
        except Exception as e:
            logger.exception(
                "Failed to load PostgreSQL persisted outputs for consistency check. projectId=%s",
                projectId,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to load PostgreSQL persisted outputs: {e}",
            )

        try:
            postgresqlStepsByProtocolId = mapper.getProjectProtocolStepsByProtocolId(projectId) or {}
        except Exception as e:
            logger.exception(
                "Failed to load PostgreSQL protocol steps for consistency check. projectId=%s",
                projectId,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to load PostgreSQL protocol steps: {e}",
            )

        normalizedPostgresqlStepsByProtocolId: Dict[str, Dict[int, Dict[str, Any]]] = {}
        for protocolId, steps in postgresqlStepsByProtocolId.items():
            protocolIdText = self.normalizeProtocolId(protocolId)
            for step in steps or []:
                stepIndex = self.toOptionalInt(step.get("index"))
                if stepIndex is None:
                    continue

                normalizedPostgresqlStepsByProtocolId.setdefault(protocolIdText, {})[stepIndex] = {
                    "index": stepIndex,
                    "name": str(step.get("name") or ""),
                    "status": self.normalizeStatus(step.get("status")),
                }

        try:
            postgresqlInputRefs = mapper.listProtocolInputRefs(projectId) or []
        except Exception as e:
            logger.exception(
                "Failed to load PostgreSQL protocol input refs for consistency check. projectId=%s",
                projectId,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to load PostgreSQL protocol input refs: {e}",
            )

        postgresqlInputRefsByKey: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
        for ref in postgresqlInputRefs:
            protocolIdText = self.normalizeProtocolId(ref.get("protocolId"))
            inputName = str(ref.get("inputName") or "").strip()
            itemIndex = self.toOptionalInt(ref.get("itemIndex"))

            if not protocolIdText or not inputName:
                continue

            if itemIndex is None or itemIndex < 0:
                itemIndex = 0

            key = (protocolIdText, inputName, int(itemIndex))
            postgresqlInputRefsByKey[key] = {
                "protocolId": protocolIdText,
                "inputName": inputName,
                "itemIndex": int(itemIndex),
                "parentProtocolId": self.normalizeOptionalText(ref.get("parentProtocolId")),
                "parentOutputName": self.normalizeOptionalText(ref.get("parentOutputName")),
                "objectClassName": self.normalizeOptionalText(ref.get("objectClassName")),
                "objectId": self.normalizeOptionalText(ref.get("objectId")),
            }

        runtimeOutputs: Set[Tuple[str, str]] = set()
        for protocolId, outputsByName in runtimeOutputsByProtocolId.items():
            for outputName in outputsByName.keys():
                runtimeOutputs.add((protocolId, outputName))

        postgresqlOutputs: Set[Tuple[str, str]] = set()
        for protocolId, outputsByName in persistedOutputsByProtocolId.items():
            for outputName in outputsByName.keys():
                postgresqlOutputs.add((self.normalizeProtocolId(protocolId), str(outputName)))

        runtimeSteps: Set[Tuple[str, int]] = set()
        for protocolId, stepsByIndex in runtimeStepsByProtocolId.items():
            for stepIndex in stepsByIndex.keys():
                runtimeSteps.add((protocolId, int(stepIndex)))

        postgresqlSteps: Set[Tuple[str, int]] = set()
        for protocolId, stepsByIndex in normalizedPostgresqlStepsByProtocolId.items():
            for stepIndex in stepsByIndex.keys():
                postgresqlSteps.add((protocolId, int(stepIndex)))

        runtimeProtocolIds = set(runtimeStatuses.keys())
        postgresqlProtocolIds = set(postgresqlStatuses.keys())
        runtimeInputRefs = set(runtimeInputRefsByKey.keys())
        postgresqlInputRefsKeys = set(postgresqlInputRefsByKey.keys())
        runtimeDependenciesFromInputRefs: Set[Tuple[str, str]] = set()

        runtimeParams: Set[Tuple[str, str]] = set()
        for protocolId, paramsByName in runtimeParamsByProtocolId.items():
            for paramName in paramsByName.keys():
                runtimeParams.add((protocolId, paramName))

        postgresqlParams: Set[Tuple[str, str]] = set()
        for protocolId, paramsByName in postgresqlParamsByProtocolId.items():
            for paramName in paramsByName.keys():
                postgresqlParams.add((protocolId, paramName))

        for inputRef in runtimeInputRefsByKey.values():
            dependencyKey = self.dependencyKeyFromInputRef(inputRef)
            if dependencyKey is not None:
                runtimeDependenciesFromInputRefs.add(dependencyKey)

        postgresqlDependenciesFromInputRefs: Set[Tuple[str, str]] = set()
        for inputRef in postgresqlInputRefsByKey.values():
            dependencyKey = self.dependencyKeyFromInputRef(inputRef)
            if dependencyKey is not None:
                postgresqlDependenciesFromInputRefs.add(dependencyKey)

        missingProtocolIds = sorted(
            runtimeProtocolIds - postgresqlProtocolIds,
            key=self.protocolSortKey,
        )
        extraProtocolIds = sorted(
            postgresqlProtocolIds - runtimeProtocolIds,
            key=self.protocolSortKey,
        )

        commonProtocolIds = sorted(
            runtimeProtocolIds.intersection(postgresqlProtocolIds),
            key=self.protocolSortKey,
        )

        statusMismatches = []
        for protocolId in commonProtocolIds:
            runtimeStatus = runtimeStatuses.get(protocolId, "")
            postgresqlStatus = postgresqlStatuses.get(protocolId, "")

            if runtimeStatus != postgresqlStatus:
                statusMismatches.append({
                    "protocolId": protocolId,
                    "runtimeStatus": runtimeStatus,
                    "postgresqlStatus": postgresqlStatus,
                })

        protocolClassMismatches = []
        for protocolId in commonProtocolIds:
            runtimeClassName = self.normalizeClassName(runtimeClassNames.get(protocolId))
            postgresqlClassName = self.normalizeClassName(postgresqlClassNames.get(protocolId))

            if (
                    runtimeClassName
                    and postgresqlClassName
                    and runtimeClassName != postgresqlClassName
            ):
                protocolClassMismatches.append({
                    "protocolId": protocolId,
                    "runtimeClassName": runtimeClassName,
                    "postgresqlClassName": postgresqlClassName,
                })

        missingDependencies = sorted(
            runtimeDependencies - postgresqlDependencies,
            key=self.dependencySortKey,
        )
        extraDependencies = sorted(
            postgresqlDependencies - runtimeDependencies,
            key=self.dependencySortKey,
        )

        missingOutputs = sorted(
            runtimeOutputs - postgresqlOutputs,
            key=self.dependencySortKey,
        )
        extraOutputs = sorted(
            postgresqlOutputs - runtimeOutputs,
            key=self.dependencySortKey,
        )

        outputClassMismatches = []
        for protocolId, outputName in sorted(runtimeOutputs.intersection(postgresqlOutputs), key=self.dependencySortKey):
            runtimeOutput = runtimeOutputsByProtocolId.get(protocolId, {}).get(outputName, {})
            postgresqlOutput = persistedOutputsByProtocolId.get(protocolId, {}).get(outputName, {})

            runtimeClassName = self.normalizeOptionalText(runtimeOutput.get("className"))
            postgresqlClassName = self.normalizeOptionalText(postgresqlOutput.get("className"))

            if (
                    runtimeClassName is not None
                    and postgresqlClassName is not None
                    and runtimeClassName != postgresqlClassName
            ):
                outputClassMismatches.append({
                    "protocolId": protocolId,
                    "outputName": outputName,
                    "runtimeClassName": runtimeClassName,
                    "postgresqlClassName": postgresqlClassName,
                    "mapperKind": postgresqlOutput.get("mapperKind"),
                })

        outputMapperKindMismatches = []
        for protocolId, outputName in sorted(runtimeOutputs.intersection(postgresqlOutputs), key=self.dependencySortKey):
            runtimeOutput = runtimeOutputsByProtocolId.get(protocolId, {}).get(outputName, {})
            postgresqlOutput = persistedOutputsByProtocolId.get(protocolId, {}).get(outputName, {})

            runtimeClassName = self.normalizeOptionalText(runtimeOutput.get("className"))
            expectedMapperKind = self.expectedOutputMapperKind(runtimeClassName)
            postgresqlMapperKind = self.normalizeOptionalText(postgresqlOutput.get("mapperKind"))

            if (
                    expectedMapperKind is not None
                    and postgresqlMapperKind is not None
                    and expectedMapperKind != postgresqlMapperKind
            ):
                outputMapperKindMismatches.append({
                    "protocolId": protocolId,
                    "outputName": outputName,
                    "className": runtimeClassName,
                    "expectedMapperKind": expectedMapperKind,
                    "postgresqlMapperKind": postgresqlMapperKind,
                })

        outputItemsCountMismatches = []
        for protocolId, outputName in sorted(runtimeOutputs.intersection(postgresqlOutputs), key=self.dependencySortKey):
            runtimeOutput = runtimeOutputsByProtocolId.get(protocolId, {}).get(outputName, {})
            postgresqlOutput = persistedOutputsByProtocolId.get(protocolId, {}).get(outputName, {})

            runtimeClassName = self.normalizeOptionalText(runtimeOutput.get("className"))
            if self.expectedOutputMapperKind(runtimeClassName) != "flat_set":
                continue

            runtimeItemsCount = self.toOptionalInt(runtimeOutput.get("itemsCount"))
            postgresqlItemsCount = self.toOptionalInt(postgresqlOutput.get("itemsCount"))

            if runtimeItemsCount is None or postgresqlItemsCount is None:
                continue

            if runtimeItemsCount != postgresqlItemsCount:
                outputItemsCountMismatches.append({
                    "protocolId": protocolId,
                    "outputName": outputName,
                    "className": runtimeClassName,
                    "runtimeItemsCount": runtimeItemsCount,
                    "postgresqlItemsCount": postgresqlItemsCount,
                    "mapperKind": postgresqlOutput.get("mapperKind"),
                })

        missingSteps = sorted(
            runtimeSteps - postgresqlSteps,
            key=self.stepSortKey,
        )
        extraSteps = sorted(
            postgresqlSteps - runtimeSteps,
            key=self.stepSortKey,
        )

        stepMismatches = []
        for protocolId, stepIndex in sorted(runtimeSteps.intersection(postgresqlSteps), key=self.stepSortKey):
            runtimeStep = runtimeStepsByProtocolId.get(protocolId, {}).get(stepIndex, {})
            postgresqlStep = normalizedPostgresqlStepsByProtocolId.get(protocolId, {}).get(stepIndex, {})

            runtimeName = str(runtimeStep.get("name") or "")
            postgresqlName = str(postgresqlStep.get("name") or "")
            runtimeStatus = self.normalizeStatus(runtimeStep.get("status"))
            postgresqlStatus = self.normalizeStatus(postgresqlStep.get("status"))

            changedFields = []
            if runtimeName != postgresqlName:
                changedFields.append("name")
            if runtimeStatus != postgresqlStatus:
                changedFields.append("status")

            if changedFields:
                stepMismatches.append({
                    "protocolId": protocolId,
                    "index": int(stepIndex),
                    "fields": changedFields,
                    "runtimeName": runtimeName,
                    "postgresqlName": postgresqlName,
                    "runtimeStatus": runtimeStatus,
                    "postgresqlStatus": postgresqlStatus,
                })


        missingInputRefs = sorted(
            runtimeInputRefs - postgresqlInputRefsKeys,
            key=self.inputRefSortKey,
        )
        extraInputRefs = sorted(
            postgresqlInputRefsKeys - runtimeInputRefs,
            key=self.inputRefSortKey,
        )

        missingParams = sorted(
            runtimeParams - postgresqlParams,
            key=self.paramSortKey,
        )
        extraParams = sorted(
            postgresqlParams - runtimeParams,
            key=self.paramSortKey,
        )

        paramValueMismatches = []
        for key in sorted(runtimeParams.intersection(postgresqlParams), key=self.paramSortKey):
            protocolId, paramName = key

            runtimeParam = runtimeParamsByProtocolId.get(protocolId, {}).get(paramName, {})
            postgresqlParam = postgresqlParamsByProtocolId.get(protocolId, {}).get(paramName, {})

            runtimeValue = self.normalizeParamValue(runtimeParam.get("value"))
            postgresqlValue = self.normalizeParamValue(postgresqlParam.get("value"))

            if runtimeValue != postgresqlValue:
                paramValueMismatches.append({
                    "protocolId": protocolId,
                    "paramName": paramName,
                    "runtimeValue": runtimeValue,
                    "postgresqlValue": postgresqlValue,
                })

        inputRefMismatches = []
        for key in sorted(runtimeInputRefs.intersection(postgresqlInputRefsKeys), key=self.inputRefSortKey):
            runtimeRef = runtimeInputRefsByKey.get(key, {})
            postgresqlRef = postgresqlInputRefsByKey.get(key, {})

            changedFields = []

            runtimeParentProtocolId = self.normalizeOptionalText(runtimeRef.get("parentProtocolId"))
            postgresqlParentProtocolId = self.normalizeOptionalText(postgresqlRef.get("parentProtocolId"))

            runtimeParentOutputName = self.normalizeOptionalText(runtimeRef.get("parentOutputName"))
            postgresqlParentOutputName = self.normalizeOptionalText(postgresqlRef.get("parentOutputName"))

            runtimeObjectClassName = self.normalizeOptionalText(runtimeRef.get("objectClassName"))
            postgresqlObjectClassName = self.normalizeOptionalText(postgresqlRef.get("objectClassName"))

            if runtimeParentProtocolId != postgresqlParentProtocolId:
                changedFields.append("parentProtocolId")

            if runtimeParentOutputName != postgresqlParentOutputName:
                changedFields.append("parentOutputName")

            if (
                    runtimeObjectClassName is not None
                    and postgresqlObjectClassName is not None
                    and runtimeObjectClassName != postgresqlObjectClassName
            ):
                changedFields.append("objectClassName")

            if changedFields:
                protocolId, inputName, itemIndex = key
                inputRefMismatches.append({
                    "protocolId": protocolId,
                    "inputName": inputName,
                    "itemIndex": int(itemIndex),
                    "fields": changedFields,
                    "runtimeParentProtocolId": runtimeParentProtocolId,
                    "postgresqlParentProtocolId": postgresqlParentProtocolId,
                    "runtimeParentOutputName": runtimeParentOutputName,
                    "postgresqlParentOutputName": postgresqlParentOutputName,
                    "runtimeObjectClassName": runtimeObjectClassName,
                    "postgresqlObjectClassName": postgresqlObjectClassName,
                })

        runtimeInputRefDependenciesMissing = sorted(
            runtimeDependenciesFromInputRefs - runtimeDependencies,
            key=self.dependencySortKey,
        )
        runtimeDependenciesWithoutInputRefs = sorted(
            runtimeDependencies - runtimeDependenciesFromInputRefs,
            key=self.dependencySortKey,
        )

        postgresqlInputRefDependenciesMissing = sorted(
            postgresqlDependenciesFromInputRefs - postgresqlDependencies,
            key=self.dependencySortKey,
        )
        postgresqlDependenciesWithoutInputRefs = sorted(
            postgresqlDependencies - postgresqlDependenciesFromInputRefs,
            key=self.dependencySortKey,
        )

        issues = {
            "missingProtocols": [
                {
                    "protocolId": protocolId,
                    "runtimeStatus": runtimeStatuses.get(protocolId, ""),
                }
                for protocolId in missingProtocolIds
            ],
            "extraProtocols": [
                {
                    "protocolId": protocolId,
                    "postgresqlStatus": postgresqlStatuses.get(protocolId, ""),
                }
                for protocolId in extraProtocolIds
            ],
            "statusMismatches": statusMismatches,
            "protocolClassMismatches": protocolClassMismatches,
            "missingDependencies": [
                self.buildDependency(parentId, childId)
                for parentId, childId in missingDependencies
            ],
            "extraDependencies": [
                self.buildDependency(parentId, childId)
                for parentId, childId in extraDependencies
            ],
            "missingOutputs": [
                {
                    "protocolId": protocolId,
                    "outputName": outputName,
                    "className": runtimeOutputsByProtocolId
                    .get(protocolId, {})
                    .get(outputName, {})
                    .get("className"),
                }
                for protocolId, outputName in missingOutputs
            ],
            "extraOutputs": [
                {
                    "protocolId": protocolId,
                    "outputName": outputName,
                    "mapperKind": persistedOutputsByProtocolId
                    .get(protocolId, {})
                    .get(outputName, {})
                    .get("mapperKind"),
                    "className": persistedOutputsByProtocolId
                    .get(protocolId, {})
                    .get(outputName, {})
                    .get("className"),
                }
                for protocolId, outputName in extraOutputs
            ],
            "outputClassMismatches": outputClassMismatches,
            "outputMapperKindMismatches": outputMapperKindMismatches,
            "outputItemsCountMismatches": outputItemsCountMismatches,

            "missingSteps": [
                self.buildStep(
                    protocolId,
                    stepIndex,
                    runtimeStepsByProtocolId.get(protocolId, {}).get(stepIndex, {}),
                )
                for protocolId, stepIndex in missingSteps
            ],
            "extraSteps": [
                self.buildStep(
                    protocolId,
                    stepIndex,
                    normalizedPostgresqlStepsByProtocolId.get(protocolId, {}).get(stepIndex, {}),
                )
                for protocolId, stepIndex in extraSteps
            ],
            "stepMismatches": stepMismatches,
            "missingInputRefs": [
                self.buildInputRef(key, runtimeInputRefsByKey.get(key, {}))
                for key in missingInputRefs
            ],
            "extraInputRefs": [
                self.buildInputRef(key, postgresqlInputRefsByKey.get(key, {}))
                for key in extraInputRefs
            ],
            "inputRefMismatches": inputRefMismatches,
            "runtimeInputRefDependenciesMissing": [
                self.buildDependency(parentId, childId)
                for parentId, childId in runtimeInputRefDependenciesMissing
            ],
            "runtimeDependenciesWithoutInputRefs": [
                self.buildDependency(parentId, childId)
                for parentId, childId in runtimeDependenciesWithoutInputRefs
            ],
            "postgresqlInputRefDependenciesMissing": [
                self.buildDependency(parentId, childId)
                for parentId, childId in postgresqlInputRefDependenciesMissing
            ],
            "postgresqlDependenciesWithoutInputRefs": [
                self.buildDependency(parentId, childId)
                for parentId, childId in postgresqlDependenciesWithoutInputRefs
            ],
            "missingParams": [
                self.buildParamIssue(key, runtimeParamsByProtocolId.get(key[0], {}).get(key[1], {}))
                for key in missingParams
            ],
            "extraParams": [
                self.buildParamIssue(key, postgresqlParamsByProtocolId.get(key[0], {}).get(key[1], {}))
                for key in extraParams
            ],
            "paramValueMismatches": paramValueMismatches,
        }

        issuesCount = sum(len(items) for items in issues.values())

        return {
            "ok": issuesCount == 0,
            "projectId": projectId,
            "checkedAt": datetime.utcnow().isoformat() + "Z",
            "summary": {
                "runtimeProtocols": len(runtimeProtocolIds),
                "postgresqlProtocols": len(postgresqlProtocolIds),
                "runtimeDependencies": len(runtimeDependencies),
                "postgresqlDependencies": len(postgresqlDependencies),
                "runtimeOutputs": len(runtimeOutputs),
                "postgresqlOutputs": len(postgresqlOutputs),
                "runtimeSteps": len(runtimeSteps),
                "postgresqlSteps": len(postgresqlSteps),
                "runtimeInputRefs": len(runtimeInputRefs),
                "postgresqlInputRefs": len(postgresqlInputRefsKeys),
                "runtimeInputRefDependencies": len(runtimeDependenciesFromInputRefs),
                "postgresqlInputRefDependencies": len(postgresqlDependenciesFromInputRefs),
                "runtimeParams": len(runtimeParams),
                "postgresqlParams": len(postgresqlParams),
                "issues": issuesCount,
            },
            "issues": issues,
        }
