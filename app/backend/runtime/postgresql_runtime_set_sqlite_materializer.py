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
import os
import re
import tempfile
import threading
import uuid
from typing import Any, Optional, Type

from pyworkflow.object import Set as ScipionSet


class PostgresqlRuntimeSetSqliteMaterializer:
    """
    Materialize a read-only PostgreSQL runtime Set as a temporary
    Scipion-compatible SQLite snapshot.

    PostgreSQL remains the active runtime mapper. The SQLite file is generated
    only for legacy code that explicitly requires Set.getFileName().
    """

    DIRECTORY_NAME = "postgresql-runtime-sets"

    def __init__(self):
        self._lock = threading.Lock()

    def materialize(
            self,
            runtimeSet: ScipionSet,
    ) -> str:
        with self._lock:
            cachedPath = getattr(
                runtimeSet,
                "_postgresqlMaterializedFileName",
                None,
            )

            if cachedPath and os.path.isfile(cachedPath):
                return str(cachedPath)

            materializedPath = self._buildMaterializedPath(
                runtimeSet
            )

            directory = os.path.dirname(
                materializedPath
            )

            if directory:
                os.makedirs(
                    directory,
                    exist_ok=True,
                )

            targetSet = None

            try:
                nativeSetClass = self._getNativeSetClass(
                    runtimeSet
                )

                targetSet = nativeSetClass(
                    filename=materializedPath
                )

                self._copySetMetadata(
                    sourceSet=runtimeSet,
                    targetSet=targetSet,
                )

                self._copySetItems(
                    sourceSet=runtimeSet,
                    targetSet=targetSet,
                )

                targetSet.write()
                targetSet.close()
                targetSet = None

            except Exception:
                if targetSet is not None:
                    try:
                        targetSet.close()
                    except Exception:
                        pass

                self._removeFile(
                    materializedPath
                )

                raise

            runtimeSet._postgresqlMaterializedFileName = (
                materializedPath
            )

            return materializedPath

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
            ],
        )

        self._copyEnabled(
            source=sourceSet,
            target=targetSet,
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

        if callable(getObjName) and callable(setName):
            objName = getObjName()

            if objName:
                setName(
                    str(objName)
                )

    def _copySetItems(
            self,
            sourceSet: ScipionSet,
            targetSet: ScipionSet,
    ) -> None:
        for sourceItem in sourceSet.iterItems():
            targetItem = self._cloneItem(
                sourceItem
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
            )

            self._copySetItems(
                sourceSet=sourceItem,
                targetSet=targetItem,
            )

            targetItem.write(
                properties=False
            )

            targetSet.update(
                targetItem
            )

    def _cloneItem(
            self,
            sourceItem,
    ):
        if isinstance(
                sourceItem,
                ScipionSet,
        ):
            nativeItemClass = self._getNativeSetClass(
                sourceItem
            )

            targetItem = nativeItemClass()

            targetItem.copy(
                sourceItem,
                copyId=True,
                ignoreAttrs=[
                    "_mapperPath",
                    "_size",
                ],
            )
        else:
            itemClass = self._getObjectClass(
                sourceItem
            )

            targetItem = itemClass()

            try:
                targetItem.copy(
                    sourceItem,
                    copyId=True,
                    copyEnable=True,
                )
            except TypeError:
                targetItem.copy(
                    sourceItem,
                    copyId=True,
                )

        self._copyEnabled(
            source=sourceItem,
            target=targetItem,
        )

        return targetItem

    def _ensureNestedMapper(
            self,
            targetParentSet: ScipionSet,
            targetNestedSet: ScipionSet,
    ) -> None:
        if getattr(
                targetNestedSet,
                "_mapper",
                None,
        ) is not None:
            return

        mapperPath = getattr(
            targetNestedSet,
            "_mapperPath",
            None,
        )

        if mapperPath is None:
            raise RuntimeError(
                "Nested Scipion Set does not expose _mapperPath"
            )

        if mapperPath.isEmpty():
            mapperPath.set(
                "%s,%s"
                % (
                    targetParentSet.getFileName(),
                    self._buildNestedPrefix(
                        targetNestedSet
                    ),
                )
            )

        targetNestedSet.load()

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
            identity = "table-%s" % tableId
        elif setId is not None:
            identity = "set-%s" % setId
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

        owner = self._findPathOwner(
            runtimeSet
        )

        if owner is not None:
            try:
                return str(
                    owner.getExtraPath(
                        self.DIRECTORY_NAME,
                        fileName,
                    )
                )
            except Exception:
                pass

        return os.path.join(
            tempfile.gettempdir(),
            self.DIRECTORY_NAME,
            fileName,
        )

    def _findPathOwner(
            self,
            runtimeSet: ScipionSet,
    ):
        current = runtimeSet
        visited = set()

        while current is not None:
            currentId = id(
                current
            )

            if currentId in visited:
                break

            visited.add(
                currentId
            )

            parent = getattr(
                current,
                "_objParent",
                None,
            )

            if parent is None:
                break

            getExtraPath = getattr(
                parent,
                "getExtraPath",
                None,
            )

            if callable(getExtraPath):
                return parent

            current = parent

        return None

    def _getRuntimeInfo(
            self,
            runtimeSet: ScipionSet,
    ) -> Dict[str, Any]:
        info = getattr(
            runtimeSet,
            "_postgresqlRuntimeInfo",
            {},
        )

        if isinstance(info, dict):
            return dict(info)

        return {}

    def _getNativeSetClass(
            self,
            runtimeSet: ScipionSet,
    ) -> Type:
        nativeSetClass = getattr(
            runtimeSet,
            "_postgresqlNativeSetClass",
            None,
        )

        if isinstance(nativeSetClass, type):
            try:
                if issubclass(
                        nativeSetClass,
                        ScipionSet,
                ):
                    return nativeSetClass
            except TypeError:
                pass

        runtimeClass = runtimeSet.__class__

        for baseClass in runtimeClass.__mro__[1:]:
            if baseClass is ScipionSet:
                continue

            try:
                isSetClass = issubclass(
                    baseClass,
                    ScipionSet,
                )
            except TypeError:
                isSetClass = False

            if isSetClass:
                return baseClass

        raise RuntimeError(
            "Native Scipion Set class could not be resolved for %s"
            % runtimeClass.__name__
        )

    def _getObjectClass(
            self,
            sourceObject: Any,
    ) -> Type:
        getClass = getattr(
            sourceObject,
            "getClass",
            None,
        )

        if callable(getClass):
            objectClass = getClass()

            if isinstance(
                    objectClass,
                    type,
            ):
                return objectClass

        return sourceObject.__class__

    def _copyEnabled(
            self,
            source,
            target,
    ) -> None:
        isEnabled = getattr(
            source,
            "isEnabled",
            None,
        )

        setEnabled = getattr(
            target,
            "setEnabled",
            None,
        )

        if not callable(isEnabled) or not callable(setEnabled):
            return

        try:
            setEnabled(
                bool(
                    isEnabled()
                )
            )
        except Exception:
            pass

    def _buildNestedPrefix(
            self,
            nestedSet: ScipionSet,
    ) -> str:
        getObjId = getattr(
            nestedSet,
            "getObjId",
            None,
        )

        objId = (
            getObjId()
            if callable(getObjId)
            else None
        )

        className = self._sanitizePathPart(
            nestedSet.getClassName()
        )

        suffix = (
            str(objId)
            if objId is not None
            else uuid.uuid4().hex[:8]
        )

        return "%s%s" % (
            className or "NestedSet",
            suffix,
        )

    @staticmethod
    def _sanitizePathPart(
            value,
    ) -> str:
        return re.sub(
            r"[^A-Za-z0-9_.-]+",
            "_",
            str(value or "").strip(),
        ).strip("_")

    @staticmethod
    def _removeFile(
            path: Optional[str],
    ) -> None:
        if not path:
            return

        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass