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
from types import SimpleNamespace
from typing import Any, Dict, Optional, Type

from pyworkflow.object import Set as ScipionSet

from app.backend.mapper.postgresql_scipion_item_hydrator import (
    PostgresqlScipionItemHydrator,
)
from app.backend.mapper.postgresql_set_runtime_mapper import (
    PostgresqlSetRuntimeMapper,
)
from app.backend.mapper.scipion_set_mapper import (
    ScipionSetPostgresqlMapper,
)
from app.backend.runtime.postgresql_runtime_set_sqlite_materializer import (
    PostgresqlRuntimeSetSqliteMaterializer,
)
from app.backend.runtime.protocol_graph_repository import (
    ProtocolGraphRepository,
)

class PostgresqlRuntimeSetMixin:
    """
    Runtime behavior added to native Scipion SetOf... classes.

    The original Scipion API is preserved, but load() reconstructs the
    PostgreSQL mapper instead of opening the legacy SQLite file.
    """

    def load(self):
        mapperFactory = getattr(
            self,
            "_postgresqlMapperFactory",
            None,
        )

        if not callable(mapperFactory):
            raise RuntimeError(
                "PostgreSQL runtime set does not have a mapper factory."
            )

        self._mapper = mapperFactory()
        self._size.set(self._mapper.count())
        self._idCount = self._mapper.maxId()

        return self

    def close(self):
        mapper = getattr(
            self,
            "_mapper",
            None,
        )

        if mapper is not None:
            mapper.close()

        self._mapper = None

    def getFileName(self):
        materializer = getattr(
            self,
            "_postgresqlSqliteMaterializer",
            None,
        )

        if materializer is None:
            raise RuntimeError(
                "PostgreSQL runtime set does not have a SQLite materializer."
            )

        return materializer.materialize(
            self
        )

    def getPostgresqlRuntimeProperties(self):
        properties = getattr(
            self,
            "_postgresqlRuntimeProperties",
            {},
        )

        return (
            dict(properties)
            if isinstance(properties, dict)
            else {}
        )

    def getLegacyFileName(self):
        return self.getPostgresqlRuntimeProperties().get(
            "fileName"
        )

    def getLegacyMapperPath(self):
        return self.getPostgresqlRuntimeProperties().get(
            "_mapperPath"
        )

    def getPostgresqlRuntimeInfo(self):
        info = getattr(
            self,
            "_postgresqlRuntimeInfo",
            {},
        )

        return (
            dict(info)
            if isinstance(info, dict)
            else {}
        )

    def isPostgresqlRuntimeOutput(self):
        return True

    def write(self, properties=True):
        raise RuntimeError(
            "PostgreSQL runtime input sets are read-only."
        )


