import logging
import os
import re
import tempfile
import threading
import uuid
from collections.abc import Mapping
from typing import Any, Dict, Optional, Type

from pyworkflow.object import Set as ScipionSet
from app.backend.mapper.postgresql_scipion_item_hydrator import (
    getPostgresqlRuntimeParent,
)

logger = logging.getLogger(__name__)


class PostgresqlRuntimeSetSqliteMaterializer:
    """Create a temporary SQLite compatibility snapshot from a runtime PG Set."""

    DIRECTORY_NAME = "postgresql-runtime-sets"
    MATERIALIZED_PATH_PROPERTY = "materializedFileName"

    def __init__(self):
        # RLock allows a recursive call to reach our
        # explicit recursion guard instead of hanging
        # forever while waiting for the same thread.
        self._lock = threading.RLock()

        self._materializingSetIdentities = set()

    def materialize(
            self,
            runtimeSet: ScipionSet,
    ) -> str:
        runtimeSetIdentity = id(
            runtimeSet
        )

        with self._lock:
            cachedPath = self._getCachedPath(
                runtimeSet
            )

            if cachedPath is not None:
                return cachedPath

            if (
                    runtimeSetIdentity
                    in self._materializingSetIdentities
            ):
                runtimeInfo = self._getRuntimeInfo(
                    runtimeSet
                )

                raise RuntimeError(
                    "Recursive PostgreSQL SQLite "
                    "materialization detected. "
                    "className=%s setId=%s tableId=%s"
                    % (
                        runtimeSet.getClassName(),
                        runtimeInfo.get(
                            "setId"
                        ),
                        runtimeInfo.get(
                            "tableId"
                        ),
                    )
                )

            self._materializingSetIdentities.add(
                runtimeSetIdentity
            )

            materializedPath = None
            targetSet = None

            try:
                # PostgreSQL is the canonical source of truth.
                #
                # Never reuse a persistent SQLite file from the
                # project or protocol directory. Compatibility
                # snapshots always live in our managed temporary
                # directory.
                materializedPath = (
                    self._buildMaterializedPath(
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

    def openWritable(
            self,
            runtimeSet: ScipionSet,
    ) -> ScipionSet:
        """
        Open a native writable execution Set from a PostgreSQL snapshot.

        The returned object does not use PostgresqlRuntimeSetMixin and
        therefore supports append(), update(), write() and enableAppend().
        """
        materializedPath = (
            self.materialize(
                runtimeSet
            )
        )

        classes = (
            self._getRuntimeClasses(
                runtimeSet
            )
        )

        nativeSetClass = (
            self._getNativeSetClass(
                runtimeSet
            )
        )

        writableSet = self._openSet(
            setClass=nativeSetClass,
            fileName=materializedPath,
            classes=classes,
        )

        try:
            mapper = (
                writableSet._getMapper()
            )

            # Empty native sets may not have a
            # Properties table yet.
            if mapper.hasProperty(
                    "self"
            ):
                writableSet.loadAllProperties()

            self._copyRuntimeIdentity(
                sourceSet=runtimeSet,
                targetSet=writableSet,
            )

            writableSet.enableAppend()

            return writableSet

        except Exception:
            try:
                writableSet.close()
            except Exception:
                pass

            raise

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

        managedRoot = os.path.realpath(
            os.path.join(
                tempfile.gettempdir(),
                self.DIRECTORY_NAME,
            )
        )

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
    ) -> None:
        materializedPath = str(materializedPath)
        runtimeSet._postgresqlMaterializedFileName = materializedPath

        properties = self._getRuntimeProperties(runtimeSet)
        properties[self.MATERIALIZED_PATH_PROPERTY] = materializedPath
        runtimeSet._postgresqlRuntimeProperties = properties

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
        targetSet.load()
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
        sourceClasses = (
                self._getRuntimeClasses(
                    sourceSet
                )
                or classes
        )

        for sourceItem in self._iterSourceItems(
                sourceSet
        ):
            targetItem = self._cloneItem(
                sourceItem,
                sourceClasses,
            )

            targetSet.append(
                targetItem
            )

            if not isinstance(
                    sourceItem,
                    ScipionSet,
            ):
                continue

            self._ensureNestedMapper(
                targetParentSet=targetSet,
                targetNestedSet=targetItem,
                classes=sourceClasses,
            )

            try:
                self._copySetItems(
                    sourceSet=sourceItem,
                    targetSet=targetItem,
                    classes=sourceClasses,
                )

                targetItem.write(
                    properties=False
                )

                targetSet.update(
                    targetItem
                )
            finally:
                # The nested mapper shares the root SQLite connection.
                # Detach it without closing the shared connection.
                targetItem._mapper = None

        self._ensureSetSchema(
            sourceSet=sourceSet,
            targetSet=targetSet,
            classes=sourceClasses,
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
            tempfile.gettempdir(),
            self.DIRECTORY_NAME,
            "worker-%s" % os.getpid(),
            fileName,
        )

    def _findPathOwner(self, runtimeSet: ScipionSet):
        current = runtimeSet
        visited = set()

        while current is not None:
            currentId = id(current)
            if currentId in visited:
                break
            visited.add(currentId)

            parent = (
                getPostgresqlRuntimeParent(
                    current
                )
            )
            if parent is None:
                break

            if callable(getattr(parent, "getExtraPath", None)):
                return parent

            current = parent

        return None

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

    def _copyRuntimeIdentity(
            self,
            sourceSet: ScipionSet,
            targetSet: ScipionSet,
    ) -> None:
        getObjId = getattr(
            sourceSet,
            "getObjId",
            None,
        )

        if callable(getObjId):
            objId = getObjId()

            if objId is not None:
                targetSet.setObjId(
                    objId
                )

        getObjName = getattr(
            sourceSet,
            "getObjName",
            None,
        )

        setName = getattr(
            targetSet,
            "setName",
            None,
        )

        if (
                callable(getObjName)
                and callable(setName)
        ):
            objName = getObjName()

            if objName:
                setName(
                    str(objName)
                )

        getLabel = getattr(
            sourceSet,
            "getObjLabel",
            None,
        )

        setLabel = getattr(
            targetSet,
            "setObjLabel",
            None,
        )

        if (
                callable(getLabel)
                and callable(setLabel)
        ):
            setLabel(
                getLabel() or ""
            )

        getComment = getattr(
            sourceSet,
            "getObjComment",
            None,
        )

        setComment = getattr(
            targetSet,
            "setObjComment",
            None,
        )

        if (
                callable(getComment)
                and callable(setComment)
        ):
            setComment(
                getComment() or ""
            )

        getCreation = getattr(
            sourceSet,
            "getObjCreation",
            None,
        )

        setCreation = getattr(
            targetSet,
            "setObjCreation",
            None,
        )

        if (
                callable(getCreation)
                and callable(setCreation)
        ):
            setCreation(
                getCreation()
            )

        self._copyEnabled(
            sourceSet,
            targetSet,
        )

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