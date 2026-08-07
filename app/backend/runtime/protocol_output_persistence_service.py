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
import json
import logging
import os
import re
import shutil
from typing import Any, Callable, Dict, List, Optional, Set, Union

from app.backend.mapper.postgresql import PostgresqlFlatMapper
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

    def _isPostgresqlRuntimeProtocolProjection(
            self,
            protocol: Any,
    ) -> bool:
        if protocol is None:
            return False

        mapper = getattr(
            protocol,
            "mapper",
            None,
        )

        if mapper is None:
            mapper = self.safeCall(
                protocol,
                "getMapper",
                None,
            )

        if mapper is None:
            return False

        marker = getattr(
            mapper,
            "isPostgresqlRuntimeMapper",
            False,
        )

        if callable(marker):
            try:
                marker = marker()
            except Exception:
                return False

        return bool(marker)

    @staticmethod
    def _isPostgresqlRuntimeSetOutput(
            outputObj: Any,
    ) -> bool:
        if outputObj is None:
            return False

        checker = getattr(
            outputObj,
            "isPostgresqlRuntimeOutput",
            None,
        )

        if not callable(checker):
            return False

        try:
            return bool(
                checker()
            )
        except Exception:
            return False

    @staticmethod
    def _isPersistedPostgresqlNativeSetOutput(
            setMapper,
            projectId: int,
            protocolDbId: int,
            outputName: str,
    ) -> bool:
        checker = getattr(
            setMapper,
            "isPostgresqlNativeSetOutput",
            None,
        )

        if not callable(checker):
            return False

        try:
            return bool(
                checker(
                    projectId=projectId,
                    protocolDbId=protocolDbId,
                    outputName=outputName,
                )
            )

        except Exception:
            logger.warning(
                "Could not identify persisted PostgreSQL "
                "native Set. projectId=%s "
                "protocolDbId=%s outputName=%s",
                projectId,
                protocolDbId,
                outputName,
                exc_info=True,
            )

            return False

    @staticmethod
    def _setScipionObjectId(
            obj: Any,
            objectId: Optional[int],
    ) -> None:
        normalizedObjectId = (
            None
            if objectId is None
            else int(objectId)
        )

        setter = getattr(
            obj,
            "setObjId",
            None,
        )

        if callable(setter):
            setter(
                normalizedObjectId
            )
            return

        obj._objId = normalizedObjectId

    @staticmethod
    def _setScipionObjectParentId(
            obj: Any,
            parentObjectId: Optional[int],
    ) -> None:
        normalizedParentObjectId = (
            None
            if parentObjectId is None
            else int(parentObjectId)
        )

        setter = getattr(
            obj,
            "setObjParentId",
            None,
        )

        if callable(setter):
            setter(
                normalizedParentObjectId
            )
            return

        obj._objParentId = (
            normalizedParentObjectId
        )

    def _prepareOutputObjectIdsForPersistence(
            self,
            mapper: PostgresqlFlatMapper,
            objectMapper,
            projectId: int,
            protocolDbId: int,
            protocolId,
            outputName: str,
            outputObj: Any,
            includeNestedProperties: bool,
    ) -> Dict[str, Any]:
        allocator = getattr(
            mapper,
            "allocateProjectObjectId",
            None,
        )

        if not callable(allocator):
            raise RuntimeError(
                "PostgreSQL mapper does not expose "
                "allocateProjectObjectId()."
            )

        storedRows = (
            objectMapper.getStoredObjectTree(
                projectId=int(projectId),
                protocolDbId=int(protocolDbId),
                outputName=str(outputName),
            )
            or []
        )

        storedIdsByPath = {}

        for row in storedRows:
            path = str(
                row.get("path")
                or ""
            ).strip()

            storedObjectId = row.get(
                "scipionObjId"
            )

            if (
                    not path
                    or storedObjectId is None
            ):
                continue

            storedIdsByPath[path] = int(
                storedObjectId
            )

        try:
            protocolRuntimeId = int(
                protocolId
            )
        except (TypeError, ValueError):
            protocolRuntimeId = None

        activeObjectIdentities = set()
        preparedItems = []
        identitySnapshot = []
        scipionObjectIdsByPath = {}

        def prepareObject(
                runtimeObject,
                path: str,
                parentRuntimeObjectId: Optional[int],
        ) -> None:
            if runtimeObject is None:
                return

            runtimeObjectIdentity = id(runtimeObject)

            if runtimeObjectIdentity in activeObjectIdentities:
                return

            activeObjectIdentities.add(runtimeObjectIdentity)

            try:
                previousObjectId = self.getScipionObjectId(runtimeObject)

                previousParentObjectId = self.safeCall(
                    runtimeObject,
                    "getObjParentId",
                    getattr(runtimeObject, "_objParentId", None),
                )

                canonicalObjectId = storedIdsByPath.get(path)
                reused = canonicalObjectId is not None

                if canonicalObjectId is None:
                    canonicalObjectId = int(allocator(int(projectId)))

                scipionObjectIdsByPath[path] = canonicalObjectId

                identitySnapshot.append({
                    "runtimeObject": runtimeObject,
                    "previousObjectId": previousObjectId,
                    "previousParentObjectId": previousParentObjectId,
                })

                self._setScipionObjectId(runtimeObject, canonicalObjectId)
                self._setScipionObjectParentId(runtimeObject, parentRuntimeObjectId)

                preparedItems.append({
                    "path": path,
                    "previousObjectId": previousObjectId,
                    "canonicalObjectId": canonicalObjectId,
                    "reused": reused,
                    "previousParentObjectId": previousParentObjectId,
                })

                if not includeNestedProperties:
                    return

                attributesReader = getattr(objectMapper, "_getAttributesToStore", None)

                if callable(attributesReader):
                    try:
                        attributes = list(attributesReader(runtimeObject) or [])
                    except Exception:
                        return
                else:
                    attributesGetter = getattr(runtimeObject, "getAttributesToStore", None)

                    if not callable(attributesGetter):
                        return

                    try:
                        attributes = list(attributesGetter() or [])
                    except Exception:
                        return

                for attributeName, childObject in attributes:
                    childPath = "%s.%s" % (path, str(attributeName))

                    prepareObject(
                        runtimeObject=childObject,
                        path=childPath,
                        parentRuntimeObjectId=canonicalObjectId,
                    )

            finally:
                activeObjectIdentities.discard(runtimeObjectIdentity)

        try:
            prepareObject(
                runtimeObject=outputObj,
                path=str(outputName),
                parentRuntimeObjectId=protocolRuntimeId,
            )

        except Exception:
            self._restoreOutputObjectIdsAfterPersistence({
                "_identitySnapshot": identitySnapshot,
            })
            raise

        return {
            "outputName": str(
                outputName
            ),
            "rootObjectId": (
                self.getScipionObjectId(
                    outputObj
                )
            ),
            "prepared": len(
                preparedItems
            ),
            "allocated": len([
                item
                for item in preparedItems
                if not item["reused"]
            ]),
            "reused": len([
                item
                for item in preparedItems
                if item["reused"]
            ]),
            "items": preparedItems,
            "_identitySnapshot": (
                identitySnapshot
            ),
            "_scipionObjectIdsByPath": dict(scipionObjectIdsByPath),
        }

    def _restoreOutputObjectIdsAfterPersistence(
            self,
            preparationReport:
            Optional[Dict[str, Any]],
    ) -> None:
        if not isinstance(
                preparationReport,
                dict,
        ):
            return

        identitySnapshot = (
            preparationReport.get(
                "_identitySnapshot"
            )
            or []
        )

        for item in reversed(
                identitySnapshot
        ):
            runtimeObject = item.get(
                "runtimeObject"
            )

            if runtimeObject is None:
                continue

            self._setScipionObjectId(
                runtimeObject,
                item.get(
                    "previousObjectId"
                ),
            )

            self._setScipionObjectParentId(
                runtimeObject,
                item.get(
                    "previousParentObjectId"
                ),
            )

    def _resolveProtocolProjectPaths(
            self,
            protocol: Any,
            projectPaths: Optional[
                List[str]
            ] = None,
    ) -> List[str]:
        result = []

        def addCandidate(value):
            if not value:
                return

            normalizedPath = os.path.abspath(
                os.path.expanduser(
                    str(value)
                )
            )

            if normalizedPath not in result:
                result.append(
                    normalizedPath
                )

        if isinstance(
                projectPaths,
                (
                        str,
                        os.PathLike,
                ),
        ):
            projectPaths = [
                str(projectPaths)
            ]

        for projectPath in (
                projectPaths or []
        ):
            addCandidate(
                projectPath
            )

        project = self.safeCall(
            protocol,
            "getProject",
            None,
        )

        if project is None:
            return result

        for attributeName in (
                "path",
                "_path",
        ):
            addCandidate(
                getattr(
                    project,
                    attributeName,
                    None,
                )
            )

        addCandidate(
            self.safeCall(
                project,
                "getPath",
                None,
            )
        )

        return result

    def _openRelativeSetMapperForPersistence(
            self,
            *,
            protocol: Any,
            scipionSet: Any,
            projectPaths: Optional[
                List[str]
            ] = None,
    ) -> bool:
        """
        Open a Scipion Set whose mapper filename is relative to the
        project root.

        The original relative _mapperPath is restored immediately, so
        PostgreSQL keeps Scipion's portable relative path rather than
        an installation-specific absolute path.

        Returns True only when this method opened the mapper.
        """
        if getattr(
                scipionSet,
                "_mapper",
                None,
        ) is not None:
            return False

        fileName = self.safeCall(
            scipionSet,
            "getFileName",
            None,
        )

        if not fileName:
            return False

        fileName = str(fileName)

        if os.path.isabs(fileName):
            absoluteFileName = os.path.abspath(
                fileName
            )

            if not os.path.isfile(
                    absoluteFileName
            ):
                raise FileNotFoundError(
                    "Scipion Set database does not exist. "
                    "absolutePath=%s"
                    % absoluteFileName
                )

            scipionSet.load()

            return True

        resolvedProjectPaths = (
            self._resolveProtocolProjectPaths(
                protocol=protocol,
                projectPaths=projectPaths,
            )
        )

        if not resolvedProjectPaths:
            raise RuntimeError(
                "Cannot resolve relative Scipion Set path "
                "without project roots. "
                "setClass=%s fileName=%s"
                % (
                    self.getScipionClassName(
                        scipionSet
                    ),
                    fileName,
                )
            )

        absoluteFileName = None
        attemptedPaths = []

        for candidateProjectPath in (
                resolvedProjectPaths
        ):
            candidateFileName = (
                os.path.abspath(
                    os.path.join(
                        candidateProjectPath,
                        fileName,
                    )
                )
            )

            attemptedPaths.append(
                candidateFileName
            )

            if os.path.isfile(
                    candidateFileName
            ):
                absoluteFileName = (
                    candidateFileName
                )

                break

        if absoluteFileName is None:
            raise FileNotFoundError(
                "Scipion Set database does not exist "
                "under any project root. "
                "relativePath=%s projectPaths=%s "
                "attemptedPaths=%s"
                % (
                    fileName,
                    resolvedProjectPaths,
                    attemptedPaths,
                )
            )

        mapperPath = getattr(
            scipionSet,
            "_mapperPath",
            None,
        )

        if (
                mapperPath is None
                or not callable(
            getattr(
                mapperPath,
                "set",
                None,
            )
        )
        ):
            raise RuntimeError(
                "Scipion Set does not expose a mutable "
                "_mapperPath. setClass=%s fileName=%s"
                % (
                    self.getScipionClassName(
                        scipionSet
                    ),
                    fileName,
                )
            )

        originalMapperPath = list(
            mapperPath
        )

        prefix = (
            originalMapperPath[1]
            if len(originalMapperPath) > 1
            else ""
        )

        try:
            mapperPath.set([
                absoluteFileName,
                prefix,
            ])

            scipionSet.load()

        except Exception:
            try:
                scipionSet.close()
            except Exception:
                logger.debug(
                    "Could not close Scipion Set mapper "
                    "after failed relative-path load. "
                    "fileName=%s absoluteFileName=%s",
                    fileName,
                    absoluteFileName,
                    exc_info=True,
                )

            raise

        finally:
            # Keep the portable Scipion path in the runtime object.
            mapperPath.set(
                originalMapperPath
            )

        logger.debug(
            "Opened relative Scipion Set mapper using project root. "
            "setClass=%s relativePath=%s absolutePath=%s",
            self.getScipionClassName(
                scipionSet
            ),
            fileName,
            absoluteFileName,
        )

        return True

    def _getCachedSetItemsCount(
            self,
            scipionSet: Any,
    ) -> Optional[int]:
        """
        Read the cached Set size without opening its SQLite mapper.
        """
        for methodName in (
                "getSize",
                "__len__",
        ):
            try:
                if methodName == "__len__":
                    value = len(
                        scipionSet
                    )
                else:
                    method = getattr(
                        scipionSet,
                        methodName,
                        None,
                    )

                    if not callable(method):
                        continue

                    value = method()

                if value in (
                        None,
                        "",
                ):
                    continue

                return int(value)

            except Exception:
                continue

        return None

    def _storeDetachedSetOutput(
            self,
            *,
            objectMapper,
            projectId: int,
            protocolDbId: int,
            outputName: str,
            outputObj: Any,
            projectPaths: Optional[
                List[str]
            ],
            artifactError: Exception,
            scipionObjectIdsByPath: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """
        Persist the metadata tree of a Set whose backing SQLite database
        is no longer available.

        The output remains addressable by protocol + output name and by
        its original Scipion object id, but its items cannot be migrated.
        """
        sourceFileName = self.safeCall(
            outputObj,
            "getFileName",
            None,
        )

        cachedItemsCount = (
            self._getCachedSetItemsCount(
                outputObj
            )
        )

        objectMapper.registerObjectTypeFromObject(
            outputObj,
            mapperKind="tree",
            includeProperties=True,
            includeNestedProperties=True,
            classSchema={
                "storage": "detached_set",
                "artifactMissing": True,
            },
        )

        syncInfo = objectMapper.storeObjectTree(
            projectId=projectId,
            protocolDbId=protocolDbId,
            outputName=outputName,
            scipionObj=outputObj,
            registerType=False,
            includeNestedProperties=True,
            scipionObjectIdsByPath=scipionObjectIdsByPath or {},
        )

        rootObjectId = syncInfo.get(
            "rootObjectId"
        )

        detachedMetadata = {
            "mapperKind": "detached_set",
            "storage": "object_tree",
            "artifactMissing": True,
            "artifactFileName": (
                str(sourceFileName)
                if sourceFileName
                else None
            ),
            "artifactError": str(
                artifactError
            ),
            "projectPathsChecked": list(
                projectPaths or []
            ),
            "itemsCount": (
                cachedItemsCount
            ),
        }

        if rootObjectId not in (None, ""):
            objectMapper.mergeStoredObjectMetadata(
                projectId=projectId,
                protocolDbId=protocolDbId,
                objectDbId=rootObjectId,
                metadata=detachedMetadata,
            )

        return {
            **syncInfo,
            "artifactMissing": True,
            "artifactFileName": (
                str(sourceFileName)
                if sourceFileName
                else None
            ),
            "itemsCount": cachedItemsCount,
            "projectPathsChecked": list(
                projectPaths or []
            ),
        }

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

    def shouldReconcileMissingProtocolOutputs(
            self,
            protocol: Any,
    ) -> bool:
        """
        Return True when the protocol output list can be treated as its final
        snapshot.

        Running and streaming protocols may expose only a partial list of
        outputs, so missing outputs must never be removed while they are active.
        """
        if (
                self
                ._isPostgresqlRuntimeProtocolProjection(
                    protocol
                )
        ):
            return False

        for methodName in (
                "isFinished",
                "isFailed",
                "isAborted",
        ):
            method = getattr(
                protocol,
                methodName,
                None,
            )

            if not callable(method):
                continue

            try:
                if bool(method()):
                    return True
            except Exception:
                pass

        statusValue = self.safeCall(
            protocol,
            "getStatus",
            None,
        )

        statusText = str(
            statusValue or ""
        ).strip().lower()

        return statusText in {
            "finished",
            "failed",
            "aborted",
            "interactive",
        }

    def shouldSyncProtocolOutputs(
            self,
            protocol: Any,
    ) -> bool:
        """
        Return True when outputs must either be persisted or reconciled.
        """
        return (
            self.shouldRegisterProtocolOutputs(
                protocol
            )
            or self.shouldReconcileMissingProtocolOutputs(
                protocol
            )
        )

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

    def _firstPersistedValue(
            self,
            sources: List[Optional[Dict[str, Any]]],
            keys: List[str],
    ) -> Any:
        for source in sources:
            if not isinstance(source, dict):
                continue

            for key in keys:
                if key in source:
                    value = source.get(key)
                    if value not in (None, "", []):
                        return value

            lowerSource = {
                str(k).lower(): v
                for k, v in source.items()
            }

            for key in keys:
                value = lowerSource.get(str(key).lower())
                if value not in (None, "", []):
                    return value

        return None

    def _toPersistedOutputInt(self, value: Any) -> Optional[int]:
        if value in (None, ""):
            return None

        try:
            return int(value)
        except Exception:
            pass

        try:
            return int(float(str(value).strip()))
        except Exception:
            return None

    def _toPersistedOutputFloat(self, value: Any) -> Optional[float]:
        if value in (None, ""):
            return None

        if isinstance(value, (list, tuple)) and value:
            value = value[0]

        try:
            return float(value)
        except Exception:
            pass

        text = str(value).strip()
        if not text:
            return None

        match = re.search(r"-?\d+(?:\.\d+)?", text)
        if not match:
            return None

        try:
            return float(match.group(0))
        except Exception:
            return None

    def _normalizePersistedOutputDims(self, value: Any) -> List[int]:
        if value in (None, ""):
            return []

        rawValues: List[Any] = []

        if isinstance(value, dict):
            for key in ("dims", "dim", "dimensions", "value"):
                candidate = value.get(key)
                if candidate not in (None, "", []):
                    return self._normalizePersistedOutputDims(candidate)

            for keys in (
                    ("x", "y", "z"),
                    ("width", "height", "depth"),
                    ("xDim", "yDim", "zDim"),
                    ("_xDim", "_yDim", "_zDim"),
            ):
                rawValues = [value.get(k) for k in keys if value.get(k) not in (None, "")]
                if rawValues:
                    break

        elif isinstance(value, (list, tuple)):
            rawValues = list(value)

        else:
            text = str(value).strip()
            if not text:
                return []

            # Handles "140x140", "140,140", "140 140", "[140, 140]".
            text = text.strip("[]()")
            rawValues = [
                part
                for part in re.split(r"[xX,;:\s]+", text)
                if part
            ]

        dims: List[int] = []
        for raw in rawValues[:3]:
            dim = self._toPersistedOutputInt(raw)
            if dim is not None and dim > 0:
                dims.append(dim)

        return dims

    def _normalizePersistedOutputClassText(
            self,
            *values: Any,
    ) -> str:
        return (
            " ".join(str(value or "") for value in values)
            .replace("_", "")
            .replace("-", "")
            .replace(".", "")
            .replace(" ", "")
            .lower()
        )

    def _resolvePersistedOutputDims(
            self,
            persistedOutput: Dict[str, Any],
            properties: Optional[Dict[str, Any]] = None,
    ) -> List[int]:
        properties = properties or {}
        sources = [properties, persistedOutput]

        classText = self._normalizePersistedOutputClassText(
            persistedOutput.get("className"),
            persistedOutput.get("itemClassName"),
            properties.get("className"),
            properties.get("baseClassName"),
        )

        firstDim = self._normalizePersistedOutputDims(
            self._firstPersistedValue(
                sources,
                [
                    "_firstDim",
                    "firstDim",
                    "first_dim",
                ],
            )
        )

        anglesCount = self._toPersistedOutputInt(
            self._firstPersistedValue(
                sources,
                [
                    "_anglesCount",
                    "anglesCount",
                    "angles_count",
                    "tiltAngles",
                    "tiltAnglesCount",
                    "tilt_angles_count",
                ],
            )
        )

        # Scipion displays SetOfTiltSeries as:
        #   nAngles x xDim x yDim
        # not as xDim x yDim x zDim.
        if "setoftiltseries" in classText and firstDim:
            if anglesCount is None:
                anglesCount = self._toPersistedOutputInt(
                    self._firstPersistedValue(
                        sources,
                        [
                            "itemsCount",
                            "itemsTableCount",
                            "rootTableItemsCount",
                            "size",
                            "count",
                            "_size",
                        ],
                    )
                )

            if anglesCount is not None and anglesCount > 0 and len(firstDim) >= 2:
                return [anglesCount, firstDim[0], firstDim[1]]

            return firstDim[:3]

        dimValue = self._firstPersistedValue(
            sources,
            [
                "dimensions",
                "dimension",
                "dims",
                "dim",
                "_dim",
                "_firstDim",
                "firstDim",
                "first_dim",
                "boxSize",
                "box_size",
                "_boxSize",
                "imageSize",
                "image_size",
                "xDim",
                "yDim",
                "zDim",
                "_xDim",
                "_yDim",
                "_zDim",
                "width",
                "height",
                "depth",
            ],
        )

        dims = self._normalizePersistedOutputDims(dimValue)
        if dims:
            return dims

        xDim = self._toPersistedOutputInt(
            self._firstPersistedValue(
                sources,
                ["xDim", "_xDim", "xdim", "_xdim", "width", "_width"],
            )
        )
        yDim = self._toPersistedOutputInt(
            self._firstPersistedValue(
                sources,
                ["yDim", "_yDim", "ydim", "_ydim", "height", "_height"],
            )
        )
        zDim = self._toPersistedOutputInt(
            self._firstPersistedValue(
                sources,
                ["zDim", "_zDim", "zdim", "_zdim", "depth", "_depth"],
            )
        )

        dims = [d for d in (xDim, yDim, zDim) if d is not None and d > 0]
        if dims:
            return dims

        # Useful for Coordinate3D-like outputs where tomograms are stored as linked metadata.
        linkedTomograms = self._firstPersistedValue(
            sources,
            ["linkedTomograms", "linked_tomograms", "tomograms"],
        )

        if isinstance(linkedTomograms, list):
            for item in linkedTomograms:
                if not isinstance(item, dict):
                    continue

                dims = self._normalizePersistedOutputDims(
                    self._firstPersistedValue(
                        [item],
                        [
                            "dimensions",
                            "dims",
                            "dim",
                            "_firstDim",
                            "firstDim",
                            "xDim",
                            "yDim",
                            "zDim",
                            "width",
                            "height",
                            "depth",
                        ],
                    )
                )

                if dims:
                    return dims

        return []

    def _formatPersistedOutputDims(self, dims: List[int]) -> str:
        if not dims:
            return ""

        if len(dims) == 1:
            return f"{dims[0]}x{dims[0]}"

        if len(dims) >= 3 and dims[2] > 1:
            return f"{dims[0]}x{dims[1]}x{dims[2]}"

        return f"{dims[0]}x{dims[1]}"

    def _toPersistedOutputBool(self, value: Any) -> Optional[bool]:
        if value is None or value == "":
            return None

        if isinstance(value, bool):
            return value

        if isinstance(value, (int, float)):
            return bool(value)

        text = str(value).strip().lower()
        if text in ("true", "1", "yes", "y"):
            return True
        if text in ("false", "0", "no", "n"):
            return False

        return None

    def _buildPersistedTomoDisplayFlags(
            self,
            persistedOutput: Dict[str, Any],
            properties: Dict[str, Any],
    ) -> List[str]:
        sources = [properties or {}, persistedOutput or {}]

        classText = self._normalizePersistedOutputClassText(
            persistedOutput.get("className"),
            persistedOutput.get("itemClassName"),
            properties.get("className"),
            properties.get("baseClassName"),
        )

        isTomoLike = (
                "tiltseries" in classText
                or "tomogram" in classText
                or "ctftomo" in classText
        )

        if not isTomoLike:
            return []

        def firstBool(*names):
            value = self._firstPersistedValue(sources, list(names))
            return self._toPersistedOutputBool(value)

        flags: List[str] = []

        isHeterogeneousSet = firstBool(
            "isHeterogeneousSet",
            "heterogeneous",
            "_isHeterogeneousSet",
        )
        if isHeterogeneousSet:
            flags.append("+het")

        hasAlignment = firstBool(
            "hasAlignment",
            "_hasAlignment",
            "alignment",
            "aligned",
        )
        if hasAlignment:
            flags.append("+ali")

        interpolated = firstBool(
            "interpolated",
            "_interpolated",
            "isInterpolated",
        )
        if interpolated:
            flags.append("! interp")

        ctfCorrected = firstBool(
            "ctfCorrected",
            "_ctfCorrected",
            "ctf",
            "ctfCorrectedFlag",
        )
        if ctfCorrected:
            flags.append("+ctf")

        hasOddEven = firstBool(
            "hasOddEven",
            "_hasOddEven",
            "oddEven",
            "hasOddEvenAssociated",
        )
        if hasOddEven:
            flags.append("+oe")

        return flags

    def _formatPersistedOutputClassName(
            self,
            className: Any,
            itemClassName: Any = None,
            outputName: Any = None,
    ) -> str:
        classText = str(className or "").strip()
        itemClassText = str(itemClassName or "").strip()
        outputText = str(outputName or "").strip()

        if classText:
            # Keep this one as Scipion normally shows it this way.
            if classText.startswith("SetOfClasses"):
                return classText

            # SetOfParticles -> Particles, SetOfMovies -> Movies, etc.
            if classText.startswith("SetOf") and len(classText) > len("SetOf"):
                return classText[len("SetOf"):]

            return classText

        if itemClassText:
            return itemClassText

        return outputText or "Output"

    def _buildPersistedOutputInfo(
            self,
            outputName: str,
            persistedOutput: Dict[str, Any],
            properties: Optional[Dict[str, Any]] = None,
    ) -> str:
        properties = properties or {}

        displayClass = self._formatPersistedOutputClassName(
            persistedOutput.get("className") or properties.get("className"),
            persistedOutput.get("itemClassName"),
            outputName,
        )

        itemsCount = self._toPersistedOutputInt(
            self._firstPersistedValue(
                [persistedOutput, properties],
                [
                    "itemsCount",
                    "itemsTableCount",
                    "rootTableItemsCount",
                    "size",
                    "count",
                    "_size",
                ],
            )
        )

        dims = self._resolvePersistedOutputDims(
            persistedOutput=persistedOutput,
            properties=properties,
        )

        samplingRate = self._toPersistedOutputFloat(
            self._firstPersistedValue(
                [properties, persistedOutput],
                [
                    "samplingRate",
                    "_samplingRate",
                    "sampling_rate",
                    "sampling",
                    "_sampling",
                    "pixelSize",
                    "pixel_size",
                    "voxelSize",
                    "voxel_size",
                ],
            )
        )

        details: List[str] = []

        if itemsCount is not None:
            details.append(f"{itemsCount} {'item' if itemsCount == 1 else 'items'}")

        dimsText = self._formatPersistedOutputDims(dims)
        if dimsText:
            details.append(dimsText)

        details.extend(
            self._buildPersistedTomoDisplayFlags(
                persistedOutput=persistedOutput,
                properties=properties,
            )
        )

        if samplingRate is not None and samplingRate > 0:
            details.append(f"{samplingRate:.2f} Å/px")

        if details:
            return f"{displayClass} ({', '.join(details)})"

        return displayClass

    def loadPersistedProtocolOutputs(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
            protocolId,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Load the PostgreSQL output summaries for one protocol.

        This is a read-only path intended for the protocol form.
        It does not reconstruct objects, register outputs or
        reconcile persisted snapshots.
        """
        protocolIdentityResolver = (
            ProtocolIdentityResolver(
                mapper=mapper,
                projectId=projectId,
            )
        )

        protocolDbId = (
            protocolIdentityResolver
            .resolvePostgresqlProtocolDbId(
                protocolId
            )
        )

        if protocolDbId is None:
            return {}

        result: Dict[
            str,
            Dict[str, Any],
        ] = {}

        from app.backend.mapper import (
            ScipionObjectPostgresqlMapper,
            ScipionSetPostgresqlMapper,
        )

        setMapper = ScipionSetPostgresqlMapper(mapper.db)
        objectMapper = ScipionObjectPostgresqlMapper(mapper.db)

        setRows = setMapper.listProtocolSetOutputRows(
            projectId=projectId,
            protocolDbId=int(protocolDbId),
        )

        for row in setRows:
            outputName = str(
                row.get("outputName")
                or ""
            ).strip()

            if not outputName:
                continue

            properties = (
                row.get("properties")
                or {}
            )

            if isinstance(
                    properties,
                    str,
            ):
                try:
                    properties = json.loads(
                        properties
                    )
                except Exception:
                    properties = {}

            if not isinstance(
                    properties,
                    dict,
            ):
                properties = {}

            persistedOutput = {
                "className": (
                    row.get("setClassName")
                ),
                "itemClassName": (
                    row.get("itemClassName")
                ),
                "itemsCount": (
                    properties.get(
                        "itemsCount"
                    )
                ),
            }

            result[outputName] = {
                "outputName": outputName,
                "mapperKind": (
                    properties.get(
                        "mapperKind"
                    )
                    or "flat_set"
                ),
                "className": (
                    row.get("setClassName")
                    or ""
                ),
                "itemClassName": (
                    row.get("itemClassName")
                    or ""
                ),
                "setId": row.get("setId"),
                "rootObjectId": (
                    row.get("objectId")
                ),
                "scipionObjId": (
                    row.get("scipionObjId")
                ),
                "info": (
                    self
                    ._buildPersistedOutputInfo(
                        outputName=outputName,
                        persistedOutput=(
                            persistedOutput
                        ),
                        properties=properties,
                    )
                ),
            }

        treeRows = objectMapper.listProtocolTreeOutputRows(
            projectId=projectId,
            protocolDbId=int(protocolDbId),
        )

        for row in treeRows:
            outputName = str(
                row.get("outputName")
                or ""
            ).strip()

            if not outputName:
                continue

            metadata = (
                row.get("metadata")
                or {}
            )

            if isinstance(metadata, str):
                try:
                    metadata = json.loads(
                        metadata
                    )
                except Exception:
                    metadata = {}

            if not isinstance(
                    metadata,
                    dict,
            ):
                metadata = {}

            className = str(
                row.get("className")
                or ""
            )

            displayText = (
                metadata.get(
                    "displayText"
                )
                or row.get("value")
                or row.get("label")
                or className
                or outputName
            )

            result[outputName] = {
                "outputName": outputName,
                "mapperKind": (
                    metadata.get(
                        "mapperKind"
                    )
                    or "tree"
                ),
                "className": className,
                "rootObjectId": (
                    row.get("rootObjectId")
                ),
                "scipionObjId": (
                    row.get("scipionObjId")
                ),
                "info": str(
                    displayText
                    or ""
                ),
            }

        return result

    def loadPersistedOutputsByProtocolId(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
    ) -> Dict[str, Dict[str, Dict[str, Any]]]:
        def toOptionalInt(value: Any) -> Optional[int]:
            if value is None or value == "":
                return None
            try:
                return int(value)
            except Exception:
                return None

        result: Dict[str, Dict[str, Dict[str, Any]]] = {}

        from app.backend.mapper import ScipionObjectPostgresqlMapper, ScipionSetPostgresqlMapper

        setMapper = ScipionSetPostgresqlMapper(mapper.db)
        objectMapper = ScipionObjectPostgresqlMapper(mapper.db)

        setRows = setMapper.listProjectSetOutputRows(projectId=projectId)

        for row in setRows:
            protocolId = str(row.get("protocolId"))
            outputName = str(row.get("outputName") or "")
            if not protocolId or not outputName:
                continue

            properties = row.get("properties") or {}

            persistedOutputInfo = self._buildPersistedOutputInfo(
                outputName=outputName,
                persistedOutput={
                    "className": row.get("setClassName"),
                    "itemClassName": row.get("itemClassName"),
                    "itemsCount": toOptionalInt(properties.get("itemsCount")) if isinstance(properties, dict) else None,
                    "itemsTableCount": toOptionalInt(row.get("itemsTableCount")),
                    "rootTableItemsCount": toOptionalInt(row.get("rootTableItemsCount")),
                },
                properties=properties if isinstance(properties, dict) else {},
            )

            result.setdefault(protocolId, {})[outputName] = {
                "mapperKind": "flat_set",
                "setId": row.get("id"),
                "protocolDbId": toOptionalInt(row.get("protocolDbId")),
                "rootObjectId": row.get("objectId"),
                "rootObjectDbId": toOptionalInt(row.get("rootObjectDbId")),
                "rootObjectProjectId": toOptionalInt(row.get("rootObjectProjectId")),
                "rootObjectProtocolDbId": toOptionalInt(row.get("rootObjectProtocolDbId")),
                "rootObjectParentObjectId": toOptionalInt(row.get("rootObjectParentObjectId")),
                "rootObjectName": row.get("rootObjectName"),
                "rootObjectPath": row.get("rootObjectPath"),
                "rootObjectClassName": row.get("rootObjectClassName"),
                "className": row.get("setClassName"),
                "itemClassName": row.get("itemClassName"),
                "info": persistedOutputInfo,
                "itemsCount": toOptionalInt(properties.get("itemsCount")) if isinstance(properties, dict) else None,
                "itemsTableCount": toOptionalInt(row.get("itemsTableCount")),
                "maxItemIdFromItems": toOptionalInt(row.get("maxItemIdFromItems")),
                "itemsIdSignature": row.get("itemsIdSignature"),
                "itemsValueSignature": row.get("itemsValueSignature"),
                "maxItemId": toOptionalInt(properties.get("maxItemId")) if isinstance(properties, dict) else None,
                "columnsCount": toOptionalInt(properties.get("columnsCount")) if isinstance(properties, dict) else None,
                "setColumnsCount": toOptionalInt(row.get("setColumnsCount")),
                "setColumnsSignature": row.get("setColumnsSignature") or [],
                "rootTablesCount": toOptionalInt(row.get("rootTablesCount")),
                "rootTableId": toOptionalInt(row.get("rootTableId")),
                "rootTableItemsCount": toOptionalInt(row.get("rootTableItemsCount")),
                "rootTableMaxItemId": toOptionalInt(row.get("rootTableMaxItemId")),
                "rootTableItemsIdSignature": row.get("rootTableItemsIdSignature"),
                "rootTableItemsValueSignature": row.get("rootTableItemsValueSignature"),
                "rootTableColumnsCount": toOptionalInt(row.get("rootTableColumnsCount")),
                "rootTableColumnsSignature": row.get("rootTableColumnsSignature") or [],
                "propertiesPayloadCount": toOptionalInt(row.get("propertiesPayloadCount")),
                "propertiesPayloadSignature": row.get("propertiesPayloadSignature") or [],
                "setPropertiesCount": toOptionalInt(row.get("setPropertiesCount")),
                "setPropertiesSignature": row.get("setPropertiesSignature") or [],
                "lastSyncAt": properties.get("lastSyncAt") if isinstance(properties, dict) else None,
                "lastCheckedAt": properties.get("lastCheckedAt") if isinstance(properties, dict) else None,
                "skippedLastSync": properties.get("skippedLastSync") if isinstance(properties, dict) else None,
                "createdAt": row.get("createdAt"),
                "updatedAt": row.get("updatedAt"),
            }

        treeRows = objectMapper.listProjectTreeOutputRows(projectId=projectId)

        for row in treeRows:
            protocolId = str(row.get("protocolId"))
            outputName = str(row.get("path") or row.get("name") or "")
            if not protocolId or not outputName:
                continue

            metadata = row.get("metadata") or {}
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except Exception:
                    metadata = {}

            if not isinstance(metadata, dict):
                metadata = {}

            className = row.get("className")
            displayText = (
                    metadata.get("displayText")
                    or row.get("value")
                    or row.get("label")
                    or className
                    or outputName
            )

            result.setdefault(protocolId, {})[outputName] = {
                "mapperKind": metadata.get("mapperKind") or "tree",
                "rootObjectId": row.get("id"),
                "rootObjectDbId": toOptionalInt(row.get("id")),
                "scipionObjId": row.get("scipionObjId"),
                "rootObjectName": row.get("name"),
                "rootObjectPath": row.get("path"),
                "rootObjectClassName": className,
                "className": className,
                "info": str(displayText or ""),
                "value": row.get("value"),
                "label": row.get("label"),
                "comment": row.get("comment"),
                "metadata": metadata,
                "createdAt": row.get("createdAt"),
                "updatedAt": row.get("updatedAt"),
            }

        return result

    def loadPersistedOutputSummariesByProtocolId(
            self,
            mapper: PostgresqlFlatMapper,
            projectId: int,
    ) -> Dict[str, Dict[str, Dict[str, Any]]]:
        def toOptionalInt(value: Any) -> Optional[int]:
            if value is None or value == "":
                return None
            try:
                return int(value)
            except Exception:
                return None

        result: Dict[str, Dict[str, Dict[str, Any]]] = {}

        from app.backend.mapper import ScipionObjectPostgresqlMapper, ScipionSetPostgresqlMapper

        setMapper = ScipionSetPostgresqlMapper(mapper.db)
        objectMapper = ScipionObjectPostgresqlMapper(mapper.db)

        setRows = setMapper.listProjectSetOutputSummaryRows(projectId=projectId)

        for row in setRows:
            protocolId = str(row.get("protocolId"))
            outputName = str(row.get("outputName") or "")
            if not protocolId or not outputName:
                continue

            properties = row.get("properties") or {}

            result.setdefault(protocolId, {})[outputName] = {
                "mapperKind": "flat_set",
                "setId": row.get("id"),
                "rootObjectId": row.get("objectId"),
                "className": row.get("setClassName"),
                "itemClassName": row.get("itemClassName"),
                "itemsCount": toOptionalInt(properties.get("itemsCount")) if isinstance(properties, dict) else None,
                "maxItemId": toOptionalInt(properties.get("maxItemId")) if isinstance(properties, dict) else None,
                "columnsCount": toOptionalInt(properties.get("columnsCount")) if isinstance(properties, dict) else None,
                "lastSyncAt": properties.get("lastSyncAt") if isinstance(properties, dict) else None,
                "lastCheckedAt": properties.get("lastCheckedAt") if isinstance(properties, dict) else None,
                "skippedLastSync": properties.get("skippedLastSync") if isinstance(properties, dict) else None,
                "createdAt": row.get("createdAt"),
                "updatedAt": row.get("updatedAt"),
            }

        treeRows = objectMapper.listProjectTreeOutputRows(projectId=projectId)

        for row in treeRows:
            protocolId = str(row.get("protocolId"))
            outputName = str(row.get("path") or row.get("name") or "")
            if not protocolId or not outputName:
                continue

            result.setdefault(protocolId, {})[outputName] = {
                "mapperKind": "tree",
                "rootObjectId": row.get("id"),
                "scipionObjId": row.get("scipionObjId"),
                "className": row.get("className"),
                "value": row.get("value"),
                "label": row.get("label"),
                "comment": row.get("comment"),
                "metadata": row.get("metadata") or {},
                "createdAt": row.get("createdAt"),
                "updatedAt": row.get("updatedAt"),
            }

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

    def loadPersistedProtocolOutputNames(
            self,
            mapper,
            projectId: int,
            protocolDbId: int,
    ) -> Set[str]:
        """
        Load the names of all flat-set and tree outputs currently persisted
        for one protocol.

        Set root objects are excluded from the tree query because they are
        represented through scipion_sets.
        """
        outputNames: Set[str] = set()

        from app.backend.mapper import ScipionObjectPostgresqlMapper, ScipionSetPostgresqlMapper

        setMapper = ScipionSetPostgresqlMapper(mapper.db)
        objectMapper = ScipionObjectPostgresqlMapper(mapper.db)

        setRows = setMapper.listProtocolSetOutputNameRows(projectId=projectId, protocolDbId=protocolDbId)

        for row in setRows or []:
            outputName = (
                row.get("outputName")
                if isinstance(row, dict)
                else row[0]
            )

            outputNameText = str(
                outputName or ""
            ).strip()

            if outputNameText:
                outputNames.add(
                    outputNameText
                )

        treeRows = objectMapper.listProtocolTreeOutputNameRows(projectId=projectId, protocolDbId=protocolDbId)

        for row in treeRows or []:
            outputName = (
                row.get("outputName")
                if isinstance(row, dict)
                else row[0]
            )

            outputNameText = str(
                outputName or ""
            ).strip()

            if outputNameText:
                outputNames.add(
                    outputNameText
                )

        return outputNames

    def deletePersistedProtocolOutputSnapshots(
            self,
            mapper,
            projectId: int,
            protocolDbId: int,
            outputNames: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Delete PostgreSQL metadata for outputs that are no longer exposed by
        a terminal protocol.

        Files are intentionally not removed from the filesystem. Their lifecycle
        remains under the native Scipion protocol operations.
        """
        normalizedOutputNames = sorted({
            str(outputName).strip()
            for outputName in outputNames or []
            if str(outputName or "").strip()
        })

        if not normalizedOutputNames:
            return []

        from app.backend.mapper import ScipionObjectPostgresqlMapper

        objectMapper = ScipionObjectPostgresqlMapper(mapper.db)
        return objectMapper.deleteProtocolOutputSnapshots(projectId=projectId,
                                                          protocolDbId=protocolDbId,
                                                          outputNames=normalizedOutputNames)

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
            projectPaths: Optional[
                List[str]
            ] = None,
            allowDetachedSetOutputs: bool = False,
    ) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        from app.backend.mapper import (
            ScipionObjectPostgresqlMapper,
            ScipionSetPostgresqlMapper,
        )

        declaredOutputs: List[Dict[str, Any]] = []
        persistedOutputs: List[Dict[str, Any]] = []
        skippedOutputs: List[Dict[str, Any]] = []
        outputErrors: List[Dict[str, Any]] = []
        removedOutputs: List[
            Dict[str, Any]
        ] = []

        currentOutputNames: Set[str] = set()

        protocolId = self.getScipionObjectId(protocol)
        protocolDbId = self.resolveProtocolDbIdForOutputPersistence(
            mapper=mapper,
            projectId=projectId,
            protocol=protocol,
        )

        if protocolDbId is None:
            raise ValueError(f"Protocol not found in PostgreSQL: {protocolId}")

        reconcileMissingOutputs = (
            self
            .shouldReconcileMissingProtocolOutputs(
                protocol
            )
        )

        persistedOutputNames: Set[str] = set()

        if reconcileMissingOutputs:
            try:
                persistedOutputNames = (
                    self
                    .loadPersistedProtocolOutputNames(
                        mapper=mapper,
                        projectId=projectId,
                        protocolDbId=int(
                            protocolDbId
                        ),
                    )
                )

            except Exception as exc:
                reconcileMissingOutputs = False

                logger.exception(
                    "Could not load persisted protocol output names. "
                    "projectId=%s protocolId=%s",
                    projectId,
                    protocolId,
                )

                outputErrors.append({
                    "outputName": None,
                    "outputClassName": None,
                    "operation": (
                        "load_persisted_output_names"
                    ),
                    "error": str(exc),
                })

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
                "removed": removedOutputs,
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

            currentOutputNames.add(
                outputName
            )

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

            isSetOutput = (
                self.isScipionSetLikeOutput(
                    outputObj
                )
            )

            isTreeOutput = (
                    not isSetOutput
                    and self.isPersistableNonSetOutput(
                outputObj
            )
            )

            isPostgresqlRuntimeSet = (
                    isSetOutput
                    and (
                            self._isPostgresqlRuntimeSetOutput(
                                outputObj
                            )
                            or self
                            ._isPersistedPostgresqlNativeSetOutput(
                        setMapper=setMapper,
                        projectId=projectId,
                        protocolDbId=int(
                            protocolDbId
                        ),
                        outputName=outputName,
                    )
                    )
            )

            identityPreparation = None

            try:
                if isTreeOutput:
                    identityPreparation = self._prepareOutputObjectIdsForPersistence(
                        mapper=mapper,
                        objectMapper=objectMapper,
                        projectId=projectId,
                        protocolDbId=int(protocolDbId),
                        protocolId=protocolId,
                        outputName=outputName,
                        outputObj=outputObj,
                        includeNestedProperties=True,
                    )

                if isSetOutput:
                    if isPostgresqlRuntimeSet:
                        syncInfo = (
                            setMapper
                            .finalizeRuntimeSetOutput(
                                projectId=projectId,
                                protocolDbId=int(
                                    protocolDbId
                                ),
                                outputName=outputName,
                                scipionSet=outputObj,
                            )
                        )

                        persistedOutputs.append({
                            "outputName": outputName,
                            "outputClassName": (
                                outputClassName
                            ),
                            "mapperKind": "flat_set",
                            "postgresqlNativeOutput": True,
                            **(syncInfo or {}),
                        })

                        continue

                    openedSetMapper = False

                    try:
                        openedSetMapper = (
                            self
                            ._openRelativeSetMapperForPersistence(
                                protocol=protocol,
                                scipionSet=outputObj,
                                projectPaths=projectPaths,
                            )
                        )

                    except FileNotFoundError as artifactError:
                        if not allowDetachedSetOutputs:
                            raise

                        logger.warning(
                            "Persisting detached Scipion Set because "
                            "its backing database is missing. "
                            "projectId=%s protocolId=%s "
                            "outputName=%s className=%s "
                            "fileName=%s",
                            projectId,
                            protocolId,
                            outputName,
                            outputClassName,
                            self.safeCall(
                                outputObj,
                                "getFileName",
                                None,
                            ),
                        )

                        identityPreparation = self._prepareOutputObjectIdsForPersistence(
                            mapper=mapper,
                            objectMapper=objectMapper,
                            projectId=projectId,
                            protocolDbId=int(protocolDbId),
                            protocolId=protocolId,
                            outputName=outputName,
                            outputObj=outputObj,
                            includeNestedProperties=True,
                        )

                        scipionObjectIdsByPath = identityPreparation.get("_scipionObjectIdsByPath") or {}

                        syncInfo = self._storeDetachedSetOutput(
                            objectMapper=objectMapper,
                            projectId=projectId,
                            protocolDbId=int(protocolDbId),
                            outputName=outputName,
                            outputObj=outputObj,
                            projectPaths=projectPaths,
                            artifactError=artifactError,
                            scipionObjectIdsByPath=scipionObjectIdsByPath,
                        )

                        persistedOutputs.append({
                            **(syncInfo or {}),
                            "outputName": outputName,
                            "outputClassName": (
                                outputClassName
                            ),
                            "mapperKind": (
                                "detached_set"
                            ),
                        })

                        continue

                    try:
                        identityPreparation = self._prepareOutputObjectIdsForPersistence(
                            mapper=mapper,
                            objectMapper=objectMapper,
                            projectId=projectId,
                            protocolDbId=int(protocolDbId),
                            protocolId=protocolId,
                            outputName=outputName,
                            outputObj=outputObj,
                            includeNestedProperties=False,
                        )

                        syncInfo = setMapper.storeSet(
                            projectId=projectId,
                            protocolDbId=int(protocolDbId),
                            outputName=outputName,
                            scipionSet=outputObj,
                        )

                    finally:
                        if openedSetMapper:
                            try:
                                outputObj.close()
                            except Exception:
                                logger.debug(
                                    "Could not close Scipion "
                                    "Set after PostgreSQL "
                                    "persistence. "
                                    "projectId=%s "
                                    "protocolId=%s "
                                    "outputName=%s",
                                    projectId,
                                    protocolId,
                                    outputName,
                                    exc_info=True,
                                )

                    persistedOutputs.append({
                        "outputName": outputName,
                        "outputClassName": (
                            outputClassName
                        ),
                        "mapperKind": "flat_set",
                        **(syncInfo or {}),
                    })


                elif isTreeOutput:
                    scipionObjectIdsByPath = {}

                    if isinstance(identityPreparation, dict):
                        scipionObjectIdsByPath = identityPreparation.get("_scipionObjectIdsByPath") or {}
                    syncInfo = objectMapper.storeObjectTree(
                        projectId=projectId,
                        protocolDbId=int(protocolDbId),
                        outputName=outputName,
                        scipionObj=outputObj,
                        registerType=True,
                        includeNestedProperties=True,
                        scipionObjectIdsByPath=scipionObjectIdsByPath,
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
            finally:
                self._restoreOutputObjectIdsAfterPersistence(
                    identityPreparation
                )

        if reconcileMissingOutputs:
            staleOutputNames = sorted(
                persistedOutputNames
                - currentOutputNames
            )

            if staleOutputNames:
                try:
                    removedOutputs = (
                        self
                        .deletePersistedProtocolOutputSnapshots(
                            mapper=mapper,
                            projectId=projectId,
                            protocolDbId=int(
                                protocolDbId
                            ),
                            outputNames=staleOutputNames,
                        )
                    )

                except Exception as exc:
                    logger.exception(
                        "Failed to remove stale persisted protocol outputs. "
                        "projectId=%s protocolId=%s outputNames=%s",
                        projectId,
                        protocolId,
                        staleOutputNames,
                    )

                    outputErrors.append({
                        "outputName": None,
                        "outputClassName": None,
                        "operation": (
                            "remove_stale_outputs"
                        ),
                        "staleOutputNames": (
                            staleOutputNames
                        ),
                        "error": str(exc),
                    })

        report = {
            "declared": declaredOutputs,
            "persisted": persistedOutputs,
            "skipped": skippedOutputs,
            "removed": removedOutputs,
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
        protocolIdentityResolver = ProtocolIdentityResolver(mapper=mapper, projectId=projectId)
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

        outputFiles = self.collectPersistedProtocolOutputFiles(mapper=mapper, projectId=projectId, protocolDbId=protocolDbId)

        fileCleanup = self.deletePersistedProtocolOutputFilesFromFilesystem(
            protocol=protocol,
            rawFileNames=outputFiles,
            getCurrentProjectPathCallback=getCurrentProjectPathCallback,
        )

        from app.backend.mapper import ScipionObjectPostgresqlMapper

        objectMapper = ScipionObjectPostgresqlMapper(mapper.db)
        metadataCleanup = objectMapper.deleteProtocolOutputMetadata(projectId=projectId, protocolDbId=protocolDbId)

        return {
            "protocolDbId": protocolDbId,
            "setsDeleted": int(metadataCleanup.get("setsDeleted") or 0),
            "objectsDeleted": int(metadataCleanup.get("objectsDeleted") or 0),
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
        from app.backend.mapper import ScipionObjectPostgresqlMapper

        objectMapper = ScipionObjectPostgresqlMapper(mapper.db)
        rows = objectMapper.listProtocolOutputFileRows(projectId=projectId, protocolDbId=protocolDbId)

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