class PostgresqlRuntimeSetFactory:
    """
    Build native Scipion SetOf... instances backed by PostgreSQL.
    """

    SKIPPED_PROPERTY_PATHS = {
        "_mapperPath",
        "_size",
    }

    _runtimeClassCache: Dict[Type, Type] = {}

    def __init__(
            self,
    ):
        self.protocolGraphRepository = (
            ProtocolGraphRepository()
        )

        self._runtimeSetsByIdentity = {}
        self._runtimeProtocolsByIdentity = {}

        self._resolvedPointerTargets = {}
        self._resolvingPointerTargets = set()

    def build(
            self,
            db,
            parent,
            outputName: str,
            outputInfo: Dict[str, Any],
            classes: Optional[Dict[str, Type]] = None,
    ):
        if db is None:
            raise ValueError("db is required")

        info = dict(
            outputInfo or {}
        )

        setId = info.get("setId")
        setClassName = (
            info.get("className")
            or info.get("setClassName")
        )
        itemClassName = info.get(
            "itemClassName"
        )

        if setId is None:
            raise ValueError(
                "PostgreSQL runtime set requires setId"
            )

        if not setClassName:
            raise ValueError(
                "PostgreSQL runtime set requires className"
            )

        classRegistry = self._loadClasses(
            classes
        )

        nativeSetClass = classRegistry.get(
            str(setClassName)
        )

        if nativeSetClass is None:
            raise ValueError(
                "Scipion set class '%s' was not found in Domain.getObjects()"
                % setClassName
            )

        itemClassName = self._resolveItemClassName(
            itemClassName=itemClassName,
            nativeSetClass=nativeSetClass,
        )

        if not itemClassName:
            raise ValueError(
                "PostgreSQL runtime set requires itemClassName"
            )

        properties = self._normalizeProperties(
            info.get("properties")
        )

        runtimeSetClass = self._getRuntimeSetClass(
            nativeSetClass
        )

        runtimeSet = runtimeSetClass()

        self._configureRuntimeSetCompatibility(
            runtimeSet=runtimeSet,
            nativeSetClass=nativeSetClass,
            runtimeInfo=info,
            runtimeProperties=properties,
            classRegistry=classRegistry,
        )

        self._applyBasicMetadata(
            runtimeSet=runtimeSet,
            parent=parent,
            outputName=outputName,
            outputInfo=info,
        )

        self._hydrateSetProperties(
            runtimeSet=runtimeSet,
            properties=properties,
        )

        setMapper = ScipionSetPostgresqlMapper(
            db=db
        )

        logicalTablesByParentId = (
            self._loadLogicalTablesByParentItemId(
                setMapper=setMapper,
                setId=int(setId),
            )
        )

        itemClassRegistry = dict(
            classRegistry
        )

        nativeItemClass = classRegistry.get(
            str(itemClassName)
        )

        if (
                logicalTablesByParentId
                and self._isScipionSetClass(
            nativeItemClass
        )
        ):
            itemClassRegistry[
                str(itemClassName)
            ] = self._getRuntimeSetClass(
                nativeItemClass
            )

        columns = setMapper.getStoredSetColumns(
            int(setId)
        )

        itemHydrator = PostgresqlScipionItemHydrator(
            itemClassName=str(itemClassName),
            columns=columns,
            parent=runtimeSet,
            classes=itemClassRegistry,
            pointerResolver=(
                self._buildPointerResolver(
                    db=db,
                    runtimeSet=runtimeSet,
                    classRegistry=classRegistry,
                )
            ),
        )

        def buildItem(row):
            row = dict(
                row or {}
            )

            item = itemHydrator.build(
                row
            )

            if (
                    isinstance(
                        item,
                        ScipionSet,
                    )
                    and self._isScipionSetClass(
                nativeItemClass
            )
            ):
                runtimeValues = getattr(
                    item,
                    "_postgresqlRuntimeValues",
                    {},
                )

                self._configureRuntimeSetCompatibility(
                    runtimeSet=item,
                    nativeSetClass=nativeItemClass,
                    runtimeInfo={
                        "setId": int(setId),
                        "parentItemId": self._toOptionalInt(
                            row.get("scipionItemId")
                        ),
                        "className": item.getClassName(),
                    },
                    runtimeProperties=(
                        runtimeValues
                        if isinstance(runtimeValues, dict)
                        else {}
                    ),
                    classRegistry=classRegistry,
                )

            self._attachLogicalTableMapper(
                db=db,
                setMapper=setMapper,
                item=item,
                row=row,
                logicalTablesByParentId=(
                    logicalTablesByParentId
                ),
                classRegistry=classRegistry,
            )

            return item

        def mapperFactory():
            return PostgresqlSetRuntimeMapper(
                db=db,
                setId=int(setId),
                itemBuilder=buildItem,
            )

        runtimeSet._postgresqlMapperFactory = (
            mapperFactory
        )

        runtimeSet.load()

        self._cacheRuntimeSet(
            runtimeSet
        )

        return runtimeSet

    def _resolveItemClassName(
            self,
            itemClassName,
            nativeSetClass: Type,
    ) -> Optional[str]:
        storedName = str(
            itemClassName or ""
        ).strip()

        if (
                storedName
                and storedName.lower() != "unknown"
        ):
            return storedName

        itemType = getattr(
            nativeSetClass,
            "ITEM_TYPE",
            None,
        )

        if isinstance(itemType, str):
            itemType = itemType.strip()
            return itemType or None

        declaredName = getattr(
            itemType,
            "__name__",
            None,
        )

        if declaredName:
            return str(declaredName)

        return None

    def _configureRuntimeSetCompatibility(
            self,
            runtimeSet: ScipionSet,
            nativeSetClass: Type,
            runtimeInfo: Optional[Dict[str, Any]] = None,
            runtimeProperties: Optional[Dict[str, Any]] = None,
            classRegistry: Optional[Dict[str, Type]] = None,
    ) -> None:
        runtimeSet._postgresqlNativeSetClass = (
            nativeSetClass
        )

        runtimeSet._postgresqlRuntimeInfo = dict(
            runtimeInfo or {}
        )

        runtimeSet._postgresqlRuntimeProperties = (
            self._normalizeProperties(
                runtimeProperties
            )
        )

        runtimeSet._postgresqlRuntimeClasses = dict(
            classRegistry or {}
        )

        runtimeSet._postgresqlSqliteMaterializer = (
            PostgresqlRuntimeSetSqliteMaterializer()
        )

        runtimeSet._postgresqlMaterializedFileName = None

    def _loadLogicalTablesByParentItemId(
            self,
            setMapper,
            setId: int,
    ) -> Dict[int, Dict[str, Any]]:
        result: Dict[int, Dict[str, Any]] = {}

        tables = setMapper.listStoredSetTables(
            int(setId)
        )

        for table in tables or []:
            table = dict(
                table or {}
            )

            if table.get("tableKind") != "child":
                continue

            parentItemId = self._toOptionalInt(
                table.get("parentItemId")
            )

            if parentItemId is None:
                continue

            parentItemId = int(
                parentItemId
            )

            if parentItemId in result:
                raise ValueError(
                    "More than one PostgreSQL logical table "
                    "was found for parent item %s"
                    % parentItemId
                )

            result[parentItemId] = table

        return result

    def _attachLogicalTableMapper(
            self,
            db,
            setMapper,
            item,
            row: Dict[str, Any],
            logicalTablesByParentId:
            Dict[int, Dict[str, Any]],
            classRegistry: Dict[str, Type],
    ) -> None:
        itemId = self._toOptionalInt(
            row.get("scipionItemId")
        )

        if itemId is None:
            return

        table = logicalTablesByParentId.get(
            int(itemId)
        )

        if table is None:
            return

        if not isinstance(
                item,
                ScipionSet,
        ):
            raise TypeError(
                "PostgreSQL logical table %s belongs to item %s, "
                "but hydrated class %s is not a Scipion Set"
                % (
                    table.get("id"),
                    itemId,
                    item.__class__.__name__,
                )
            )

        tableId = self._toOptionalInt(
            table.get("id")
        )

        childItemClassName = table.get(
            "itemClassName"
        )

        if tableId is None:
            raise ValueError(
                "Logical table for item %s does not have an id"
                % itemId
            )

        if not childItemClassName:
            raise ValueError(
                "Logical table %s does not define itemClassName"
                % tableId
            )

        tableProperties = self._normalizeProperties(
            table.get("properties")
        )

        runtimeValues = getattr(
            item,
            "_postgresqlRuntimeValues",
            {},
        )

        nestedProperties = dict(
            runtimeValues
            if isinstance(runtimeValues, dict)
            else {}
        )

        nestedProperties.update(
            tableProperties
        )

        item._postgresqlRuntimeInfo = {
            "setId": table.get("setId"),
            "tableId": int(tableId),
            "parentItemId": int(itemId),
            "className": item.getClassName(),
            "itemClassName": str(
                childItemClassName
            ),
            "properties": tableProperties,
        }

        item._postgresqlRuntimeProperties = (
            nestedProperties
        )

        def mapperFactory():
            childColumns = (
                setMapper.getStoredSetTableColumns(
                    int(tableId)
                )
            )

            childHydrator = (
                PostgresqlScipionItemHydrator(
                    itemClassName=str(
                        childItemClassName
                    ),
                    columns=childColumns,
                    parent=item,
                    classes=classRegistry,
                    pointerResolver=(
                        self._buildPointerResolver(
                            db=db,
                            runtimeSet=item,
                            classRegistry=classRegistry,
                        )
                    ),
                )
            )

            return PostgresqlSetRuntimeMapper(
                db=db,
                tableId=int(tableId),
                itemBuilder=childHydrator,
            )

        item._postgresqlMapperFactory = (
            mapperFactory
        )

        # Keep loading lazy. The mapper will be created when iterItems(),
        # getFirstItem(), getItem() or another Set operation needs it.
        item._mapper = None

    def _buildLocalPointerResolver(
            self,
            runtimeSet: ScipionSet,
    ):
        resolvedTargets = {}
        resolvingTargets = set()

        def resolvePointer(
                reference: Dict[str, Any],
        ):
            targetObjectId = self._toOptionalInt(
                reference.get(
                    "targetObjectId"
                )
            )

            targetParentObjectId = (
                self._toOptionalInt(
                    reference.get(
                        "targetParentObjectId"
                    )
                )
            )

            runtimeSetObjectId = (
                self._toOptionalInt(
                    runtimeSet.getObjId()
                )
            )

            if not isinstance(
                    targetObjectId,
                    int,
            ):
                return None

            if not isinstance(
                    targetParentObjectId,
                    int,
            ):
                return None

            if not isinstance(
                    runtimeSetObjectId,
                    int,
            ):
                return None

            # This resolver only owns pointers to items
            # contained in this runtime set.
            if (
                    targetParentObjectId
                    != runtimeSetObjectId
            ):
                return None

            targetKey = (
                targetParentObjectId,
                targetObjectId,
            )

            if targetKey in resolvedTargets:
                return resolvedTargets[
                    targetKey
                ]

            # Avoid infinite recursion for circular pointers:
            # item A -> item B -> item A.
            if targetKey in resolvingTargets:
                return None

            resolvingTargets.add(
                targetKey
            )

            try:
                mapper = runtimeSet._getMapper()

                target = mapper.selectById(
                    targetObjectId
                )

                if target is not None:
                    resolvedTargets[
                        targetKey
                    ] = target

                return target
            finally:
                resolvingTargets.discard(
                    targetKey
                )

        return resolvePointer

    def _buildPointerResolver(
            self,
            db,
            runtimeSet: ScipionSet,
            classRegistry: Dict[str, Type],
    ):
        localResolver = (
            self._buildLocalPointerResolver(
                runtimeSet
            )
        )

        def resolvePointer(
                reference: Dict[str, Any],
        ):
            targetObjectId = self._toOptionalInt(
                reference.get(
                    "targetObjectId"
                )
            )

            targetParentObjectId = (
                self._toOptionalInt(
                    reference.get(
                        "targetParentObjectId"
                    )
                )
            )

            runtimeSetObjectId = (
                self._toOptionalInt(
                    runtimeSet.getObjId()
                )
            )

            if not isinstance(
                    targetObjectId,
                    int,
            ):
                return None

            if not isinstance(
                    targetParentObjectId,
                    int,
            ):
                return None

            if (
                    isinstance(
                        runtimeSetObjectId,
                        int,
                    )
                    and targetParentObjectId
                    == runtimeSetObjectId
            ):
                return localResolver(
                    reference
                )

            return self._resolveExternalPointerTarget(
                db=db,
                runtimeSet=runtimeSet,
                classRegistry=classRegistry,
                targetParentObjectId=(
                    targetParentObjectId
                ),
                targetObjectId=targetObjectId,
            )

        return resolvePointer

    def _resolveExternalPointerTarget(
            self,
            db,
            runtimeSet: ScipionSet,
            classRegistry: Dict[str, Type],
            targetParentObjectId: int,
            targetObjectId: int,
    ):
        projectId = self._getRuntimeProjectId(
            runtimeSet
        )

        if not isinstance(
                projectId,
                int,
        ):
            return None

        targetKey = (
            projectId,
            int(targetParentObjectId),
            int(targetObjectId),
        )

        if targetKey in self._resolvedPointerTargets:
            return self._resolvedPointerTargets[
                targetKey
            ]

        if targetKey in self._resolvingPointerTargets:
            return None

        self._resolvingPointerTargets.add(
            targetKey
        )

        try:
            sourceProtocol = (
                self._findProtocolParent(
                    runtimeSet
                )
            )

            runtimeMapper = (
                self._getProtocolMapper(
                    sourceProtocol
                )
            )

            repositoryMapper = runtimeMapper

            if (
                    repositoryMapper is None
                    or getattr(
                repositoryMapper,
                "db",
                None,
            ) is None
            ):
                repositoryMapper = SimpleNamespace(
                    db=db
                )

            targetOutputInfo = (
                self.protocolGraphRepository
                .getPersistedSetOutputRowByRuntimeObjectId(
                    mapper=repositoryMapper,
                    projectId=projectId,
                    runtimeObjectId=(
                        targetParentObjectId
                    ),
                )
            )

            if targetOutputInfo is None:
                return None

            targetSet = self._getCachedRuntimeSet(
                projectId=projectId,
                runtimeObjectId=(
                    targetParentObjectId
                ),
            )

            if targetSet is None:
                targetProtocol = (
                    self._resolveRuntimeProtocol(
                        projectId=projectId,
                        sourceProtocol=sourceProtocol,
                        runtimeMapper=runtimeMapper,
                        targetOutputInfo=(
                            targetOutputInfo
                        ),
                    )
                )

                if targetProtocol is None:
                    return None

                outputName = str(
                    targetOutputInfo.get(
                        "outputName"
                    )
                    or ""
                ).strip()

                if not outputName:
                    return None

                attachedSet = getattr(
                    targetProtocol,
                    outputName,
                    None,
                )

                if self._isMatchingRuntimeSet(
                        runtimeSet=attachedSet,
                        runtimeObjectId=(
                                targetParentObjectId
                        ),
                ):
                    targetSet = attachedSet

                else:
                    targetSet = self.build(
                        db=db,
                        parent=targetProtocol,
                        outputName=outputName,
                        outputInfo=targetOutputInfo,
                        classes=classRegistry,
                    )

                    setattr(
                        targetProtocol,
                        outputName,
                        targetSet,
                    )

                self._cacheRuntimeSet(
                    targetSet
                )

            target = self._selectRuntimeSetItem(
                runtimeSet=targetSet,
                itemId=targetObjectId,
            )

            if target is not None:
                self._resolvedPointerTargets[
                    targetKey
                ] = target

            return target

        finally:
            self._resolvingPointerTargets.discard(
                targetKey
            )

    def _resolveRuntimeProtocol(
            self,
            projectId: int,
            sourceProtocol,
            runtimeMapper,
            targetOutputInfo: Dict[str, Any],
    ):
        targetProtocolId = self._toOptionalInt(
            targetOutputInfo.get(
                "protocolId"
            )
        )

        if not isinstance(
                targetProtocolId,
                int,
        ):
            return None

        sourceProtocolId = self._toOptionalInt(
            self._callOptionalMethod(
                sourceProtocol,
                "getObjId",
            )
        )

        if (
                sourceProtocol is not None
                and sourceProtocolId
                == targetProtocolId
        ):
            return sourceProtocol

        protocolKey = (
            int(projectId),
            int(targetProtocolId),
        )

        if protocolKey in self._runtimeProtocolsByIdentity:
            return self._runtimeProtocolsByIdentity[
                protocolKey
            ]

        if runtimeMapper is None:
            return None

        selector = getattr(
            runtimeMapper,
            "selectById",
            None,
        )

        if not callable(
                selector
        ):
            return None

        targetProtocol = selector(
            targetProtocolId
        )

        if targetProtocol is None:
            return None

        self._runtimeProtocolsByIdentity[
            protocolKey
        ] = targetProtocol

        return targetProtocol

    def _findProtocolParent(
            self,
            runtimeSet: ScipionSet,
    ):
        current = runtimeSet
        visited = set()

        while isinstance(
                current,
                ScipionSet,
        ):
            currentIdentity = id(
                current
            )

            if currentIdentity in visited:
                return None

            visited.add(
                currentIdentity
            )

            current = getattr(
                current,
                "_objParent",
                None,
            )

        return current

    def _getProtocolMapper(
            self,
            protocol,
    ):
        if protocol is None:
            return None

        getter = getattr(
            protocol,
            "getMapper",
            None,
        )

        if callable(
                getter
        ):
            try:
                mapper = getter()

                if mapper is not None:
                    return mapper
            except Exception:
                pass

        for attrName in (
                "_mapper",
                "mapper",
        ):
            mapper = getattr(
                protocol,
                attrName,
                None,
            )

            if mapper is not None:
                return mapper

        return None

    def _getRuntimeProjectId(
            self,
            runtimeSet: ScipionSet,
    ):
        current = runtimeSet
        visited = set()

        while current is not None:
            currentIdentity = id(
                current
            )

            if currentIdentity in visited:
                break

            visited.add(
                currentIdentity
            )

            runtimeInfo = getattr(
                current,
                "_postgresqlRuntimeInfo",
                {},
            )

            if isinstance(
                    runtimeInfo,
                    dict,
            ):
                projectId = self._toOptionalInt(
                    runtimeInfo.get(
                        "projectId"
                    )
                )

                if isinstance(
                        projectId,
                        int,
                ):
                    return projectId

            current = getattr(
                current,
                "_objParent",
                None,
            )

        protocol = self._findProtocolParent(
            runtimeSet
        )

        mapper = self._getProtocolMapper(
            protocol
        )

        return self._toOptionalInt(
            getattr(
                mapper,
                "projectId",
                None,
            )
        )

    def _cacheRuntimeSet(
            self,
            runtimeSet,
    ) -> None:
        if runtimeSet is None:
            return

        projectId = self._getRuntimeProjectId(
            runtimeSet
        )

        runtimeObjectId = self._toOptionalInt(
            self._callOptionalMethod(
                runtimeSet,
                "getObjId",
            )
        )

        if not isinstance(
                projectId,
                int,
        ):
            return

        if not isinstance(
                runtimeObjectId,
                int,
        ):
            return

        self._runtimeSetsByIdentity[
            (
                projectId,
                runtimeObjectId,
            )
        ] = runtimeSet

    def _getCachedRuntimeSet(
            self,
            projectId: int,
            runtimeObjectId: int,
    ):
        return self._runtimeSetsByIdentity.get(
            (
                int(projectId),
                int(runtimeObjectId),
            )
        )

    def _isMatchingRuntimeSet(
            self,
            runtimeSet,
            runtimeObjectId: int,
    ) -> bool:
        if not isinstance(
                runtimeSet,
                ScipionSet,
        ):
            return False

        candidateObjectId = self._toOptionalInt(
            self._callOptionalMethod(
                runtimeSet,
                "getObjId",
            )
        )

        if candidateObjectId != int(
                runtimeObjectId
        ):
            return False

        checker = getattr(
            runtimeSet,
            "isPostgresqlRuntimeOutput",
            None,
        )

        if not callable(
                checker
        ):
            return False

        try:
            return bool(
                checker()
            )
        except Exception:
            return False

    def _selectRuntimeSetItem(
            self,
            runtimeSet: ScipionSet,
            itemId: int,
    ):
        mapper = runtimeSet._getMapper()

        selector = getattr(
            mapper,
            "selectById",
            None,
        )

        if not callable(
                selector
        ):
            return None

        return selector(
            int(itemId)
        )

    @staticmethod
    def _callOptionalMethod(
            obj,
            methodName: str,
    ):
        if obj is None:
            return None

        method = getattr(
            obj,
            methodName,
            None,
        )

        if not callable(
                method
        ):
            return None

        try:
            return method()
        except Exception:
            return None

    def _isScipionSetClass(
            self,
            objectClass,
    ) -> bool:
        if not isinstance(
                objectClass,
                type,
        ):
            return False

        try:
            return issubclass(
                objectClass,
                ScipionSet,
            )
        except TypeError:
            return False

    def _getRuntimeSetClass(
            self,
            nativeSetClass: Type,
    ) -> Type:
        runtimeClass = self._runtimeClassCache.get(
            nativeSetClass
        )

        if runtimeClass is not None:
            return runtimeClass

        runtimeClass = type(
            nativeSetClass.__name__,
            (
                PostgresqlRuntimeSetMixin,
                nativeSetClass,
            ),
            {
                "__module__": nativeSetClass.__module__,
            },
        )

        self._runtimeClassCache[
            nativeSetClass
        ] = runtimeClass

        return runtimeClass

    def _loadClasses(
            self,
            extraClasses: Optional[Dict[str, Type]],
    ) -> Dict[str, Type]:
        classes: Dict[str, Type] = {}

        try:
            from pwem import Domain

            classes.update(
                Domain.getObjects() or {}
            )
        except Exception:
            pass

        if extraClasses:
            classes.update(
                extraClasses
            )

        return classes

    def _applyBasicMetadata(
            self,
            runtimeSet,
            parent,
            outputName: str,
            outputInfo: Dict[str, Any],
    ) -> None:
        if "runtimeObjectId" in outputInfo:
            runtimeObjectId = outputInfo.get(
                "runtimeObjectId"
            )
        else:
            runtimeObjectId = outputInfo.get(
                "objectId"
            )

        if runtimeObjectId is not None:
            runtimeSet.setObjId(
                self._toOptionalInt(
                    runtimeObjectId
                )
            )

        runtimeSet.setName(
            str(outputName)
        )

        runtimeSet.setObjLabel(
            str(outputName)
        )

        runtimeSet._objParent = parent

        parentIdGetter = getattr(
            parent,
            "getObjId",
            None,
        )

        if callable(parentIdGetter):
            try:
                runtimeSet._objParentId = (
                    parentIdGetter()
                )
            except Exception:
                runtimeSet._objParentId = None

    def _hydrateSetProperties(
            self,
            runtimeSet,
            properties: Dict[str, Any],
    ) -> None:
        for path, value in properties.items():
            path = str(path)

            if not path.startswith("_"):
                continue

            if path in self.SKIPPED_PROPERTY_PATHS:
                continue

            self._setExistingAttributeValue(
                runtimeSet,
                path,
                value,
            )

    def _setExistingAttributeValue(
            self,
            runtimeSet,
            path: str,
            value: Any,
    ) -> bool:
        parts = [
            part
            for part in path.split(".")
            if part
        ]

        if not parts:
            return False

        current = runtimeSet

        for part in parts:
            current = getattr(
                current,
                part,
                None,
            )

            if current is None:
                return False

        setter = getattr(
            current,
            "set",
            None,
        )

        if not callable(setter):
            return False

        setter(value)

        return True

    def _normalizeProperties(
            self,
            properties,
    ) -> Dict[str, Any]:
        if isinstance(properties, dict):
            return dict(properties)

        if isinstance(properties, str):
            try:
                parsed = json.loads(
                    properties
                )
            except Exception:
                return {}

            if isinstance(parsed, dict):
                return dict(parsed)

        return {}

    def _toOptionalInt(
            self,
            value,
    ):
        if value in (None, ""):
            return None

        try:
            return int(value)
        except (TypeError, ValueError):
            return value