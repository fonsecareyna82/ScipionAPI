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
import re
import logging
from typing import Any, Callable, Dict, List, Optional

from app.backend.runtime.protocol_graph_repository import ProtocolGraphRepository

logger = logging.getLogger(__name__)


class RuntimeOutputRelationRepairService:
    """Repair missing runtime relations between persisted PostgreSQL outputs."""

    defaultRelationRules = [
        {
            "name": "set_of_tilt_series",
            "getterName": "getSetOfTiltSeries",
            "setterName": "setSetOfTiltSeries",
            "targetClassNames": [
                "SetOfTiltSeries",
            ],
            "targetItemClassNames": [
                "TiltSeries",
            ],
        },
    ]

    def __init__(self):
        self.protocolGraphRepository = ProtocolGraphRepository()

    @staticmethod
    def _loadRuntimeOutputFromFallback(mapper, outputInfo: Dict[str, Any]):
        runtimeObjectId = (outputInfo or {}).get("runtimeObjectId")

        if runtimeObjectId in (None, ""):
            return None

        try:
            runtimeObjectId = int(runtimeObjectId)
        except Exception:
            return None

        for fallbackMapper in (
                getattr(mapper, "writeFallbackMapper", None),
                getattr(mapper, "readFallbackMapper", None),
        ):
            if fallbackMapper is None:
                continue

            selectById = getattr(fallbackMapper, "selectById", None)

            if not callable(selectById):
                continue

            try:
                outputObj = selectById(runtimeObjectId)
            except Exception:
                outputObj = None

            if outputObj is not None:
                return outputObj

        return None

    @staticmethod
    def isPostgresqlProxy(obj) -> bool:
        try:
            checker = getattr(obj, "isPostgresqlRuntimeOutput", None)
            return callable(checker) and bool(checker())
        except Exception:
            return False

    @staticmethod
    def outputInfoMatchesRule(
            outputInfo: Dict[str, Any],
            relationRule: Dict[str, Any],
    ) -> bool:
        className = str(outputInfo.get("className") or "")
        itemClassName = str(outputInfo.get("itemClassName") or "")

        targetClassNames = relationRule.get("targetClassNames") or []
        targetItemClassNames = relationRule.get("targetItemClassNames") or []

        for targetClassName in targetClassNames:
            targetClassName = str(targetClassName or "")

            if not targetClassName:
                continue

            if targetClassName in className or className.endswith(targetClassName):
                return True

        for targetItemClassName in targetItemClassNames:
            targetItemClassName = str(targetItemClassName or "")

            if not targetItemClassName:
                continue

            if itemClassName.endswith(targetItemClassName):
                return True

        return False

    @staticmethod
    def buildAccessorNamesFromRelationName(relationName):
        relationName = str(relationName or "").strip()

        if not relationName:
            return None, None

        if "_" in relationName:
            baseName = "".join(
                part[:1].upper() + part[1:]
                for part in relationName.split("_")
                if part
            )
        else:
            baseName = relationName[:1].upper() + relationName[1:]

        if not baseName:
            return None, None

        return f"get{baseName}", f"set{baseName}"

    @staticmethod
    def buildRelationNameFromAccessorSuffix(accessorSuffix: str) -> str:
        accessorSuffix = str(accessorSuffix or "").strip()
        if not accessorSuffix:
            return ""
        return re.sub(r"(?<!^)(?=[A-Z])", "_", accessorSuffix).lower()

    def buildRelationRulesFromInputCandidates(
            self,
            mapper,
            projectId: int,
            outputObj,
            inputRefRows: List[Dict[str, Any]],
            currentInputName: str,
    ) -> List[Dict[str, Any]]:
        if outputObj is None:
            return []

        relationRules = []
        seen = set()

        for ref in inputRefRows or []:
            candidateInputName = str(ref.get("inputName") or "").strip()
            candidateParentProtocolDbId = ref.get("parentProtocolDbId")
            candidateOutputName = str(ref.get("parentOutputName") or "").strip()

            if not candidateInputName or candidateInputName == currentInputName:
                continue

            if candidateParentProtocolDbId in (None, "") or not candidateOutputName:
                continue

            try:
                candidateOutputInfo = self.protocolGraphRepository.getPostgresqlRuntimeOutputInfo(
                    mapper=mapper,
                    projectId=projectId,
                    parentProtocolDbId=int(candidateParentProtocolDbId),
                    outputName=candidateOutputName,
                )
            except Exception:
                continue

            if not candidateOutputInfo.get("exists"):
                continue

            for className in (
                    candidateOutputInfo.get("className"),
                    candidateOutputInfo.get("itemClassName"),
            ):
                className = str(className or "").strip()

                if not className:
                    continue

                getterName = "get%s" % className
                setterName = "set%s" % className

                if not hasattr(outputObj, getterName):
                    continue

                if not hasattr(outputObj, setterName):
                    continue

                relationName = self.buildRelationNameFromAccessorSuffix(className)
                if not relationName:
                    continue

                key = (relationName, getterName, setterName)
                if key in seen:
                    continue

                seen.add(key)

                relationRules.append({
                    "name": relationName,
                    "getterName": getterName,
                    "setterName": setterName,
                    "targetClassNames": [className],
                    "targetItemClassNames": [],
                    "source": "input_candidates",
                })

        return relationRules

    def buildRelationRuleFromPersistedRelation(
            self,
            persistedRelation: Dict[str, Any],
    ) -> Dict[str, Any]:
        metadata = persistedRelation.get("metadata") or {}
        relationName = persistedRelation.get("relationName")

        getterName = (
                metadata.get("getterName")
                or persistedRelation.get("getterName")
        )
        setterName = (
                metadata.get("setterName")
                or persistedRelation.get("setterName")
        )

        if not getterName or not setterName:
            getterName, setterName = self.buildAccessorNamesFromRelationName(
                relationName,
            )

        return {
            "name": relationName,
            "getterName": getterName,
            "setterName": setterName,
            "source": "scipion_object_relations",
        }

    def buildRelatedOutputCandidateFromPersistedRelation(
            self,
            mapper,
            projectId: int,
            persistedRelation: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        targetProtocolDbId = persistedRelation.get("targetProtocolDbId")
        targetProtocolId = persistedRelation.get("targetProtocolId")
        targetOutputName = str(persistedRelation.get("targetOutputName") or "").strip()

        if targetProtocolDbId in (None, "") or not targetOutputName:
            return None

        outputInfo = self.protocolGraphRepository.getPostgresqlRuntimeOutputInfo(
            mapper=mapper,
            projectId=projectId,
            parentProtocolDbId=int(targetProtocolDbId),
            outputName=targetOutputName,
        )

        if not outputInfo.get("exists"):
            return None

        return {
            "ref": persistedRelation,
            "outputInfo": outputInfo,
            "sameParent": False,
            "parentProtocolId": targetProtocolId,
            "parentProtocolDbId": targetProtocolDbId,
            "outputName": targetOutputName,
            "source": "scipion_object_relations",
        }

    def findRelatedOutputCandidates(
            self,
            mapper,
            projectId: int,
            inputRefRows: List[Dict[str, Any]],
            currentInputName: str,
            preferredParentProtocolDbId: int,
            relationRule: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        candidates = []

        for ref in inputRefRows or []:
            candidateInputName = str(ref.get("inputName") or "").strip()
            candidateOutputName = str(ref.get("parentOutputName") or "").strip()
            candidateParentProtocolDbId = ref.get("parentProtocolDbId")
            candidateParentProtocolId = ref.get("parentProtocolId")

            if not candidateInputName or not candidateOutputName:
                continue

            if candidateInputName == currentInputName:
                continue

            if candidateParentProtocolDbId in (None, ""):
                continue

            try:
                outputInfo = self.protocolGraphRepository.getPostgresqlRuntimeOutputInfo(
                    mapper=mapper,
                    projectId=projectId,
                    parentProtocolDbId=int(candidateParentProtocolDbId),
                    outputName=candidateOutputName,
                )
            except Exception:
                logger.debug(
                    "Could not inspect input ref while repairing runtime output relation. "
                    "projectId=%s inputName=%s parentProtocolDbId=%s outputName=%s",
                    projectId,
                    candidateInputName,
                    candidateParentProtocolDbId,
                    candidateOutputName,
                    exc_info=True,
                )
                continue

            if not outputInfo.get("exists"):
                continue

            if not self.outputInfoMatchesRule(outputInfo, relationRule):
                continue

            try:
                sameParent = int(candidateParentProtocolDbId) == int(preferredParentProtocolDbId)
            except Exception:
                sameParent = False

            candidates.append({
                "ref": ref,
                "outputInfo": outputInfo,
                "sameParent": sameParent,
                "parentProtocolId": candidateParentProtocolId,
                "parentProtocolDbId": candidateParentProtocolDbId,
                "outputName": candidateOutputName,
            })

        candidates.sort(key=lambda item: 0 if item.get("sameParent") else 1)

        return candidates

    def repairPersistedOutputRelations(
            self,
            mapper,
            projectId: int,
            parentProtocol,
            parentProtocolDbId: int,
            parentScipionProtocolId,
            outputName: str,
            outputObj,
            inputRefRows: List[Dict[str, Any]],
            currentInputName: str,
            getParentProtocolCallback: Callable,
            repairOutputMapperCallback: Optional[Callable] = None,
            storeProtocolCallback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        lastReport = {
            "checked": False,
            "repaired": False,
            "reason": "no_persisted_runtime_output_relation",
            "outputName": outputName,
            "relationSource": "scipion_object_relations",
        }

        persistedRelations = self.protocolGraphRepository.loadRuntimeOutputRelations(
            mapper=mapper,
            projectId=projectId,
            sourceProtocolDbId=int(parentProtocolDbId),
            sourceOutputName=outputName,
        )

        for persistedRelation in persistedRelations or []:
            relationRule = self.buildRelationRuleFromPersistedRelation(
                persistedRelation,
            )

            relatedOutputCandidate = self.buildRelatedOutputCandidateFromPersistedRelation(
                mapper=mapper,
                projectId=projectId,
                persistedRelation=persistedRelation,
            )

            if relatedOutputCandidate is None:
                lastReport = {
                    "checked": False,
                    "repaired": False,
                    "reason": "persisted_related_output_not_available",
                    "outputName": outputName,
                    "relationName": persistedRelation.get("relationName"),
                    "relationId": persistedRelation.get("relationId"),
                    "relationSource": "scipion_object_relations",
                }
                continue

            report = self.repairMissingOutputRelation(
                mapper=mapper,
                projectId=projectId,
                parentProtocol=parentProtocol,
                parentProtocolDbId=parentProtocolDbId,
                parentScipionProtocolId=parentScipionProtocolId,
                outputName=outputName,
                outputObj=outputObj,
                inputRefRows=inputRefRows,
                currentInputName=currentInputName,
                relationRule=relationRule,
                getParentProtocolCallback=getParentProtocolCallback,
                repairOutputMapperCallback=repairOutputMapperCallback,
                storeProtocolCallback=storeProtocolCallback,
                relatedOutputCandidate=relatedOutputCandidate,
                persistRepairedRelation=True,
            )

            report["relationId"] = persistedRelation.get("relationId")
            report["relationSource"] = "scipion_object_relations"

            lastReport = report

            if report.get("checked"):
                return report

        return lastReport

    def persistResolvedRuntimeOutputRelation(
            self,
            mapper,
            projectId: int,
            sourceProtocolDbId: int,
            sourceOutputName: str,
            relationRule: Dict[str, Any],
            relatedParentProtocolDbId,
            relatedOutputName,
    ) -> Dict[str, Any]:
        relationName = str(relationRule.get("name") or "").strip()

        if not relationName:
            return {
                "saved": False,
                "reason": "missing_relation_name",
            }

        if relatedParentProtocolDbId in (None, "") or not relatedOutputName:
            return {
                "saved": False,
                "reason": "missing_related_output",
                "relationName": relationName,
                "sourceProtocolDbId": sourceProtocolDbId,
                "sourceOutputName": sourceOutputName,
                "targetProtocolDbId": relatedParentProtocolDbId,
                "targetOutputName": relatedOutputName,
            }

        metadata = {
            "source": "runtime_output_relation_repair_service",
            "repairSource": relationRule.get("source") or "default_relation_rules",
            "getterName": relationRule.get("getterName"),
            "setterName": relationRule.get("setterName"),
        }

        return self.protocolGraphRepository.replaceRuntimeOutputRelation(
            mapper=mapper,
            projectId=projectId,
            sourceProtocolDbId=int(sourceProtocolDbId),
            sourceOutputName=sourceOutputName,
            relationName=relationName,
            targetProtocolDbId=int(relatedParentProtocolDbId),
            targetOutputName=str(relatedOutputName),
            metadata=metadata,
        )

    def repairMissingOutputRelations(
            self,
            mapper,
            projectId: int,
            parentProtocol,
            parentProtocolDbId: int,
            parentScipionProtocolId,
            outputName: str,
            outputObj,
            inputRefRows: List[Dict[str, Any]],
            currentInputName: str,
            getParentProtocolCallback: Callable,
            repairOutputMapperCallback: Optional[Callable] = None,
            storeProtocolCallback: Optional[Callable] = None,
            relationRules: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        persistedRelationReport = self.repairPersistedOutputRelations(
            mapper=mapper,
            projectId=projectId,
            parentProtocol=parentProtocol,
            parentProtocolDbId=parentProtocolDbId,
            parentScipionProtocolId=parentScipionProtocolId,
            outputName=outputName,
            outputObj=outputObj,
            inputRefRows=inputRefRows,
            currentInputName=currentInputName,
            getParentProtocolCallback=getParentProtocolCallback,
            repairOutputMapperCallback=repairOutputMapperCallback,
            storeProtocolCallback=storeProtocolCallback,
        )

        if persistedRelationReport.get("checked"):
            return persistedRelationReport

        lastReport = persistedRelationReport or {
            "checked": False,
            "repaired": False,
            "reason": "no_runtime_relation_rule_matched",
            "outputName": outputName,
        }

        inferredRelationRules = self.buildRelationRulesFromInputCandidates(
            mapper=mapper,
            projectId=projectId,
            outputObj=outputObj,
            inputRefRows=inputRefRows,
            currentInputName=currentInputName,
        )

        if relationRules is None:
            relationRules = inferredRelationRules or self.defaultRelationRules

        for relationRule in relationRules or []:
            report = self.repairMissingOutputRelation(
                mapper=mapper,
                projectId=projectId,
                parentProtocol=parentProtocol,
                parentProtocolDbId=parentProtocolDbId,
                parentScipionProtocolId=parentScipionProtocolId,
                outputName=outputName,
                outputObj=outputObj,
                inputRefRows=inputRefRows,
                currentInputName=currentInputName,
                relationRule=relationRule,
                getParentProtocolCallback=getParentProtocolCallback,
                repairOutputMapperCallback=repairOutputMapperCallback,
                storeProtocolCallback=storeProtocolCallback,
            )

            lastReport = report

            if report.get("checked"):
                report.setdefault("relationSource", "default_relation_rules")
                return report

        return lastReport

    def repairMissingOutputRelation(
            self,
            mapper,
            projectId: int,
            parentProtocol,
            parentProtocolDbId: int,
            parentScipionProtocolId,
            outputName: str,
            outputObj,
            inputRefRows: List[Dict[str, Any]],
            currentInputName: str,
            relationRule: Dict[str, Any],
            getParentProtocolCallback: Callable,
            repairOutputMapperCallback: Optional[Callable] = None,
            storeProtocolCallback: Optional[Callable] = None,
            relatedOutputCandidate: Optional[Dict[str, Any]] = None,
            persistRepairedRelation: bool = True,
    ) -> Dict[str, Any]:
        relationName = relationRule.get("name")
        getterName = relationRule.get("getterName")
        setterName = relationRule.get("setterName")

        report = {
            "checked": False,
            "repaired": False,
            "reason": None,
            "relationName": relationName,
            "outputName": outputName,
            "relatedOutputName": None,
            "relatedParentProtocolId": None,
            "relatedParentProtocolDbId": None,
        }

        if not getterName or not setterName:
            report["reason"] = "invalid_relation_rule"
            return report

        sourceOutputInfo = {}

        try:
            sourceOutputInfo = self.protocolGraphRepository.getPostgresqlRuntimeOutputInfo(
                mapper=mapper,
                projectId=projectId,
                parentProtocolDbId=int(parentProtocolDbId),
                outputName=outputName,
            )
        except Exception:
            sourceOutputInfo = {}

        if outputObj is None or self.isPostgresqlProxy(outputObj):
            try:
                parentScipionProtocolId, parentProtocol = getParentProtocolCallback(
                    mapper=mapper,
                    projectId=projectId,
                    parentId=parentScipionProtocolId,
                )
                outputObj = getattr(parentProtocol, outputName, None)
            except Exception as e:
                report["reason"] = "parent_protocol_not_loaded"
                report["error"] = str(e)
                return report

            fallbackOutputObj = self._loadRuntimeOutputFromFallback(
                mapper=mapper,
                outputInfo=sourceOutputInfo,
            )

            if fallbackOutputObj is not None:
                outputObj = fallbackOutputObj
                setattr(parentProtocol, outputName, outputObj)
                report["sourceOutputLoadedFromFallback"] = True
            else:
                report["reason"] = "source_runtime_output_missing"
                report["error"] = (
                    "Source output %s.%s exists in PostgreSQL but could not be "
                    "loaded as a real Scipion object from the SQLite fallback."
                    % (str(parentScipionProtocolId), outputName)
                )
                return report

        if not hasattr(outputObj, setterName) or not hasattr(outputObj, getterName):
            report["reason"] = "relation_not_supported"
            return report

        report["checked"] = True

        if repairOutputMapperCallback is not None and sourceOutputInfo.get("exists"):
            try:
                report["sourceOutputMapperRepaired"] = bool(
                    repairOutputMapperCallback(
                        mapper=mapper,
                        projectId=projectId,
                        outputObj=outputObj,
                        outputInfo=sourceOutputInfo,
                    )
                )
            except Exception as mapperRepairError:
                report["sourceOutputMapperRepaired"] = False
                report["sourceOutputMapperRepairError"] = str(mapperRepairError)

                logger.debug(
                    "Could not repair source output mapper before writing runtime relation. "
                    "projectId=%s parentProtocolId=%s parentProtocolDbId=%s "
                    "outputName=%s relationName=%s",
                    projectId,
                    parentScipionProtocolId,
                    parentProtocolDbId,
                    outputName,
                    relationName,
                    exc_info=True,
                )

        if relatedOutputCandidate is not None:
            candidates = [relatedOutputCandidate]
        else:
            candidates = self.findRelatedOutputCandidates(
                mapper=mapper,
                projectId=projectId,
                inputRefRows=inputRefRows,
                currentInputName=currentInputName,
                preferredParentProtocolDbId=parentProtocolDbId,
                relationRule=relationRule,
            )

        try:
            currentRelatedOutput = getattr(outputObj, getterName)()
        except Exception:
            currentRelatedOutput = None

        if not candidates:
            if currentRelatedOutput is not None:
                report["reason"] = "already_has_runtime_relation"
                report["runtimeRelationAlreadyPresent"] = True
            else:
                report["reason"] = "related_output_input_not_found"

            return report

        candidate = candidates[0]

        relatedParentProtocolId = candidate.get("parentProtocolId")
        relatedParentProtocolDbId = candidate.get("parentProtocolDbId")
        relatedOutputName = candidate.get("outputName")
        relatedOutputInfo = candidate.get("outputInfo") or {}

        report["relatedOutputName"] = relatedOutputName
        report["relatedParentProtocolId"] = (
            str(relatedParentProtocolId)
            if relatedParentProtocolId not in (None, "")
            else None
        )
        report["relatedParentProtocolDbId"] = (
            int(relatedParentProtocolDbId)
            if relatedParentProtocolDbId not in (None, "")
            else None
        )

        try:
            if int(relatedParentProtocolDbId) == int(parentProtocolDbId):
                relatedParentProtocol = parentProtocol
            else:
                _relatedScipionProtocolId, relatedParentProtocol = getParentProtocolCallback(
                    mapper=mapper,
                    projectId=projectId,
                    parentId=relatedParentProtocolId,
                )
        except Exception as e:
            report["reason"] = "related_parent_protocol_not_loaded"
            report["error"] = str(e)
            return report

        try:
            relatedOutputObj = getattr(relatedParentProtocol, relatedOutputName, None)
        except Exception:
            relatedOutputObj = None

        if relatedOutputObj is None:
            try:
                _relatedScipionProtocolId, freshRelatedParentProtocol = getParentProtocolCallback(
                    mapper=mapper,
                    projectId=projectId,
                    parentId=relatedParentProtocolId,
                )
                relatedParentProtocol = freshRelatedParentProtocol
                relatedOutputObj = getattr(freshRelatedParentProtocol, relatedOutputName, None)
            except Exception as e:
                report["reason"] = "related_output_object_not_loaded"
                report["error"] = str(e)
                return report

        if relatedOutputObj is None or self.isPostgresqlProxy(relatedOutputObj):
            fallbackRelatedOutputObj = self._loadRuntimeOutputFromFallback(
                mapper=mapper,
                outputInfo=relatedOutputInfo,
            )

            if fallbackRelatedOutputObj is not None:
                relatedOutputObj = fallbackRelatedOutputObj
                setattr(relatedParentProtocol, relatedOutputName, relatedOutputObj)
                report["relatedOutputLoadedFromFallback"] = True
            else:
                report["reason"] = "related_runtime_output_missing"
                report["error"] = (
                        "Related output %s.%s exists in PostgreSQL but could not be "
                        "loaded as a real Scipion object from the SQLite fallback."
                        % (str(relatedParentProtocolId), relatedOutputName)
                )
                return report

        if repairOutputMapperCallback is not None:
            try:
                repairOutputMapperCallback(
                    mapper=mapper,
                    projectId=projectId,
                    outputObj=relatedOutputObj,
                    outputInfo=relatedOutputInfo,
                )
            except Exception:
                logger.debug(
                    "Could not repair related output mapper before linking runtime relation. "
                    "projectId=%s relatedParentProtocolId=%s relatedOutputName=%s",
                    projectId,
                    relatedParentProtocolId,
                    relatedOutputName,
                    exc_info=True,
                )

        try:
            getattr(outputObj, setterName)(relatedOutputObj)

            writeMethod = getattr(outputObj, "write", None)

            if callable(writeMethod):
                try:
                    writeMethod(properties=True)
                    report["relationPropertiesWritten"] = True
                except TypeError:
                    writeMethod()
                    report["relationPropertiesWritten"] = True
                except Exception as writeError:
                    report["relationPropertiesWritten"] = False
                    report["relationPropertiesWriteError"] = str(writeError)

                    logger.debug(
                        "Could not write runtime output relation properties. "
                        "The canonical PostgreSQL relation will still be persisted. "
                        "projectId=%s parentProtocolId=%s parentProtocolDbId=%s "
                        "outputName=%s relationName=%s relatedOutputName=%s",
                        projectId,
                        parentScipionProtocolId,
                        parentProtocolDbId,
                        outputName,
                        relationName,
                        relatedOutputName,
                        exc_info=True,
                    )
            else:
                report["relationPropertiesWritten"] = False
                report["relationPropertiesWriteSkipped"] = "output_has_no_write_method"

            if storeProtocolCallback is not None:
                storeProtocolCallback(parentProtocol)

            report["repaired"] = True
            report["reason"] = "linked_runtime_output_relation"

            if persistRepairedRelation:
                try:
                    persistReport = self.persistResolvedRuntimeOutputRelation(
                        mapper=mapper,
                        projectId=projectId,
                        sourceProtocolDbId=parentProtocolDbId,
                        sourceOutputName=outputName,
                        relationRule=relationRule,
                        relatedParentProtocolDbId=relatedParentProtocolDbId,
                        relatedOutputName=relatedOutputName,
                    )

                    report["persistedRuntimeOutputRelation"] = persistReport

                    if persistReport.get("saved"):
                        report["relationSource"] = "%s_persisted" % (
                                relationRule.get("source") or "default_relation_rules"
                        )

                except Exception as persistError:
                    report["persistedRuntimeOutputRelation"] = {
                        "saved": False,
                        "reason": "persist_failed",
                        "error": str(persistError),
                    }

                    logger.debug(
                        "Could not persist repaired runtime output relation. "
                        "projectId=%s parentProtocolId=%s parentProtocolDbId=%s "
                        "outputName=%s relationName=%s relatedParentProtocolDbId=%s "
                        "relatedOutputName=%s",
                        projectId,
                        parentScipionProtocolId,
                        parentProtocolDbId,
                        outputName,
                        relationName,
                        relatedParentProtocolDbId,
                        relatedOutputName,
                        exc_info=True,
                    )

            logger.info(
                "Repaired PostgreSQL runtime output relation. "
                "projectId=%s parentProtocolId=%s parentProtocolDbId=%s "
                "outputName=%s relationName=%s relatedParentProtocolId=%s "
                "relatedParentProtocolDbId=%s relatedOutputName=%s",
                projectId,
                parentScipionProtocolId,
                parentProtocolDbId,
                outputName,
                relationName,
                relatedParentProtocolId,
                relatedParentProtocolDbId,
                relatedOutputName,
            )

        except Exception as e:
            logger.exception(
                "Failed to repair PostgreSQL runtime output relation. "
                "projectId=%s parentProtocolId=%s parentProtocolDbId=%s "
                "outputName=%s relationName=%s relatedOutputName=%s",
                projectId,
                parentScipionProtocolId,
                parentProtocolDbId,
                outputName,
                relationName,
                relatedOutputName,
            )
            report["reason"] = "repair_failed"
            report["error"] = str(e)

        return report