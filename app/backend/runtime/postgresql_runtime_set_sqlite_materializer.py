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
import re
import shutil
import tempfile
import threading
import uuid
import weakref
from datetime import datetime, timedelta
from collections.abc import Mapping
from typing import Any, Dict, Optional, Type

from pyworkflow.object import Set as ScipionSet

logger = logging.getLogger(__name__)


class PostgresqlRuntimeSetSqliteMaterializer:
    """
    Create worker-local SQLite compatibility snapshots from PostgreSQL
    runtime Sets.

    PostgreSQL remains the only authoritative persistence. These files are
    disposable, isolated per consumer worker and refreshed at a stable path
    for legacy streaming protocols that cache Set.getFileName().

    See .ai/postgresql-runtime-compatibility.md before changing this class.
    """

    DIRECTORY_NAME = "postgresql-runtime-sets"
    MATERIALIZED_PATH_PROPERTY = "materializedFileName"
    COMPATIBILITY_BUILD_ATTRIBUTE = "_postgresqlCompatibilityBuild"

    _managedPathsLock = threading.RLock()
    _managedRuntimeSets = weakref.WeakValueDictionary()
    STREAMING_CURSOR_EPOCH = datetime(
        2000,
        1,
        1,
    )

    def __init__(self):
        # RLock allows a recursive call to reach our
        # explicit recursion guard instead of hanging
        # forever while waiting for the same thread.
        self._lock = threading.RLock()

        self._materializingSetIdentities = set()

    @classmethod
    def refreshManagedPath(
            cls,
            path: str,
    ) -> bool:
        if not path:
            return False

        managedPath = os.path.realpath(str(path))

        with cls._managedPathsLock:
            runtimeSet = cls._managedRuntimeSets.get(managedPath)

        if runtimeSet is None:
            return False

        materializer = getattr(
            runtimeSet,
            "_postgresqlSqliteMaterializer",
            None,
        )

        if materializer is None:
            with cls._managedPathsLock:
                cls._managedRuntimeSets.pop(managedPath, None)

            return False

        refreshedPath = materializer.materialize(runtimeSet)
        refreshedPath = os.path.realpath(str(refreshedPath))

        if refreshedPath != managedPath:
            raise RuntimeError(
                "PostgreSQL SQLite compatibility refresh "
                "changed its managed path. expected=%s actual=%s"
                % (
                    managedPath,
                    refreshedPath,
                )
            )

        return True

    def _registerManagedPath(
            self,
            runtimeSet: ScipionSet,
            materializedPath: str,
    ) -> None:
        managedPath = os.path.realpath(str(materializedPath))

        runtimeSet._postgresqlSqliteMaterializer = self

        with self._managedPathsLock:
            self._managedRuntimeSets[managedPath] = runtimeSet

    @classmethod
    def _getManagedRootDirectory(cls) -> str:
        return os.path.realpath(os.path.join(tempfile.gettempdir(), cls.DIRECTORY_NAME))

    @classmethod
    def _getCurrentWorkerDirectory(cls) -> str:
        return os.path.abspath(
            os.path.join(
                cls._getManagedRootDirectory(),
                "worker-%s" % os.getpid(),
            )
        )

    @classmethod
    def cleanupCurrentWorkerDirectory(cls) -> Dict[str, Any]:
        managedRoot = cls._getManagedRootDirectory()
        workerDirectory = cls._getCurrentWorkerDirectory()
        expectedDirectoryName = "worker-%s" % os.getpid()

        try:
            commonPath = os.path.commonpath(
                (
                    managedRoot,
                    workerDirectory,
                )
            )
        except ValueError as error:
            raise RuntimeError(
                "Could not validate PostgreSQL SQLite worker directory: %s"
                % workerDirectory
            ) from error

        if (
                commonPath != managedRoot
                or os.path.basename(workerDirectory) != expectedDirectoryName
        ):
            raise RuntimeError(
                "Refusing to clean an unexpected PostgreSQL SQLite "
                "worker directory: %s"
                % workerDirectory
            )

        with cls._managedPathsLock:
            managedPaths = []

            for managedPath in list(cls._managedRuntimeSets.keys()):
                try:
                    belongsToWorker = (
                        os.path.commonpath(
                            (
                                workerDirectory,
                                os.path.realpath(managedPath),
                            )
                        )
                        == workerDirectory
                    )
                except ValueError:
                    belongsToWorker = False

                if belongsToWorker:
                    managedPaths.append(managedPath)

        if not os.path.lexists(workerDirectory):
            with cls._managedPathsLock:
                for managedPath in managedPaths:
                    cls._managedRuntimeSets.pop(managedPath, None)

            return {
                "workerDirectory": workerDirectory,
                "removed": False,
                "deleted": [],
                "deletedCount": 0,
                "registryEntriesRemoved": len(managedPaths),
            }

        if os.path.islink(workerDirectory):
            raise RuntimeError(
                "Refusing to clean a symbolic PostgreSQL SQLite "
                "worker directory: %s"
                % workerDirectory
            )

        if not os.path.isdir(workerDirectory):
            raise RuntimeError(
                "PostgreSQL SQLite worker path is not a directory: %s"
                % workerDirectory
            )

        deletedPaths = sorted(
            os.path.join(rootPath, fileName)
            for rootPath, _, fileNames in os.walk(workerDirectory)
            for fileName in fileNames
        )

        shutil.rmtree(workerDirectory)

        with cls._managedPathsLock:
            for managedPath in managedPaths:
                cls._managedRuntimeSets.pop(managedPath, None)

        return {
            "workerDirectory": workerDirectory,
            "removed": True,
            "deleted": deletedPaths,
            "deletedCount": len(deletedPaths),
            "registryEntriesRemoved": len(managedPaths),
        }

    def materialize(
            self,
            runtimeSet: ScipionSet,
    ) -> str:
        runtimeSetIdentity = id(
            runtimeSet
        )

        with self._lock:
            if runtimeSetIdentity in self._materializingSetIdentities:
                runtimeInfo = self._getRuntimeInfo(runtimeSet)

                raise RuntimeError(
                    "Recursive PostgreSQL SQLite "
                    "materialization detected. "
                    "className=%s setId=%s tableId=%s"
                    % (
                        runtimeSet.getClassName(),
                        runtimeInfo.get("setId"),
                        runtimeInfo.get("tableId"),
                    )
                )

            self._refreshRuntimeSetState(runtimeSet)

            cachedPath = self._getCachedPath(runtimeSet)
            sourceRevision = self._getSourceRevision(runtimeSet)

            cachedRevision = getattr(
                runtimeSet,
                "_postgresqlMaterializedRevision",
                None,
            )

            if (
                    cachedPath is not None
                    and (
                        sourceRevision is None
                        or cachedRevision == sourceRevision
                    )
            ):
                return cachedPath

            self._materializingSetIdentities.add(runtimeSetIdentity)

            materializedPath = None
            targetSet = None

            try:
                # Rebuild stale snapshots at the same worker-local
                # path. This avoids accumulating obsolete SQLite files
                # and preserves the filename expected by streaming code.
                materializedPath = (
                        cachedPath
                        or self._buildMaterializedPath(
                    runtimeSet
                )
                )

                os.makedirs(
                    os.path.dirname(
                        materializedPath
                    ),
                    exist_ok=True,
                )

                self._removeSqliteFiles(
                    materializedPath
                )

                classes = self._getRuntimeClasses(
                    runtimeSet
                )

                nativeSetClass = (
                    self._getNativeSetClass(
                        runtimeSet
                    )
                )

                targetSet = self._openSet(
                    setClass=nativeSetClass,
                    fileName=materializedPath,
                    classes=classes,
                )

                self._copySetMetadata(
                    runtimeSet,
                    targetSet,
                )

                self._copySetItems(
                    runtimeSet,
                    targetSet,
                    classes,
                )

                targetSet.write()
                targetSet.close()
                targetSet = None

                self._rememberMaterializedPath(
                    runtimeSet,
                    materializedPath,
                    sourceRevision=(
                        sourceRevision
                    ),
                )

                return materializedPath

            except Exception:
                if targetSet is not None:
                    try:
                        targetSet.close()
                    except Exception:
                        pass

                self._removeSqliteFiles(
                    materializedPath
                )

                raise

            finally:
                self._materializingSetIdentities.discard(
                    runtimeSetIdentity
                )

    def _getSourceRevision(
            self,
            runtimeSet: ScipionSet,
    ):
        runtimeChecker = getattr(
            runtimeSet,
            "isPostgresqlRuntimeOutput",
            None,
        )

        if (
                not callable(
                    runtimeChecker
                )
                or not runtimeChecker()
        ):
            return None

        mapper = runtimeSet._getMapper()

        revisionGetter = getattr(
            mapper,
            "getRevisionToken",
            None,
        )

        if callable(
                revisionGetter
        ):
            return revisionGetter()

        # Safe fallback while loading an object created by
        # older runtime mapper code.
        return (
            "fallback",
            int(
                mapper.count()
            ),
            int(
                mapper.maxId()
            ),
        )

    @staticmethod
    def _refreshRuntimeSetState(
            runtimeSet: ScipionSet,
    ) -> None:
        refresher = getattr(
            runtimeSet,
            "refreshPostgresqlRuntimeState",
            None,
        )

        if callable(
                refresher
        ):
            refresher()

    def _getCachedPath(
            self,
            runtimeSet: ScipionSet,
    ) -> Optional[str]:
        cachedPath = getattr(
            runtimeSet,
            "_postgresqlMaterializedFileName",
            None,
        )

        if not cachedPath:
            cachedPath = (
                self
                ._getRuntimeProperties(
                    runtimeSet
                )
                .get(
                    self.MATERIALIZED_PATH_PROPERTY
                )
            )

        if not cachedPath:
            return None

        cachedPath = os.path.realpath(
            str(cachedPath)
        )

        # Never accept a cached path located in Runs/,
        # project root, extra/, or any other persistent
        # project directory.
        if not self._isManagedTemporaryPath(
                cachedPath
        ):
            logger.warning(
                "Ignoring persistent SQLite compatibility "
                "path for PostgreSQL runtime Set. "
                "className=%s path=%s",
                runtimeSet.getClassName(),
                cachedPath,
            )

            return None

        if not os.path.isfile(
                cachedPath
        ):
            return None

        return cachedPath

    def _isManagedTemporaryPath(
            self,
            path: str,
    ) -> bool:
        if not path:
            return False

        managedRoot = self._getManagedRootDirectory()

        candidatePath = os.path.realpath(
            str(path)
        )

        try:
            return (
                    os.path.commonpath(
                        (
                            managedRoot,
                            candidatePath,
                        )
                    )
                    == managedRoot
            )

        except ValueError:
            # Different drives or incompatible paths.
            return False

    def _rememberMaterializedPath(
            self,
            runtimeSet: ScipionSet,
            materializedPath: str,
            sourceRevision=None,
    ) -> None:
        materializedPath = str(
            materializedPath
        )

        runtimeSet._postgresqlMaterializedFileName = (
            materializedPath
        )

        runtimeSet._postgresqlMaterializedRevision = (
            sourceRevision
        )

        properties = self._getRuntimeProperties(
            runtimeSet
        )

        properties[
            self.MATERIALIZED_PATH_PROPERTY
        ] = materializedPath

        runtimeSet._postgresqlRuntimeProperties = (
            properties
        )

        self._registerManagedPath(
            runtimeSet=runtimeSet,
            materializedPath=materializedPath,
        )

    def _openSet(
            self,
            setClass: Type,
            fileName: str,
            classes: Dict[str, Type],
            prefix: str = "",
    ) -> ScipionSet:
        targetSet = setClass()
        self._setClassesDict(targetSet, classes)

        mapperPath = getattr(targetSet, "_mapperPath", None)
        if mapperPath is None:
            raise RuntimeError(
                "Scipion Set %s does not expose _mapperPath"
                % setClass.__name__
            )

        mapperPath.set("%s, %s" % (fileName, prefix))

        setattr(
            targetSet,
            self.COMPATIBILITY_BUILD_ATTRIBUTE,
            True,
        )

        try:
            targetSet.load()
        finally:
            targetSet.__dict__.pop(
                self.COMPATIBILITY_BUILD_ATTRIBUTE,
                None,
            )

        return targetSet

    def _copySetMetadata(
            self,
            sourceSet: ScipionSet,
            targetSet: ScipionSet,
    ) -> None:
        targetSet.copy(
            sourceSet,
            copyId=True,
            ignoreAttrs=[
                "_mapperPath",
                "_size",
                "_objParent",
            ],
        )
        self._copyEnabled(sourceSet, targetSet)

        getObjName = getattr(sourceSet, "getObjName", None)
        setName = getattr(targetSet, "setName", None)
        if callable(getObjName) and callable(setName):
            objName = getObjName()
            if objName:
                setName(str(objName))

    def _copySetItems(
            self,
            sourceSet: ScipionSet,
            targetSet: ScipionSet,
            classes: Dict[str, Type],
    ) -> None:
        sourceClasses = self._getRuntimeClasses(sourceSet) or classes
        itemSchema = None

        for sourceItem in self._iterSourceItems(sourceSet):
            targetItem = self._cloneItem(
                sourceItem,
                sourceClasses,
            )

            nestedSetItem = isinstance(
                sourceItem,
                ScipionSet,
            )

            if nestedSetItem:
                setattr(targetItem, self.COMPATIBILITY_BUILD_ATTRIBUTE, True)

            try:
                if not nestedSetItem:
                    if itemSchema is None:
                        itemSchema = targetItem
                    else:
                        self._completeMissingItemAttributes(
                            targetItem,
                            itemSchema,
                        )

                targetSet.append(targetItem)

                self._setStableStreamingCreation(
                    targetItem=targetItem,
                    targetSet=targetSet,
                )

                if not nestedSetItem:
                    continue

                self._ensureNestedMapper(
                    targetParentSet=targetSet,
                    targetNestedSet=targetItem,
                    classes=sourceClasses,
                )

                self._copySetItems(
                    sourceSet=sourceItem,
                    targetSet=targetItem,
                    classes=sourceClasses,
                )

                targetItem.write(properties=False)
                targetSet.update(targetItem)

            finally:
                if nestedSetItem:
                    # Native tomography Sets may call load() from append().
                    # Keep that internal load outside the managed-path
                    # refresh mechanism while this snapshot is constructed.
                    targetItem._mapper = None
                    targetItem.__dict__.pop(
                        self.COMPATIBILITY_BUILD_ATTRIBUTE,
                        None,
                    )

        self._ensureSetSchema(
            sourceSet=sourceSet,
            targetSet=targetSet,
            classes=sourceClasses,
        )

    def _completeMissingItemAttributes(
            self,
            targetItem,
            schemaItem,
    ) -> None:
        for attributeName, schemaAttribute in schemaItem.getAttributesToStore():
            targetAttribute = getattr(
                targetItem,
                attributeName,
                None,
            )

            if targetAttribute is None:
                targetAttribute = schemaAttribute.getClass()()
                setattr(
                    targetItem,
                    attributeName,
                    targetAttribute,
                )

            if schemaAttribute.isPointer():
                continue

            self._completeMissingItemAttributes(
                targetAttribute,
                schemaAttribute,
            )

    @classmethod
    def _buildStableStreamingCreation(
            cls,
            itemId: int,
    ) -> str:
        itemId = int(itemId)

        if itemId < 0:
            raise ValueError(
                "Streaming item id cannot be negative."
            )

        try:
            creation = (
                cls.STREAMING_CURSOR_EPOCH
                + timedelta(
                    microseconds=itemId
                )
            )

        except OverflowError as error:
            raise ValueError(
                "Streaming item id is too large: %s"
                % itemId
            ) from error

        return creation.strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )

    def _setStableStreamingCreation(
            self,
            targetItem,
            targetSet: ScipionSet,
    ) -> None:
        itemId = targetItem.getObjId()

        if itemId in (None, ""):
            raise RuntimeError(
                "Cannot create a stable SQLite "
                "streaming cursor without an object id."
            )

        creationText = (
            self
            ._buildStableStreamingCreation(
                int(itemId)
            )
        )

        mapper = targetSet._getMapper()
        sqliteDb = getattr(
            mapper,
            "db",
            None,
        )

        executeCommand = getattr(
            sqliteDb,
            "executeCommand",
            None,
        )

        if not callable(executeCommand):
            raise RuntimeError(
                "SQLite compatibility mapper does not "
                "provide executeCommand()."
            )

        tablePrefix = str(
            getattr(
                sqliteDb,
                "tablePrefix",
                "",
            )
            or ""
        )

        executeCommand(
            "UPDATE %sObjects "
            "SET creation=? "
            "WHERE id=?"
            % tablePrefix,
            (
                creationText,
                int(itemId),
            ),
        )

        targetItem.setObjCreation(
            creationText
        )

    def _iterSourceItems(
            self,
            sourceSet: ScipionSet,
    ):
        """
        Iterate PostgreSQL runtime Sets directly through their
        PostgreSQL mapper.

        Tomography Sets may override iterItems() and use
        getFileName() internally to resolve nested SQLite tables.
        Calling that method while materializing the same Set
        produces recursive materialization.
        """
        runtimeChecker = getattr(
            sourceSet,
            "isPostgresqlRuntimeOutput",
            None,
        )

        isPostgresqlRuntimeSet = (
            bool(
                runtimeChecker()
            )
            if callable(
                runtimeChecker
            )
            else False
        )

        if not isPostgresqlRuntimeSet:
            return sourceSet.iterItems()

        getMapper = getattr(
            sourceSet,
            "_getMapper",
            None,
        )

        if not callable(
                getMapper
        ):
            raise RuntimeError(
                "PostgreSQL runtime Set does not "
                "provide _getMapper(). "
                "className=%s objectId=%s"
                % (
                    sourceSet.getClassName(),
                    sourceSet.getObjId(),
                )
            )

        try:
            # Nested PostgreSQL Sets deliberately keep
            # _mapper=None until the first read.
            #
            # _getMapper() invokes the runtime load()
            # method and constructs the logical-table
            # mapper through _postgresqlMapperFactory.
            mapper = getMapper()

        except Exception as error:
            runtimeInfo = self._getRuntimeInfo(
                sourceSet
            )

            raise RuntimeError(
                "Could not lazily load PostgreSQL "
                "runtime Set mapper during SQLite "
                "compatibility materialization. "
                "className=%s objectId=%s "
                "setId=%s tableId=%s"
                % (
                    sourceSet.getClassName(),
                    sourceSet.getObjId(),
                    runtimeInfo.get(
                        "setId"
                    ),
                    runtimeInfo.get(
                        "tableId"
                    ),
                )
            ) from error

        if mapper is None:
            raise RuntimeError(
                "PostgreSQL runtime Set _getMapper() "
                "returned None during SQLite "
                "compatibility materialization. "
                "className=%s objectId=%s"
                % (
                    sourceSet.getClassName(),
                    sourceSet.getObjId(),
                )
            )

        selectAll = getattr(
            mapper,
            "selectAll",
            None,
        )

        if not callable(
                selectAll
        ):
            raise RuntimeError(
                "PostgreSQL runtime Set mapper does not "
                "provide selectAll(). "
                "className=%s mapperClass=%s"
                % (
                    sourceSet.getClassName(),
                    mapper.__class__.__name__,
                )
            )

        return selectAll(
            orderBy="id",
            direction="ASC",
            iterate=True,
        )

    def _ensureSetSchema(
            self,
            sourceSet: ScipionSet,
            targetSet: ScipionSet,
            classes: Dict[str, Type],
    ) -> None:
        mapper = targetSet._getMapper()

        if not getattr(
                mapper,
                "doCreateTables",
                False,
        ):
            return

        itemClass = self._resolveSetItemClass(
            sourceSet=sourceSet,
            targetSet=targetSet,
            classes=classes,
        )

        schemaItem = itemClass()

        schemaItem.setObjId(
            1
        )

        mapper.insert(
            schemaItem
        )

        mapper.delete(
            schemaItem
        )

    def _resolveSetItemClass(
            self,
            sourceSet: ScipionSet,
            targetSet: ScipionSet,
            classes: Dict[str, Type],
    ) -> Type:
        itemType = getattr(
            targetSet,
            "ITEM_TYPE",
            None,
        )

        if isinstance(
                itemType,
                type,
        ):
            return itemType

        if isinstance(
                itemType,
                str,
        ):
            itemClass = classes.get(
                itemType
            )

            if isinstance(
                    itemClass,
                    type,
            ):
                return itemClass

        itemClassName = self._getRuntimeInfo(
            sourceSet
        ).get(
            "itemClassName"
        )

        itemClass = classes.get(
            str(itemClassName)
        )

        if isinstance(
                itemClass,
                type,
        ):
            return itemClass

        raise RuntimeError(
            "Cannot resolve the item class required to create "
            "the compatibility SQLite schema for %s"
            % targetSet.getClassName()
        )

    def _cloneItem(
            self,
            sourceItem,
            classes: Dict[str, Type],
    ):
        if isinstance(sourceItem, ScipionSet):
            nativeItemClass = self._getNativeSetClass(sourceItem)
            targetItem = nativeItemClass()
            self._setClassesDict(targetItem, classes)
            targetItem.copy(
                sourceItem,
                copyId=True,
                ignoreAttrs=[
                    "_mapperPath",
                    "_size",
                    "_objParent",
                ],
            )
        else:
            itemClass = self._getObjectClass(sourceItem)
            targetItem = itemClass()
            try:
                targetItem.copy(
                    sourceItem,
                    copyId=True,
                    ignoreAttrs=[
                        "_objParent",
                    ],
                    copyEnable=True,
                )
            except TypeError:
                targetItem.copy(
                    sourceItem,
                    copyId=True,
                    ignoreAttrs=[
                        "_objParent",
                    ],
                )

        self._copyEnabled(sourceItem, targetItem)
        return targetItem

    def _ensureNestedMapper(
            self,
            targetParentSet: ScipionSet,
            targetNestedSet: ScipionSet,
            classes: Dict[str, Type],
    ) -> None:
        self._setClassesDict(targetNestedSet, classes)

        if getattr(targetNestedSet, "_mapper", None) is not None:
            return

        mapperPath = getattr(targetNestedSet, "_mapperPath", None)
        if mapperPath is None:
            raise RuntimeError(
                "Nested Scipion Set does not expose _mapperPath"
            )

        if mapperPath.isEmpty():
            mapperPath.set(
                "%s, %s"
                % (
                    targetParentSet.getFileName(),
                    self._buildNestedPrefix(targetNestedSet),
                )
            )

        targetNestedSet.load()

    def _setClassesDict(
            self,
            scipionSet: ScipionSet,
            classes: Dict[str, Type],
    ) -> None:
        if not classes:
            return

        classes = dict(classes)
        setter = getattr(scipionSet, "setClassesDict", None)
        if callable(setter):
            setter(classes)
        else:
            scipionSet._classesDict = classes

    def _buildMaterializedPath(
            self,
            runtimeSet: ScipionSet,
    ) -> str:
        info = self._getRuntimeInfo(
            runtimeSet
        )

        setId = info.get(
            "setId"
        )

        tableId = info.get(
            "tableId"
        )

        if tableId is not None:
            identity = (
                    "table-%s"
                    % tableId
            )
        elif setId is not None:
            identity = (
                    "set-%s"
                    % setId
            )
        else:
            identity = "set"

        className = self._sanitizePathPart(
            runtimeSet.getClassName()
        )

        fileName = "%s-%s-%s.sqlite" % (
            className or "ScipionSet",
            identity,
            uuid.uuid4().hex[:12],
        )

        return os.path.join(
            self._getCurrentWorkerDirectory(),
            fileName,
        )

    def _getRuntimeInfo(
            self,
            runtimeSet: ScipionSet,
    ) -> Dict[str, Any]:
        info = getattr(runtimeSet, "_postgresqlRuntimeInfo", {})
        return dict(info) if isinstance(info, Mapping) else {}

    def _getRuntimeProperties(
            self,
            runtimeSet: ScipionSet,
    ) -> Dict[str, Any]:
        properties = getattr(
            runtimeSet,
            "_postgresqlRuntimeProperties",
            {},
        )
        return (
            dict(properties)
            if isinstance(properties, Mapping)
            else {}
        )

    def _getRuntimeClasses(
            self,
            runtimeSet: ScipionSet,
    ) -> Dict[str, Type]:
        classes = getattr(runtimeSet, "_postgresqlRuntimeClasses", {})
        if isinstance(classes, Mapping) and classes:
            return dict(classes)

        loader = getattr(runtimeSet, "_loadClassesDict", None)
        if callable(loader):
            try:
                loadedClasses = loader()
                if isinstance(loadedClasses, Mapping):
                    return dict(loadedClasses)
            except Exception:
                pass

        return {}

    def _getNativeSetClass(self, runtimeSet: ScipionSet) -> Type:
        nativeSetClass = getattr(
            runtimeSet,
            "_postgresqlNativeSetClass",
            None,
        )
        if self._isSetClass(nativeSetClass):
            return nativeSetClass

        runtimeClass = runtimeSet.__class__
        for baseClass in runtimeClass.__mro__[1:]:
            if baseClass is ScipionSet:
                continue
            if self._isSetClass(baseClass):
                return baseClass

        if self._isSetClass(runtimeClass):
            return runtimeClass

        raise RuntimeError(
            "Native Scipion Set class could not be resolved for %s"
            % runtimeClass.__name__
        )

    def _getObjectClass(self, sourceObject: Any) -> Type:
        getClass = getattr(sourceObject, "getClass", None)
        if callable(getClass):
            objectClass = getClass()
            if isinstance(objectClass, type):
                return objectClass
        return sourceObject.__class__

    def _copyEnabled(self, source, target) -> None:
        isEnabled = getattr(source, "isEnabled", None)
        setEnabled = getattr(target, "setEnabled", None)
        if not callable(isEnabled) or not callable(setEnabled):
            return

        try:
            setEnabled(bool(isEnabled()))
        except Exception:
            pass

    def _buildNestedPrefix(self, nestedSet: ScipionSet) -> str:
        tableId = self._getRuntimeInfo(nestedSet).get("tableId")
        if tableId is not None:
            return "Table%s" % tableId

        getObjId = getattr(nestedSet, "getObjId", None)
        objId = getObjId() if callable(getObjId) else None
        className = self._sanitizePathPart(nestedSet.getClassName())
        suffix = str(objId) if objId is not None else uuid.uuid4().hex[:8]
        return "%s%s" % (className or "NestedSet", suffix)

    @staticmethod
    def _isSetClass(objectClass) -> bool:
        if not isinstance(objectClass, type):
            return False
        try:
            return issubclass(objectClass, ScipionSet)
        except TypeError:
            return False

    @staticmethod
    def _sanitizePathPart(value) -> str:
        return re.sub(
            r"[^A-Za-z0-9_.-]+",
            "_",
            str(value or "").strip(),
        ).strip("_")

    @staticmethod
    def _removeSqliteFiles(path: Optional[str]) -> None:
        if not path:
            return

        for candidate in (
                str(path),
                "%s-journal" % path,
                "%s-wal" % path,
                "%s-shm" % path,
        ):
            try:
                if os.path.exists(candidate):
                    os.remove(candidate)
            except Exception:
                pass