import os
import re
import tempfile
import threading
import uuid
from collections.abc import Mapping
from typing import Any, Dict, Optional, Type

from pyworkflow.object import Set as ScipionSet


class PostgresqlRuntimeSetSqliteMaterializer:
    """Create a temporary SQLite compatibility snapshot from a runtime PG Set."""

    DIRECTORY_NAME = "postgresql-runtime-sets"
    MATERIALIZED_PATH_PROPERTY = "materializedFileName"

    def __init__(self):
        self._lock = threading.Lock()

    def materialize(self, runtimeSet: ScipionSet) -> str:
        with self._lock:
            cachedPath = self._getCachedPath(runtimeSet)
            if cachedPath is not None:
                return cachedPath

            materializedPath = self._buildMaterializedPath(runtimeSet)
            os.makedirs(os.path.dirname(materializedPath), exist_ok=True)
            self._removeSqliteFiles(materializedPath)

            targetSet = None
            try:
                classes = self._getRuntimeClasses(runtimeSet)
                nativeSetClass = self._getNativeSetClass(runtimeSet)

                targetSet = self._openSet(
                    setClass=nativeSetClass,
                    fileName=materializedPath,
                    classes=classes,
                )
                self._copySetMetadata(runtimeSet, targetSet)
                self._copySetItems(runtimeSet, targetSet, classes)
                targetSet.write()
                targetSet.close()
                targetSet = None
            except Exception:
                if targetSet is not None:
                    try:
                        targetSet.close()
                    except Exception:
                        pass
                self._removeSqliteFiles(materializedPath)
                raise

            self._rememberMaterializedPath(runtimeSet, materializedPath)
            return materializedPath

    def _getCachedPath(self, runtimeSet: ScipionSet) -> Optional[str]:
        cachedPath = getattr(
            runtimeSet,
            "_postgresqlMaterializedFileName",
            None,
        )
        if not cachedPath:
            cachedPath = self._getRuntimeProperties(runtimeSet).get(
                self.MATERIALIZED_PATH_PROPERTY
            )

        if cachedPath and os.path.isfile(str(cachedPath)):
            return str(cachedPath)
        return None

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

        for sourceItem in sourceSet.iterItems():
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
            # Do not close it: detach it so Set.__del__() cannot
            # close the root connection when targetItem is destroyed.
            targetItem._mapper = None

        self._ensureSetSchema(
            sourceSet=sourceSet,
            targetSet=targetSet,
            classes=sourceClasses,
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

    def _buildMaterializedPath(self, runtimeSet: ScipionSet) -> str:
        info = self._getRuntimeInfo(runtimeSet)
        setId = info.get("setId")
        tableId = info.get("tableId")

        if tableId is not None:
            identity = "table-%s" % tableId
        elif setId is not None:
            identity = "set-%s" % setId
        else:
            identity = "set"

        className = self._sanitizePathPart(runtimeSet.getClassName())
        fileName = "%s-%s-%s.sqlite" % (
            className or "ScipionSet",
            identity,
            uuid.uuid4().hex[:12],
        )

        owner = self._findPathOwner(runtimeSet)
        if owner is not None:
            try:
                return str(
                    owner.getExtraPath(self.DIRECTORY_NAME, fileName)
                )
            except Exception:
                pass

        return os.path.join(
            tempfile.gettempdir(),
            self.DIRECTORY_NAME,
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

            parent = getattr(current, "_objParent", None)
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