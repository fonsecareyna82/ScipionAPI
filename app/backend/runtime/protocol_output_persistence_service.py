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
import shutil
from typing import Any, Callable, Dict, List, Optional, Union

from pyworkflow.object import (
    Object as ScipionObject,
    Pointer,
    Set as ScipionSet,
)

from app.backend.runtime.protocol_identity import ProtocolIdentityResolver

logger = logging.getLogger(__name__)


class RuntimeProtocolOutputPersistenceService:
    """Persist and cleanup PostgreSQL runtime protocol outputs."""

    @staticmethod
    def safeCall(obj: Any, methodName: str, default: Any = None) -> Any:
        try:
            method = getattr(obj, methodName, None)
            if method is None:
                return default
            return method()
        except Exception:
            return default

    def getScipionObjectId(self, obj: Any) -> Optional[Any]:
        return self.safeCall(obj, "getObjId", None)

    def getScipionClassName(self, obj: Any) -> Optional[str]:
        if obj is None:
            return None

        className = self.safeCall(obj, "getClassName", None)
        if className:
            return str(className)

        return obj.__class__.__name__

    def isPersistableNonSetOutput(self, outputObj: Any) -> bool:
        if outputObj is None:
            return False

        if self.isScipionSetLikeOutput(outputObj):
            return False

        try:
            if isinstance(outputObj, Pointer):
                return False
        except Exception:
            pass

        try:
            if isinstance(outputObj, ScipionObject):
                return True
        except Exception:
            pass

        return False

    def isScipionSetLikeOutput(self, outputObj: Any) -> bool:
        if outputObj is None:
            return False

        try:
            if isinstance(outputObj, ScipionSet):
                return True
        except Exception:
            pass

        className = self.getScipionClassName(outputObj) or outputObj.__class__.__name__
        classNameText = str(className or "")

        if classNameText.startswith("SetOf") or "SetOf" in classNameText:
            return True

        return (
                callable(getattr(outputObj, "iterItems", None))
                and callable(getattr(outputObj, "getSize", None))
                and callable(getattr(outputObj, "getFileName", None))
        )

    def shouldRegisterProtocolOutputs(self, protocol: Any) -> bool:
        """
        Return True when the protocol already exposes at least one persistable output.

        Do not depend on protocol status here:
          - streaming protocols can expose outputs while running
          - finished protocols should also register outputs
          - new/launched protocols without outputs will naturally return False
        """
        try:
            outputs = list(protocol.iterOutputAttributes())
        except Exception:
            return False

        if not outputs:
            return False

        for outputItem in outputs:
            if isinstance(outputItem, (tuple, list)) and len(outputItem) >= 2:
                outputObj = outputItem[1]
            else:
                outputObj = outputItem

            if outputObj is None:
                continue

            try:
                if self.isScipionSetLikeOutput(outputObj):
                    return True
            except Exception:
                pass

            try:
                if self.isPersistableNonSetOutput(outputObj):
                    return True
            except Exception:
                pass

        return False

    def countRuntimeOutputKinds(self, outputs: List[Dict[str, Any]]) -> Dict[str, int]:
        result: Dict[str, int] = {}

        for item in outputs or []:
            mapperKind = str(item.get("mapperKind") or "unknown")
            result[mapperKind] = result.get(mapperKind, 0) + 1

        return result

    def buildMissingOutputSyncItems(
            self,
            protocolId,
            declaredOutputs: List[Dict[str, Any]],
            persistedOutputs: List[Dict[str, Any]],
            skippedOutputs: List[Dict[str, Any]],
            outputErrors: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        persistedOutputNames = {
            item.get("outputName")
            for item in persistedOutputs or []
            if item.get("outputName")
        }

        result = []

        for skippedOutput in skippedOutputs or []:
            result.append({
                "protocolId": str(protocolId),
                "outputName": skippedOutput.get("outputName"),
                "outputClassName": skippedOutput.get("outputClassName"),
                "reason": skippedOutput.get("reason") or "skipped",
            })

        for outputError in outputErrors or []:
            item = {
                "protocolId": str(protocolId),
                "outputName": outputError.get("outputName"),
                "outputClassName": outputError.get("outputClassName"),
                "reason": "persistence_error",
            }

            if outputError.get("error") is not None:
                item["error"] = outputError.get("error")

            result.append(item)

        knownMissingNames = {
            item.get("outputName")
            for item in result
            if item.get("outputName")
        }

        for declaredOutput in declaredOutputs or []:
            outputName = declaredOutput.get("outputName")

            if not outputName:
                continue

            if outputName in persistedOutputNames:
                continue

            if outputName in knownMissingNames:
                continue

            result.append({
                "protocolId": str(protocolId),
                "outputName": outputName,
                "outputClassName": declaredOutput.get("outputClassName"),
                "reason": "not_persisted",
            })

        return result

    def resolveProtocolDbIdForOutputPersistence(
            self,
            mapper,
            projectId: int,
            protocol,
    ) -> Optional[int]:
        protocolId = self.getScipionObjectId(protocol)

        if protocolId in (None, ""):
            return None

        protocolIdentityResolver = ProtocolIdentityResolver(
            mapper=mapper,
            projectId=projectId,
        )

        return protocolIdentityResolver.resolvePostgresqlProtocolDbId(protocolId)

    def storeGeneratedSetInPostgresql(
            self,
            mapper,
            projectId: Optional[int],
            protocolId: Union[int, str],
            outputName: str,
            scipionSet,
            contextLabel: str,
    ) -> Dict[str, Any]:
        postgresqlSync = None
        postgresqlError = None

        if mapper is None:
            return {
                "postgresqlSync": postgresqlSync,
                "postgresqlError": postgresqlError,
            }

        try:
            from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper

            protocolIdentityResolver = ProtocolIdentityResolver(
                mapper=mapper,
                projectId=projectId,
            )

            protocolDbId = (
                    protocolIdentityResolver.resolvePostgresqlProtocolDbId(protocolId)
                    or protocolId
            )

            setMapper = ScipionSetPostgresqlMapper(mapper.db)
            postgresqlSync = setMapper.storeSet(
                projectId=projectId,
                protocolDbId=protocolDbId,
                outputName=outputName,
                scipionSet=scipionSet,
            )

        except Exception as e:
            postgresqlError = str(e)
            logger.exception(
                "Failed to persist generated %s output to PostgreSQL. projectId=%s protocolId=%s outputName=%s",
                contextLabel,
                projectId,
                protocolId,
                outputName,
            )

        return {
            "postgresqlSync": postgresqlSync,
            "postgresqlError": postgresqlError,
        }

    def registerOutput(
            self,
            projectId: int,
            protocol: Any,
            mapper,
            returnReport: bool = False,
    ) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        from app.backend.mapper import (
            ScipionObjectPostgresqlMapper,
            ScipionSetPostgresqlMapper,
        )

        declaredOutputs: List[Dict[str, Any]] = []
        persistedOutputs: List[Dict[str, Any]] = []
        skippedOutputs: List[Dict[str, Any]] = []
        outputErrors: List[Dict[str, Any]] = []

        protocolId = self.getScipionObjectId(protocol)
        protocolDbId = self.resolveProtocolDbIdForOutputPersistence(
            mapper=mapper,
            projectId=projectId,
            protocol=protocol,
        )

        if protocolDbId is None:
            raise ValueError(f"Protocol not found in PostgreSQL: {protocolId}")

        try:
            outputAttributes = list(protocol.iterOutputAttributes())
        except Exception as exc:
            logger.exception(
                "Could not iterate protocol outputs. projectId=%s protocolId=%s",
                projectId,
                protocolId,
            )
            outputErrors.append({
                "outputName": None,
                "outputClassName": None,
                "error": str(exc),
            })

            report = {
                "declared": declaredOutputs,
                "persisted": persistedOutputs,
                "skipped": skippedOutputs,
                "errors": outputErrors,
            }
            return report if returnReport else persistedOutputs

        setMapper = ScipionSetPostgresqlMapper(mapper.db)
        objectMapper = ScipionObjectPostgresqlMapper(mapper.db)

        for outputItem in outputAttributes:
            outputName = None
            outputObj = None

            if isinstance(outputItem, (tuple, list)) and len(outputItem) >= 2:
                outputName = outputItem[0]
                outputObj = outputItem[1]
            else:
                outputName = self.safeCall(outputItem, "getName", None)
                outputObj = outputItem

            outputName = str(outputName or "").strip()
            outputClassName = self.getScipionClassName(outputObj) or ""

            if not outputName:
                skippedOutputs.append({
                    "outputName": outputName,
                    "outputClassName": outputClassName,
                    "reason": "empty_output_name",
                })
                continue

            declaredOutputs.append({
                "outputName": outputName,
                "outputClassName": outputClassName,
            })

            if outputObj is None:
                skippedOutputs.append({
                    "outputName": outputName,
                    "outputClassName": "",
                    "reason": "empty_output",
                })
                continue

            try:
                if self.isScipionSetLikeOutput(outputObj):
                    syncInfo = setMapper.storeSet(
                        projectId=projectId,
                        protocolDbId=int(protocolDbId),
                        outputName=outputName,
                        scipionSet=outputObj,
                    )

                    persistedOutputs.append({
                        "outputName": outputName,
                        "outputClassName": outputClassName,
                        "mapperKind": "flat_set",
                        **(syncInfo or {}),
                    })

                elif self.isPersistableNonSetOutput(outputObj):
                    try:
                        syncInfo = objectMapper.storeObjectTree(
                            projectId=projectId,
                            protocolDbId=int(protocolDbId),
                            outputName=outputName,
                            scipionObj=outputObj,
                            registerType=True,
                            includeNestedProperties=True,
                        )
                    except TypeError:
                        syncInfo = objectMapper.storeObjectTree(
                            projectId=projectId,
                            protocolDbId=int(protocolDbId),
                            outputName=outputName,
                            scipionObj=outputObj,
                            includeNestedProperties=True,
                        )

                    persistedOutputs.append({
                        "outputName": outputName,
                        "outputClassName": outputClassName,
                        "mapperKind": "tree",
                        **(syncInfo or {}),
                    })

                else:
                    skippedOutputs.append({
                        "outputName": outputName,
                        "outputClassName": outputClassName,
                        "reason": "unsupported_output_type",
                    })

            except Exception as exc:
                logger.exception(
                    "Failed to persist protocol output. projectId=%s protocolId=%s outputName=%s outputClassName=%s",
                    projectId,
                    protocolId,
                    outputName,
                    outputClassName,
                )
                outputErrors.append({
                    "outputName": outputName,
                    "outputClassName": outputClassName,
                    "error": str(exc),
                })

        report = {
            "declared": declaredOutputs,
            "persisted": persistedOutputs,
            "skipped": skippedOutputs,
            "errors": outputErrors,
        }

        return report if returnReport else persistedOutputs

    def deletePersistedProtocolOutputs(
            self,
            mapper,
            projectId: int,
            protocolId: Union[int, str],
            protocol: Any = None,
            getCurrentProjectPathCallback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        protocolIdentityResolver = ProtocolIdentityResolver(
            mapper=mapper,
            projectId=projectId,
        )

        protocolDbId = protocolIdentityResolver.resolvePostgresqlProtocolDbId(protocolId)

        if protocolDbId is None:
            return {
                "protocolDbId": None,
                "setsDeleted": 0,
                "objectsDeleted": 0,
                "filesDeleted": 0,
                "filesSkipped": [],
                "fileErrors": [],
                "skipped": True,
                "reason": "protocol_not_found",
            }

        outputFiles = self.collectPersistedProtocolOutputFiles(
            mapper=mapper,
            projectId=projectId,
            protocolDbId=protocolDbId,
        )

        fileCleanup = self.deletePersistedProtocolOutputFilesFromFilesystem(
            protocol=protocol,
            rawFileNames=outputFiles,
            getCurrentProjectPathCallback=getCurrentProjectPathCallback,
        )

        setRows = mapper.db.fetchAll(
            """
            SELECT id
              FROM scipion_sets
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
            """,
            (projectId, protocolDbId),
        )

        setIds = [
            int(row.get("id") if isinstance(row, dict) else row[0])
            for row in (setRows or [])
            if (row.get("id") if isinstance(row, dict) else row[0]) is not None
        ]

        setsDeleted = 0
        objectsDeleted = 0

        with mapper.db.transaction():
            if setIds:
                mapper.db.execute(
                    """
                    DELETE FROM scipion_set_table_items
                     WHERE "tableId" IN (
                           SELECT id
                             FROM scipion_set_tables
                            WHERE "setId" = ANY(%s)
                     )
                    """,
                    (setIds,),
                    commit=False,
                )

                mapper.db.execute(
                    """
                    DELETE FROM scipion_set_table_columns
                     WHERE "tableId" IN (
                           SELECT id
                             FROM scipion_set_tables
                            WHERE "setId" = ANY(%s)
                     )
                    """,
                    (setIds,),
                    commit=False,
                )

                mapper.db.execute(
                    """
                    DELETE FROM scipion_set_tables
                     WHERE "setId" = ANY(%s)
                    """,
                    (setIds,),
                    commit=False,
                )

                mapper.db.execute(
                    """
                    DELETE FROM scipion_set_items
                     WHERE "setId" = ANY(%s)
                    """,
                    (setIds,),
                    commit=False,
                )

                mapper.db.execute(
                    """
                    DELETE FROM scipion_set_columns
                     WHERE "setId" = ANY(%s)
                    """,
                    (setIds,),
                    commit=False,
                )

                mapper.db.execute(
                    """
                    DELETE FROM scipion_set_properties
                     WHERE "setId" = ANY(%s)
                    """,
                    (setIds,),
                    commit=False,
                )

                cur = mapper.db.execute(
                    """
                    DELETE FROM scipion_sets
                     WHERE id = ANY(%s)
                    """,
                    (setIds,),
                    commit=False,
                )
                setsDeleted = int(cur.rowcount or 0)

            cur = mapper.db.execute(
                """
                WITH RECURSIVE object_tree AS (
                    SELECT id
                      FROM scipion_objects
                     WHERE "projectId" = %s
                       AND "protocolDbId" = %s

                    UNION ALL

                    SELECT child.id
                      FROM scipion_objects child
                      JOIN object_tree parent
                        ON child."parentObjectId" = parent.id
                )
                DELETE FROM scipion_objects
                 WHERE id IN (SELECT id FROM object_tree)
                """,
                (projectId, protocolDbId),
                commit=False,
            )
            objectsDeleted = int(cur.rowcount or 0)

        return {
            "protocolDbId": protocolDbId,
            "setsDeleted": setsDeleted,
            "objectsDeleted": objectsDeleted,
            "filesDeleted": fileCleanup.get("filesDeleted", 0),
            "filesSkipped": fileCleanup.get("filesSkipped", []),
            "fileErrors": fileCleanup.get("fileErrors", []),
            "skipped": False,
        }

    def deletePersistedProtocolOutputsForRuntimeProtocols(
            self,
            mapper,
            projectId: int,
            protocols: List[Any],
            getCurrentProjectPathCallback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        cleanupItems = []
        totalSetsDeleted = 0
        totalObjectsDeleted = 0
        totalFilesDeleted = 0
        totalFileErrors = []

        for protocol in protocols or []:
            protocolId = None

            try:
                protocolId = protocol.getObjId()
            except Exception:
                protocolId = protocol

            if protocolId is None:
                continue

            cleanupInfo = self.deletePersistedProtocolOutputs(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
                protocol=protocol,
                getCurrentProjectPathCallback=getCurrentProjectPathCallback,
            )

            cleanupItems.append({
                "protocolId": str(protocolId),
                **cleanupInfo,
            })

            totalSetsDeleted += int(cleanupInfo.get("setsDeleted") or 0)
            totalObjectsDeleted += int(cleanupInfo.get("objectsDeleted") or 0)
            totalFilesDeleted += int(cleanupInfo.get("filesDeleted") or 0)
            totalFileErrors.extend(cleanupInfo.get("fileErrors") or [])

        return {
            "protocolsCount": len(cleanupItems),
            "setsDeleted": totalSetsDeleted,
            "objectsDeleted": totalObjectsDeleted,
            "filesDeleted": totalFilesDeleted,
            "fileErrors": totalFileErrors,
            "items": cleanupItems,
        }

    def collectPersistedProtocolOutputFiles(
            self,
            mapper,
            projectId: int,
            protocolDbId: int,
    ) -> List[str]:
        rows = mapper.db.fetchAll(
            """
            SELECT DISTINCT file_name
              FROM (
                    SELECT root.metadata ->> 'fileName' AS file_name
                      FROM scipion_sets s
                      LEFT JOIN scipion_objects root
                        ON root.id = s."objectId"
                     WHERE s."projectId" = %s
                       AND s."protocolDbId" = %s

                    UNION

                    SELECT o.metadata ->> 'fileName' AS file_name
                      FROM scipion_objects o
                     WHERE o."projectId" = %s
                       AND o."protocolDbId" = %s
                       AND o."parentObjectId" IS NULL
              ) files
             WHERE file_name IS NOT NULL
               AND file_name <> ''
            """,
            (
                projectId,
                protocolDbId,
                projectId,
                protocolDbId,
            ),
        )

        result = []
        seen = set()

        for row in rows or []:
            value = row.get("file_name") if isinstance(row, dict) else row[0]
            value = str(value or "").strip()

            if not value or value in seen:
                continue

            seen.add(value)
            result.append(value)

        return result

    def deletePersistedProtocolOutputFilesFromFilesystem(
            self,
            protocol: Any,
            rawFileNames: List[str],
            getCurrentProjectPathCallback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        projectPath = None

        if callable(getCurrentProjectPathCallback):
            try:
                projectPath = getCurrentProjectPathCallback()
            except Exception:
                projectPath = None

        if not projectPath:
            return {
                "filesDeleted": 0,
                "filesSkipped": [
                    {
                        "fileName": fileName,
                        "reason": "missing_project_path",
                    }
                    for fileName in (rawFileNames or [])
                ],
                "fileErrors": [],
            }

        projectPath = os.path.abspath(str(projectPath))

        workingDirPath = None
        if protocol is not None:
            try:
                workingDirPath = protocol.getWorkingDir()
            except Exception:
                workingDirPath = None

        if workingDirPath:
            workingDirPath = str(workingDirPath)
            if not os.path.isabs(workingDirPath):
                workingDirPath = os.path.join(projectPath, workingDirPath)
            workingDirPath = os.path.abspath(workingDirPath)

        allowedRoot = workingDirPath or projectPath

        filesDeleted = 0
        filesSkipped = []
        fileErrors = []

        for rawFileName in rawFileNames or []:
            resolvedPath = self.resolvePersistedOutputFileForDeletion(
                rawFileName=rawFileName,
                projectPath=projectPath,
                allowedRoot=allowedRoot,
            )

            if resolvedPath is None:
                filesSkipped.append({
                    "fileName": str(rawFileName),
                    "reason": "outside_allowed_root",
                })
                continue

            candidatePaths = [
                resolvedPath,
                resolvedPath + "-wal",
                resolvedPath + "-shm",
                resolvedPath + "-journal",
            ]

            for candidatePath in candidatePaths:
                if not os.path.exists(candidatePath):
                    continue

                try:
                    if os.path.isdir(candidatePath) and not os.path.islink(candidatePath):
                        shutil.rmtree(candidatePath)
                    else:
                        os.remove(candidatePath)

                    filesDeleted += 1

                except Exception as e:
                    logger.exception(
                        "Could not delete persisted protocol output file. path=%s",
                        candidatePath,
                    )
                    fileErrors.append({
                        "fileName": str(rawFileName),
                        "path": candidatePath,
                        "error": str(e),
                    })

        return {
            "filesDeleted": filesDeleted,
            "filesSkipped": filesSkipped,
            "fileErrors": fileErrors,
        }

    def resolvePersistedOutputFileForDeletion(
            self,
            rawFileName: str,
            projectPath: str,
            allowedRoot: str,
    ) -> Optional[str]:
        rawFileName = str(rawFileName or "").strip()

        if not rawFileName:
            return None

        if os.path.isabs(rawFileName):
            candidatePath = os.path.abspath(rawFileName)
        else:
            candidatePath = os.path.abspath(os.path.join(projectPath, rawFileName))

        allowedRoot = os.path.abspath(allowedRoot)

        try:
            commonPath = os.path.commonpath([allowedRoot, candidatePath])
        except Exception:
            return None

        if commonPath != allowedRoot:
            return None

        return candidatePath