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
from types import SimpleNamespace
from typing import Any, Dict, Optional, Type

from pyworkflow.object import (
    Pointer,
    PointerList,
    Set as ScipionSet,
)

from app.backend.mapper.postgresql_scipion_item_hydrator import (
    PostgresqlScipionItemHydrator,
    getPostgresqlRuntimeParent,
    setPostgresqlRuntimeParentReference,
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

logger = logging.getLogger(__name__)


class PostgresqlRuntimeSetMixin:
    """
    Runtime behavior added to native Scipion SetOf... classes.

    The original Scipion API is preserved, but load() reconstructs the
    PostgreSQL mapper instead of opening the legacy SQLite file.
    """

    def getClass(self):
        nativeSetClass = getattr(self, "_postgresqlNativeSetClass", None)

        if isinstance(nativeSetClass, type):
            return nativeSetClass

        return super().getClass()

    def load(self):
        mapperFactory = getattr(
            self,
            "_postgresqlMapperFactory",
            None,
        )

        if not callable(
                mapperFactory
        ):
            raise RuntimeError(
                "PostgreSQL runtime set does not "
                "have a mapper factory."
            )

        writable = bool(
            getattr(
                self,
                "_postgresqlWritable",
                False,
            )
        )

        # Scipion streaming closes output Sets after every
        # _updateOutputSet(). Preserve the previous access
        # mode when the same object is opened again.
        if writable:
            self._mapper = mapperFactory(
                writable=True
            )

        else:
            # Do not pass writable=False here. Clone mapper
            # factories preserve the original no-argument
            # callable contract.
            self._mapper = mapperFactory()

        self._size.set(
            self._mapper.count()
        )

        self._idCount = (
            self._mapper.maxId()
        )

        return self

    def refreshPostgresqlRuntimeState(self):
        mapper = self._getMapper()

        refreshProperties = getattr(mapper, "refreshProperties", None)

        if callable(refreshProperties):
            refreshProperties()

        self._size.set(mapper.count())
        self._idCount = mapper.maxId()
        self._refreshPostgresqlRuntimeProperties(mapper)

        return self

    def _refreshPostgresqlRuntimeProperties(self, mapper):
        getPropertyKeys = getattr(mapper, "getPropertyKeys", None)
        getProperty = getattr(mapper, "getProperty", None)

        if not callable(getPropertyKeys) or not callable(getProperty):
            return

        runtimeProperties = self.getPostgresqlRuntimeProperties()

        for propertyName in getPropertyKeys():
            propertyName = str(propertyName)

            if propertyName == "self":
                continue

            propertyValue = getProperty(propertyName)
            runtimeProperties[propertyName] = propertyValue

            if self._isPostgresqlRuntimePointerProperty(propertyName):
                continue

            currentAttribute = self

            for attributeName in propertyName.split("."):
                currentAttribute = getattr(
                    currentAttribute,
                    attributeName,
                    None,
                )

                if currentAttribute is None:
                    break

            setter = getattr(
                currentAttribute,
                "set",
                None,
            )

            if not callable(setter):
                continue

            try:
                setter(propertyValue)
            except Exception:
                logger.warning(
                    "Could not refresh PostgreSQL runtime Set property. "
                    "className=%s objectId=%s property=%s",
                    self.getClassName(),
                    self.getObjId(),
                    propertyName,
                    exc_info=True,
                )

        self._postgresqlRuntimeProperties = runtimeProperties

    def _isPostgresqlRuntimePointerProperty(self, propertyName):
        current = self

        for attributeName in str(propertyName).split("."):
            if isinstance(current, (Pointer, PointerList)):
                return True

            current = getattr(current, attributeName, None)

            if current is None:
                return False

        return isinstance(current, (Pointer, PointerList))

    def loadAllProperties(
            self,
    ):
        """
        Preserve the native streaming contract.

        Scipion protocols call loadAllProperties() expecting the
        input Set size and stream state to reflect current storage.
        """
        return (
            self
            .refreshPostgresqlRuntimeState()
        )

    def close(self):
        mapper = getattr(self, "_mapper", None)

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

    def supportsPostgresqlNativeWrite(self) -> bool:
        return bool(
            getattr(
                self,
                "_postgresqlSupportsNativeWrite",
                False,
            )
        )

    def isPostgresqlWritable(self) -> bool:
        mapper = getattr(
            self,
            "_mapper",
            None,
        )

        if mapper is None:
            return False

        checker = getattr(
            mapper,
            "isWritable",
            None,
        )

        if not callable(checker):
            return False

        return bool(
            checker()
        )

    def enablePostgresqlWrite(self):
        """
        Replace the current read-only mapper with a writable
        PostgreSQL mapper for this runtime Set.
        """
        if not self.supportsPostgresqlNativeWrite():
            raise NotImplementedError(
                "Native PostgreSQL writing is not yet "
                "supported for nested PostgreSQL Sets."
            )

        if self.isPostgresqlWritable():
            return self

        mapperFactory = getattr(
            self,
            "_postgresqlMapperFactory",
            None,
        )

        if not callable(mapperFactory):
            raise RuntimeError(
                "PostgreSQL runtime Set does not "
                "have a mapper factory."
            )

        currentMapper = getattr(
            self,
            "_mapper",
            None,
        )

        if currentMapper is not None:
            closeMapper = getattr(
                currentMapper,
                "close",
                None,
            )

            if callable(closeMapper):
                closeMapper()

        self._mapper = mapperFactory(
            writable=True
        )

        self._size.set(
            self._mapper.count()
        )

        self._idCount = (
            self._mapper.maxId()
        )

        self._postgresqlWritable = True

        return self

    def enableAppend(self):
        if not self.supportsPostgresqlNativeWrite():
            raise RuntimeError(
                "PostgreSQL runtime Set is read-only."
            )

        self.enablePostgresqlWrite()
        self._getMapper().enableAppend()

    def _preparePostgresqlAppendItem(
            self,
            item,
    ) -> None:
        """
        Preserve the metadata preparation normally performed by
        native Scipion SetOfImages/TiltSeries append methods.

        PostgreSQL persistence remains atomic and is still handled
        exclusively by PostgresqlSetRuntimeMapper.appendItem().
        """
        getContainerTsId = getattr(
            self,
            "getTsId",
            None,
        )
        setItemTsId = getattr(
            item,
            "setTsId",
            None,
        )

        if (
                callable(getContainerTsId)
                and callable(setItemTsId)
        ):
            setItemTsId(
                getContainerTsId()
            )

        getContainerSamplingRate = getattr(
            self,
            "getSamplingRate",
            None,
        )
        getItemSamplingRate = getattr(
            item,
            "getSamplingRate",
            None,
        )
        setItemSamplingRate = getattr(
            item,
            "setSamplingRate",
            None,
        )

        if (
                callable(getContainerSamplingRate)
                and callable(getItemSamplingRate)
                and callable(setItemSamplingRate)
        ):
            containerSamplingRate = (
                getContainerSamplingRate()
            )
            itemSamplingRate = (
                getItemSamplingRate()
            )

            if (
                    containerSamplingRate
                    or not itemSamplingRate
            ):
                setItemSamplingRate(
                    containerSamplingRate
                )

        containerHasAcquisition = getattr(
            self,
            "hasAcquisition",
            None,
        )
        getContainerAcquisition = getattr(
            self,
            "getAcquisition",
            None,
        )
        itemHasAcquisition = getattr(
            item,
            "hasAcquisition",
            None,
        )
        setItemAcquisition = getattr(
            item,
            "setAcquisition",
            None,
        )

        if (
                callable(containerHasAcquisition)
                and callable(getContainerAcquisition)
                and callable(itemHasAcquisition)
                and callable(setItemAcquisition)
                and containerHasAcquisition()
                and not itemHasAcquisition()
        ):
            setItemAcquisition(
                getContainerAcquisition()
            )

    def _updatePostgresqlAppendMetadata(
            self,
            item,
            wasEmpty: bool,
    ) -> None:
        """
        Restore container metadata normally updated by native
        SetOfImages.append() and TiltSeries.append().
        """
        if wasEmpty:
            getItemDim = getattr(
                item,
                "getDim",
                None,
            )
            setContainerDim = getattr(
                self,
                "setDim",
                None,
            )

            if (
                    callable(getItemDim)
                    and callable(setContainerDim)
            ):
                itemDim = getItemDim()

                if itemDim is not None:
                    setContainerDim(
                        itemDim
                    )

        for attributeName, getterName in (
                (
                    "_hasAlignment",
                    "hasTransform",
                ),
                (
                    "_hasOddEven",
                    "hasOddEven",
                ),
        ):
            targetAttribute = getattr(
                self,
                attributeName,
                None,
            )
            setter = getattr(
                targetAttribute,
                "set",
                None,
            )
            getter = getattr(
                item,
                getterName,
                None,
            )

            if (
                    callable(setter)
                    and callable(getter)
            ):
                setter(
                    bool(
                        getter()
                    )
                )

    def append(
            self,
            item,
    ) -> None:
        """
        Append through PostgreSQL while preserving the native
        Scipion metadata invariants of image-based Sets.
        """
        mapper = self._getMapper()

        if not self.isPostgresqlWritable():
            raise RuntimeError(
                "PostgreSQL runtime Set is read-only."
            )

        appendItem = getattr(
            mapper,
            "appendItem",
            None,
        )

        if not callable(appendItem):
            raise RuntimeError(
                "Writable PostgreSQL mapper does not "
                "provide appendItem()."
            )

        wasEmpty = bool(
            self.isEmpty()
        )

        self._preparePostgresqlAppendItem(
            item
        )

        itemId = int(
            appendItem(
                item
            )
        )

        self._updatePostgresqlAppendMetadata(
            item=item,
            wasEmpty=wasEmpty,
        )

        self._idCount = max(
            int(
                self._idCount
                or 0
            ),
            itemId,
        )

        # Do not increment optimistically. Another worker
        # may have inserted items concurrently.
        self._size.set(
            mapper.count()
        )

    def clone(self, *args, **kwargs):
        """
        Clone a PostgreSQL runtime Set while preserving its
        read-only mapper and SQLite compatibility infrastructure.

        Preserve the native clone() contract of each Scipion Set
        implementation. Some Sets accept copyEnable, while others,
        such as TiltSeries, accept ignoreAttrs.
        """
        try:
            runtimeClone = super().clone(
                *args,
                **kwargs
            )

        except TypeError as error:
            genericSetCloneError = (
                "copy() got an unexpected "
                "keyword argument 'copyEnable'"
            )

            if genericSetCloneError not in str(
                    error
            ):
                raise

            # Object.clone(copyEnable=...) is not compatible
            # with Set.copy(), whose signature does not accept
            # copyEnable. Reproduce the native clone behavior
            # explicitly for generic Scipion Sets.
            runtimeClone = self.getClass()()

            runtimeClone.copy(
                self
            )

            copyEnable = (
                kwargs.get(
                    "copyEnable"
                )
                if "copyEnable" in kwargs
                else (
                    args[0]
                    if args
                    else False
                )
            )

            if copyEnable:
                runtimeClone.setEnabled(
                    self.isEnabled()
                )

        sourceMapperFactory = getattr(
            self,
            "_postgresqlMapperFactory",
            None,
        )

        if not callable(
                sourceMapperFactory
        ):
            raise RuntimeError(
                "Cannot clone PostgreSQL runtime set "
                "without a mapper factory. "
                "className=%s objectId=%s"
                % (
                    self.getClassName(),
                    self.getObjId(),
                )
            )

        sourceMaterializer = getattr(
            self,
            "_postgresqlSqliteMaterializer",
            None,
        )

        if sourceMaterializer is None:
            raise RuntimeError(
                "Cannot clone PostgreSQL runtime set "
                "without a SQLite materializer. "
                "className=%s objectId=%s"
                % (
                    self.getClassName(),
                    self.getObjId(),
                )
            )

        originalCloneClass = runtimeClone.__class__

        if originalCloneClass is not self.__class__:
            try:
                runtimeClone.__class__ = self.__class__
            except TypeError as error:
                raise TypeError(
                    "Could not promote cloned native Scipion Set. "
                    "originalClass=%s runtimeClass=%s objectId=%s"
                    % (
                        originalCloneClass.__name__,
                        self.__class__.__name__,
                        self.getObjId(),
                    )
                ) from error

        for attributeName in (
                "_postgresqlRuntimeInfo",
                "_postgresqlRuntimeProperties",
                "_postgresqlRuntimeClasses",
                "_postgresqlRuntimeValues",
        ):
            value = getattr(
                self,
                attributeName,
                {},
            )

            setattr(
                runtimeClone,
                attributeName,
                (
                    dict(value)
                    if isinstance(value, dict)
                    else {}
                ),
            )

        classesDict = getattr(
            self,
            "_classesDict",
            None,
        )

        if isinstance(
                classesDict,
                dict,
        ):
            runtimeClone._classesDict = dict(
                classesDict
            )

        runtimeClone._postgresqlNativeSetClass = getattr(
            self,
            "_postgresqlNativeSetClass",
            None,
        )

        runtimeClone._postgresqlSqliteMaterializer = (
            sourceMaterializer
        )

        runtimeClone._postgresqlMaterializedFileName = None
        runtimeClone._postgresqlMaterializedRevision = None

        # A clone must not become writable implicitly.
        # Resume explicitly enables writing on the canonical output.
        runtimeClone._postgresqlSupportsNativeWrite = self.supportsPostgresqlNativeWrite()
        runtimeClone._postgresqlWritable = False

        runtimeClone._mapper = None

        try:
            runtimeClone.setName(
                self.getObjName()
            )
        except Exception:
            pass

        try:
            runtimeClone._objParentId = (
                self.getObjParentId()
            )
        except Exception:
            runtimeClone._objParentId = None

        setPostgresqlRuntimeParentReference(
            runtimeObject=runtimeClone,
            parent=getPostgresqlRuntimeParent(
                self
            ),
        )

        def cloneMapperFactory(writable=False):
            mapper = sourceMapperFactory(
                writable=bool(writable)
            )

            sourceItemBuilder = getattr(
                mapper,
                "itemBuilder",
                None,
            )

            if not callable(
                    sourceItemBuilder
            ):
                return mapper

            def buildCloneItem(row):
                item = sourceItemBuilder(
                    row
                )

                if item is None:
                    return None

                setPostgresqlRuntimeParentReference(
                    runtimeObject=item,
                    parent=runtimeClone,
                )

                try:
                    item._objParentId = (
                        runtimeClone.getObjId()
                    )
                except Exception:
                    pass

                return item

            mapper.itemBuilder = (
                buildCloneItem
            )

            return mapper

        runtimeClone._postgresqlMapperFactory = (
            cloneMapperFactory
        )

        return runtimeClone

    def write(
            self,
            properties=True,
    ):
        # Scipion's streaming update closes the Set after
        # committing STREAM_OPEN. The following STREAM_CLOSED
        # update reuses exactly the same object.
        #
        # _postgresqlWritable preserves the requested access
        # mode even while _mapper is None.
        if (
                not self.isPostgresqlWritable()
                and bool(
            getattr(
                self,
                "_postgresqlWritable",
                False,
            )
        )
        ):
            self.enablePostgresqlWrite()

        if not self.isPostgresqlWritable():
            raise RuntimeError(
                "PostgreSQL runtime Set is read-only."
            )

        return super().write(
            properties=properties
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

    def clearCaches(self) -> None:
        """
        Release all runtime objects owned by this factory.

        Runtime sets are closed once before references to sets, protocols and
        resolved pointer targets are discarded.
        """
        runtimeSets = []
        seenSetIdentities = set()

        for runtimeSet in self._runtimeSetsByIdentity.values():
            runtimeSetIdentity = id(runtimeSet)

            if runtimeSetIdentity in seenSetIdentities:
                continue

            seenSetIdentities.add(runtimeSetIdentity)
            runtimeSets.append(runtimeSet)

        self._runtimeSetsByIdentity.clear()
        self._runtimeProtocolsByIdentity.clear()
        self._resolvedPointerTargets.clear()
        self._resolvingPointerTargets.clear()

        for runtimeSet in runtimeSets:
            close = getattr(runtimeSet, "close", None)

            if not callable(close):
                continue

            try:
                close()
            except Exception:
                logger.debug(
                    "Could not close cached PostgreSQL runtime set.",
                    exc_info=True,
                )

    def evictRuntimeSet(
            self,
            projectId: int,
            runtimeObjectId: int,
            runtimeSet=None,
    ):
        """
        Remove one runtime Set and its item-pointer cache entries.

        Cached protocols and unrelated runtime Sets must remain untouched.
        """
        projectId = int(projectId)
        runtimeObjectId = int(runtimeObjectId)

        targetIdentity = (
            projectId,
            runtimeObjectId,
        )

        cachedRuntimeSet = self._runtimeSetsByIdentity.pop(
            targetIdentity,
            None,
        )

        runtimeSetsToClose = []
        seenRuntimeSets = set()

        for candidate in (
                cachedRuntimeSet,
                runtimeSet,
        ):
            if candidate is None:
                continue

            candidateIdentity = id(
                candidate
            )

            if candidateIdentity in seenRuntimeSets:
                continue

            seenRuntimeSets.add(
                candidateIdentity
            )

            runtimeSetsToClose.append(
                candidate
            )

        if seenRuntimeSets:
            for identity, candidate in list(
                    self._runtimeSetsByIdentity.items()
            ):
                if id(candidate) not in seenRuntimeSets:
                    continue

                self._runtimeSetsByIdentity.pop(
                    identity,
                    None,
                )

        for pointerKey in list(
                self._resolvedPointerTargets
        ):
            if pointerKey[:2] != targetIdentity:
                continue

            self._resolvedPointerTargets.pop(
                pointerKey,
                None,
            )

        for pointerKey in list(
                self._resolvingPointerTargets
        ):
            if pointerKey[:2] != targetIdentity:
                continue

            self._resolvingPointerTargets.discard(
                pointerKey
            )

        for runtimeSetToClose in runtimeSetsToClose:
            close = getattr(
                runtimeSetToClose,
                "close",
                None,
            )

            if not callable(close):
                continue

            try:
                close()
            except Exception:
                logger.debug(
                    "Could not close evicted PostgreSQL runtime Set. "
                    "projectId=%s runtimeObjectId=%s",
                    projectId,
                    runtimeObjectId,
                    exc_info=True,
                )

        return (
            cachedRuntimeSet
            if cachedRuntimeSet is not None
            else runtimeSet
        )

    def clearRuntimeSetPointerCache(
            self,
            projectId: int,
            runtimeObjectId: int,
    ) -> None:
        """
        Clear item-pointer resolutions owned by one runtime Set.

        The runtime Set itself remains cached and open.
        """
        targetIdentity = (
            int(projectId),
            int(runtimeObjectId),
        )

        for pointerKey in list(
                self._resolvedPointerTargets
        ):
            if pointerKey[:2] != targetIdentity:
                continue

            self._resolvedPointerTargets.pop(
                pointerKey,
                None,
            )

        for pointerKey in list(
                self._resolvingPointerTargets
        ):
            if pointerKey[:2] != targetIdentity:
                continue

            self._resolvingPointerTargets.discard(
                pointerKey
            )

    def build(
            self,
            db,
            parent,
            outputName: str,
            outputInfo: Dict[str, Any],
            classes: Optional[Dict[str, Type]] = None,
            runtimeSet=None,
            cache: bool = True,
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

        if runtimeSet is None:
            runtimeSet = runtimeSetClass()

        else:
            if not isinstance(
                    runtimeSet,
                    nativeSetClass,
            ):
                raise TypeError(
                    "Cannot refresh PostgreSQL runtime Set %s "
                    "using persisted class %s."
                    % (
                        runtimeSet.__class__.__name__,
                        nativeSetClass.__name__,
                    )
                )

            runtimeChecker = getattr(
                runtimeSet,
                "isPostgresqlRuntimeOutput",
                None,
            )

            if (
                    not callable(runtimeChecker)
                    or not runtimeChecker()
            ):
                raise TypeError(
                    "Existing Set %s is not a PostgreSQL "
                    "runtime output."
                    % runtimeSet.__class__.__name__
                )

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
            db=db,
            classRegistry=classRegistry,
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

        rootTableId = (
            self._resolveRootLogicalTableId(
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

        nestedSetItemClass = (
            self._isScipionSetClass(
                nativeItemClass
            )
        )

        if nestedSetItemClass:
            itemClassRegistry[
                str(itemClassName)
            ] = self._getRuntimeSetClass(
                nativeItemClass
            )

        columns = setMapper.getStoredSetColumns(
            int(setId)
        )

        pointerResolver = (
            self._buildPointerResolver(
                db=db,
                runtimeSet=runtimeSet,
                classRegistry=classRegistry,
            )
        )

        itemHydratorState = {
            "columns": [
                dict(column)
                for column
                in columns or []
            ],
            "hydrator": None,
        }

        def updateItemHydratorColumns(
                updatedColumns,
        ) -> None:
            normalizedColumns = [
                dict(column)
                for column in (
                    updatedColumns
                    or []
                )
            ]

            if (
                    normalizedColumns
                    == itemHydratorState[
                "columns"
            ]
            ):
                return

            itemHydratorState[
                "columns"
            ] = normalizedColumns

            itemHydratorState[
                "hydrator"
            ] = None

        def getItemHydrator():
            hydrator = (
                itemHydratorState[
                    "hydrator"
                ]
            )

            if hydrator is None:
                hydrator = (
                    PostgresqlScipionItemHydrator(
                        itemClassName=(
                            str(itemClassName)
                        ),
                        columns=(
                            itemHydratorState[
                                "columns"
                            ]
                        ),
                        parent=runtimeSet,
                        classes=(
                            itemClassRegistry
                        ),
                        pointerResolver=(
                            pointerResolver
                        ),
                    )
                )

                itemHydratorState[
                    "hydrator"
                ] = hydrator

            return hydrator

        def buildItem(row):
            row = dict(
                row or {}
            )

            if nestedSetItemClass:
                parentItemId = self._toOptionalInt(
                    row.get("scipionItemId")
                )

                if (
                        parentItemId is not None
                        and int(parentItemId) not in logicalTablesByParentId
                ):
                    refreshedLogicalTables = self._loadLogicalTablesByParentItemId(
                        setMapper=setMapper,
                        setId=int(setId),
                    )

                    logicalTablesByParentId.clear()
                    logicalTablesByParentId.update(
                        refreshedLogicalTables
                    )

                if (
                        parentItemId is None
                        or int(parentItemId) not in logicalTablesByParentId
                ):
                    raise RuntimeError(
                        "PostgreSQL nested set snapshot "
                        "is incomplete. "
                        "setId=%s parentItemId=%s "
                        "itemClassName=%s "
                        "availableParentItemIds=%s"
                        % (
                            setId,
                            parentItemId,
                            itemClassName,
                            sorted(
                                logicalTablesByParentId.keys()
                            ),
                        )
                    )

            item = (
                getItemHydrator()
                .build(
                    row
                )
            )

            if (
                    isinstance(
                        item,
                        ScipionSet,
                    )
                    and nestedSetItemClass
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

        def serializeItem(
                item,
        ):
            return (
                setMapper
                .serializeRuntimeItem(
                    item=item,
                    scipionSet=runtimeSet,
                )
            )

        def synchronizeItemSchema(
                item,
        ):
            if rootTableId is None:
                raise RuntimeError(
                    "Cannot synchronize a PostgreSQL "
                    "Set schema without rootTableId."
                )

            schemaInfo = (
                setMapper
                .synchronizeRuntimeItemSchema(
                    setId=int(setId),
                    rootTableId=int(
                        rootTableId
                    ),
                    item=item,
                    scipionSet=runtimeSet,
                )
            )

            updateItemHydratorColumns(
                schemaInfo.get(
                    "columns"
                )
                or []
            )

            return schemaInfo

        def synchronizeNestedItem(
                item,
                parentItemId,
        ):
            if not nestedSetItemClass:
                return None

            if not isinstance(
                    item,
                    ScipionSet,
            ):
                raise TypeError(
                    "Nested PostgreSQL output item must "
                    "be a Scipion Set. className=%s"
                    % item.__class__.__name__
                )

            parentItemId = int(
                parentItemId
            )

            tableInfo = (
                setMapper
                .ensureRuntimeNestedSetTable(
                    setId=int(setId),
                    rootTableId=int(
                        rootTableId
                    ),
                    parentSet=item,
                    parentItemId=(
                        parentItemId
                    ),
                )
            )

            tableRow = dict(
                tableInfo.get(
                    "table"
                )
                or {}
            )

            tableProperties = (
                self._normalizeProperties(
                    tableRow.get(
                        "properties"
                    )
                )
            )

            tableProperties.update(
                self._normalizeProperties(
                    tableInfo.get(
                        "properties"
                    )
                )
            )

            tableRow[
                "properties"
            ] = tableProperties

            logicalTablesByParentId[
                parentItemId
            ] = tableRow

            # The protocol must keep the exact same object.
            self._promoteRuntimeSetInstance(
                runtimeSet=item,
                nativeSetClass=(
                    nativeItemClass
                ),
            )

            currentMapper = getattr(
                item,
                "_mapper",
                None,
            )

            # ensureRuntimeNestedSetTable() has already copied any
            # items held by the original native/SQLite mapper.
            if currentMapper is not None:
                closeMapper = getattr(
                    currentMapper,
                    "close",
                    None,
                )

                if callable(
                        closeMapper
                ):
                    closeMapper()

            item._mapper = None

            self._configureRuntimeSetCompatibility(
                runtimeSet=item,
                nativeSetClass=(
                    nativeItemClass
                ),
                runtimeInfo={
                    "setId": int(setId),
                    "rootTableId": int(
                        rootTableId
                    ),
                    "tableId": int(
                        tableInfo[
                            "tableId"
                        ]
                    ),
                    "parentItemId": (
                        parentItemId
                    ),
                    "className": (
                        item.getClassName()
                    ),
                    "itemClassName": (
                        tableInfo.get(
                            "itemClassName"
                        )
                    ),
                    "properties": (
                        tableProperties
                    ),
                },
                runtimeProperties=(
                    tableProperties
                ),
                classRegistry=(
                    classRegistry
                ),
            )

            setPostgresqlRuntimeParentReference(
                runtimeObject=item,
                parent=runtimeSet,
            )

            item._objParentId = (
                runtimeSet.getObjId()
            )

            self._attachLogicalTableMapper(
                db=db,
                setMapper=setMapper,
                item=item,
                row={
                    "scipionItemId": (
                        parentItemId
                    ),
                },
                logicalTablesByParentId={
                    parentItemId: (
                        tableRow
                    ),
                },
                classRegistry=(
                    classRegistry
                ),
                writable=True,
            )

            return tableInfo

        def mapperFactory(
                writable=False,
        ):
            return PostgresqlSetRuntimeMapper(
                db=db,
                setId=int(setId),
                rootTableId=rootTableId,
                itemBuilder=buildItem,
                itemSerializer=serializeItem,
                itemSchemaSynchronizer=(
                    synchronizeItemSchema
                    if rootTableId is not None
                    else None
                ),
                itemColumnsUpdater=(
                    updateItemHydratorColumns
                ),
                nestedItemSynchronizer=(
                    synchronizeNestedItem
                    if nestedSetItemClass
                    else None
                ),
                writable=bool(
                    writable
                ),
            )

        # Root Sets can write normal items directly and can
        # synchronize nested Set items through writable
        # PostgreSQL logical tables.
        runtimeSet._postgresqlSupportsNativeWrite = (
                rootTableId is not None
        )

        runtimeSet._postgresqlWritable = False

        runtimeSet._postgresqlMapperFactory = (
            mapperFactory
        )

        runtimeSet.load()

        runtimeInfo = getattr(
            runtimeSet,
            "_postgresqlRuntimeInfo",
            None,
        )

        if isinstance(
                runtimeInfo,
                dict,
        ):
            runtimeInfo[
                "rootTableId"
            ] = rootTableId

        if cache:
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
        runtimeSet._postgresqlMaterializedRevision = None
        runtimeSet._postgresqlSupportsNativeWrite = False
        runtimeSet._postgresqlWritable = False

    def _resolveRootLogicalTableId(
            self,
            setMapper,
            setId: int,
    ) -> Optional[int]:
        rootTables = [
            dict(table)
            for table in (
                    setMapper.listStoredSetTables(
                        int(setId)
                    )
                    or []
            )
            if (
                    table.get(
                        "tableKind"
                    )
                    == "root"
            )
        ]

        if len(rootTables) > 1:
            raise ValueError(
                "More than one PostgreSQL root "
                "logical table was found for set %s."
                % setId
            )

        if not rootTables:
            return None

        tableId = self._toOptionalInt(
            rootTables[0].get(
                "id"
            )
        )

        return (
            int(tableId)
            if tableId is not None
            else None
        )

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

    def _resolveCurrentLogicalTableId(
            self,
            *,
            setMapper,
            setId: int,
            parentItemId: int,
    ) -> Optional[int]:
        matchingTables = []

        for table in (
                setMapper.listStoredSetTables(
                    int(setId)
                )
                or []
        ):
            if (
                    table.get("tableKind")
                    != "child"
            ):
                continue

            storedParentItemId = (
                self._toOptionalInt(
                    table.get(
                        "parentItemId"
                    )
                )
            )

            if (
                    storedParentItemId
                    != int(parentItemId)
            ):
                continue

            matchingTables.append(
                dict(table)
            )

        if len(matchingTables) > 1:
            raise ValueError(
                "More than one PostgreSQL logical "
                "table was found for set %s and "
                "parent item %s."
                % (
                    setId,
                    parentItemId,
                )
            )

        if not matchingTables:
            return None

        return self._toOptionalInt(
            matchingTables[0].get("id")
        )

    def _attachLogicalTableMapper(
            self,
            db,
            setMapper,
            item,
            row: Dict[str, Any],
            logicalTablesByParentId:
            Dict[int, Dict[str, Any]],
            classRegistry: Dict[str, Type],
            writable: bool = False,
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

        setId = self._toOptionalInt(
            table.get("setId")
        )

        if setId is None:
            raise ValueError(
                "Logical table %s does not expose setId"
                % tableId
            )

        childMapperState = {
            "tableId": None,
            "columns": [],
            "hydrator": None,
        }

        def updateChildHydratorColumns(
                updatedColumns,
        ) -> None:
            normalizedColumns = [
                dict(column)
                for column in (
                    updatedColumns
                    or []
                )
            ]

            if (
                    normalizedColumns
                    == childMapperState[
                "columns"
            ]
            ):
                return

            childMapperState[
                "columns"
            ] = normalizedColumns

            childMapperState[
                "hydrator"
            ] = None

        def resolveCurrentTableId():
            currentTableId = (
                self._resolveCurrentLogicalTableId(
                    setMapper=setMapper,
                    setId=int(setId),
                    parentItemId=int(itemId),
                )
            )

            if currentTableId is None:
                currentTableId = int(
                    tableId
                )

            runtimeInfo = getattr(
                item,
                "_postgresqlRuntimeInfo",
                None,
            )

            if isinstance(
                    runtimeInfo,
                    dict,
            ):
                runtimeInfo[
                    "tableId"
                ] = int(
                    currentTableId
                )

            return int(
                currentTableId
            )

        def refreshChildColumns(
                currentTableId,
        ):
            currentTableId = int(
                currentTableId
            )

            if (
                    childMapperState[
                        "tableId"
                    ]
                    == currentTableId
            ):
                return

            childMapperState[
                "tableId"
            ] = currentTableId

            updateChildHydratorColumns(
                setMapper
                .getStoredSetTableColumns(
                    currentTableId
                )
                or []
            )

        def getChildHydrator():
            currentTableId = (
                resolveCurrentTableId()
            )

            refreshChildColumns(
                currentTableId
            )

            hydrator = (
                childMapperState[
                    "hydrator"
                ]
            )

            if hydrator is None:
                hydrator = (
                    PostgresqlScipionItemHydrator(
                        itemClassName=str(
                            childItemClassName
                        ),
                        columns=(
                            childMapperState[
                                "columns"
                            ]
                        ),
                        parent=item,
                        classes=classRegistry,
                        pointerResolver=(
                            self._buildPointerResolver(
                                db=db,
                                runtimeSet=item,
                                classRegistry=(
                                    classRegistry
                                ),
                            )
                        ),
                    )
                )

                childMapperState[
                    "hydrator"
                ] = hydrator

            return hydrator

        def buildChildItem(
                childRow,
        ):
            return (
                getChildHydrator()
                .build(
                    dict(
                        childRow
                        or {}
                    )
                )
            )

        def serializeChildItem(
                childItem,
        ):
            return (
                setMapper
                .serializeRuntimeItem(
                    item=childItem,
                    scipionSet=item,
                )
            )

        def synchronizeChildSchema(
                childItem,
        ):
            currentTableId = (
                resolveCurrentTableId()
            )

            schemaInfo = (
                setMapper
                .synchronizeRuntimeLogicalItemSchema(
                    tableId=(
                        currentTableId
                    ),
                    item=childItem,
                    parentSet=item,
                )
            )

            childMapperState[
                "tableId"
            ] = currentTableId

            updateChildHydratorColumns(
                schemaInfo.get(
                    "columns"
                )
                or []
            )

            return schemaInfo

        def mapperFactory(
                writable=False,
        ):
            currentTableId = (
                resolveCurrentTableId()
            )

            refreshChildColumns(
                currentTableId
            )

            return PostgresqlSetRuntimeMapper(
                db=db,
                tableId=currentTableId,
                tableIdResolver=(
                    resolveCurrentTableId
                ),
                parentItemId=int(
                    itemId
                ),
                itemBuilder=(
                    buildChildItem
                ),
                itemSerializer=(
                    serializeChildItem
                ),
                itemSchemaSynchronizer=(
                    synchronizeChildSchema
                ),
                itemColumnsUpdater=(
                    updateChildHydratorColumns
                ),
                writable=bool(
                    writable
                ),
            )

        item._postgresqlMapperFactory = (
            mapperFactory
        )

        item._postgresqlSupportsNativeWrite = True
        item._postgresqlWritable = False

        currentMapper = getattr(
            item,
            "_mapper",
            None,
        )

        if currentMapper is not None:
            closeMapper = getattr(
                currentMapper,
                "close",
                None,
            )

            if callable(
                    closeMapper
            ):
                closeMapper()

        item._mapper = None

        if writable:
            item.enablePostgresqlWrite()

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

            targetSet = (
                self
                ._resolveRuntimeSetPointerTarget(
                    db=db,
                    runtimeSet=runtimeSet,
                    classRegistry=(
                        classRegistry
                    ),
                    reference=reference,
                )
            )

            if targetSet is not None:
                return targetSet

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

    def _resolveRuntimeSetPointerTarget(
            self,
            db,
            runtimeSet: ScipionSet,
            classRegistry: Dict[str, Type],
            reference: Dict[str, Any],
    ):
        targetClassName = str(
            reference.get(
                "targetClassName"
            )
            or ""
        ).strip()

        targetClass = (
            classRegistry.get(
                targetClassName
            )
            if classRegistry
            else None
        )

        if not self._isScipionSetClass(
                targetClass
        ):
            return None

        projectId = self._getRuntimeProjectId(
            runtimeSet
        )

        if not isinstance(
                projectId,
                int,
        ):
            return None

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

        targetObjectName = str(
            reference.get(
                "targetObjectName"
            )
            or reference.get(
                "uniqueId"
            )
            or ""
        ).strip()

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
            repositoryMapper = (
                SimpleNamespace(
                    db=db
                )
            )

        targetOutputInfo = None

        if isinstance(
                targetObjectId,
                int,
        ):
            targetOutputInfo = (
                self.protocolGraphRepository
                .getPersistedSetOutputRowByRuntimeObjectId(
                    mapper=repositoryMapper,
                    projectId=projectId,
                    runtimeObjectId=(
                        targetObjectId
                    ),
                )
            )

        if (
                targetOutputInfo is None
                and isinstance(
            targetParentObjectId,
            int,
        )
                and targetObjectName
        ):
            outputName = (
                targetObjectName
            )

            protocolPrefix = (
                "%s."
                % targetParentObjectId
            )

            if outputName.startswith(
                    protocolPrefix
            ):
                outputName = outputName[
                    len(protocolPrefix):
                ]

            targetOutputInfo = (
                self.protocolGraphRepository
                .getPersistedSetOutputRowByProtocolOutput(
                    mapper=repositoryMapper,
                    projectId=projectId,
                    protocolId=(
                        targetParentObjectId
                    ),
                    outputName=outputName,
                )
            )

        if targetOutputInfo is None:
            return None

        canonicalRuntimeObjectId = (
            self._toOptionalInt(
                targetOutputInfo.get(
                    "runtimeObjectId"
                )
            )
        )

        if not isinstance(
                canonicalRuntimeObjectId,
                int,
        ):
            return None

        sourceRuntimeObjectId = (
            self._toOptionalInt(
                runtimeSet.getObjId()
            )
        )

        if (
                sourceRuntimeObjectId
                == canonicalRuntimeObjectId
        ):
            return runtimeSet

        targetKey = (
            projectId,
            canonicalRuntimeObjectId,
            "__set__",
        )

        if targetKey in (
                self._resolvedPointerTargets
        ):
            return (
                self._resolvedPointerTargets[
                    targetKey
                ]
            )

        if targetKey in (
                self._resolvingPointerTargets
        ):
            return None

        self._resolvingPointerTargets.add(
            targetKey
        )

        try:
            targetSet = (
                self._getCachedRuntimeSet(
                    projectId=projectId,
                    runtimeObjectId=(
                        canonicalRuntimeObjectId
                    ),
                )
            )

            if targetSet is None:
                targetProtocol = (
                    self._resolveRuntimeProtocol(
                        projectId=projectId,
                        sourceProtocol=(
                            sourceProtocol
                        ),
                        runtimeMapper=(
                            runtimeMapper
                        ),
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
                            canonicalRuntimeObjectId
                        ),
                ):
                    targetSet = attachedSet

                else:
                    targetSet = self.build(
                        db=db,
                        parent=targetProtocol,
                        outputName=outputName,
                        outputInfo=(
                            targetOutputInfo
                        ),
                        classes=classRegistry,
                    )

                self._cacheRuntimeSet(
                    targetSet
                )

            self._resolvedPointerTargets[
                targetKey
            ] = targetSet

            return targetSet

        finally:
            self._resolvingPointerTargets.discard(
                targetKey
            )

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

                attachedSet = getattr(targetProtocol, outputName, None)

                if self._isMatchingRuntimeSet(
                        runtimeSet=attachedSet,
                        runtimeObjectId=targetParentObjectId,
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

                # The external set can reference its owner protocol, but resolving
                # an item for another protocol must never replace or attach outputs
                # on the target parent protocol.
                self._cacheRuntimeSet(targetSet)

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

            current = (
                getPostgresqlRuntimeParent(
                    current
                )
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

            current = (
                getPostgresqlRuntimeParent(
                    current
                )
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

    def _promoteRuntimeSetInstance(
            self,
            runtimeSet: ScipionSet,
            nativeSetClass: Type,
    ):
        """
        Promote one existing native Scipion Set instance to its
        PostgreSQL runtime subclass without replacing the object.

        Protocols commonly keep using the same TiltSeries/Class
        reference after appending it to the parent Set.
        """
        if not isinstance(
                runtimeSet,
                nativeSetClass,
        ):
            raise TypeError(
                "Cannot promote %s using native Set class %s."
                % (
                    runtimeSet.__class__.__name__,
                    nativeSetClass.__name__,
                )
            )

        runtimeSetClass = (
            self._getRuntimeSetClass(
                nativeSetClass
            )
        )

        if isinstance(
                runtimeSet,
                runtimeSetClass,
        ):
            return runtimeSet

        originalClass = (
            runtimeSet.__class__
        )

        try:
            runtimeSet.__class__ = (
                runtimeSetClass
            )

        except TypeError as error:
            raise TypeError(
                "Could not promote native Scipion Set "
                "instance in place. "
                "originalClass=%s runtimeClass=%s "
                "objectId=%s"
                % (
                    originalClass.__name__,
                    runtimeSetClass.__name__,
                    runtimeSet.getObjId(),
                )
            ) from error

        return runtimeSet

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

        setPostgresqlRuntimeParentReference(
            runtimeObject=runtimeSet,
            parent=parent,
        )

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
            db,
            classRegistry: Dict[str, Type],
    ) -> None:
        pointerResolver = (
            self._buildPointerResolver(
                db=db,
                runtimeSet=runtimeSet,
                classRegistry=classRegistry,
            )
        )

        for path, value in properties.items():
            path = str(path)

            if not path.startswith("_"):
                continue

            if path in self.SKIPPED_PROPERTY_PATHS:
                continue

            attribute = (
                self._getExistingAttribute(
                    runtimeSet=runtimeSet,
                    path=path,
                )
            )

            if isinstance(
                    attribute,
                    Pointer,
            ):
                self._hydrateRuntimePointer(
                    pointer=attribute,
                    value=value,
                    pointerResolver=(
                        pointerResolver
                    ),
                )

                continue

            if isinstance(
                    attribute,
                    PointerList,
            ):
                self._hydrateRuntimePointerList(
                    pointerList=attribute,
                    value=value,
                    pointerResolver=(
                        pointerResolver
                    ),
                )

                continue

            self._setExistingAttributeValue(
                runtimeSet,
                path,
                value,
            )

    def _getExistingAttribute(
            self,
            runtimeSet,
            path: str,
    ):
        parts = [
            part
            for part in path.split(".")
            if part
        ]

        if not parts:
            return None

        current = runtimeSet

        for part in parts:
            current = getattr(
                current,
                part,
                None,
            )

            if current is None:
                return None

        return current

    def _hydrateRuntimePointer(
            self,
            pointer: Pointer,
            value: Any,
            pointerResolver,
    ) -> bool:
        reference = (
            self._normalizePointerReference(
                value
            )
        )

        pointer._postgresqlRuntimeReference = (
            dict(reference)
        )

        target = None

        if (
                reference
                and callable(
            pointerResolver
        )
        ):
            target = pointerResolver(
                dict(reference)
            )

        pointer.set(
            target
        )

        extended = reference.get(
            "extended"
        )

        if extended not in (
                None,
                "",
        ):
            pointer.setExtended(
                str(extended)
            )

        return bool(reference)

    def _hydrateRuntimePointerList(
            self,
            pointerList: PointerList,
            value: Any,
            pointerResolver,
    ) -> bool:
        references = (
            self._normalizePointerReferences(
                value
            )
        )

        pointerList.clear()

        normalizedReferences = []

        for reference in references:
            pointer = Pointer()

            self._hydrateRuntimePointer(
                pointer=pointer,
                value=reference,
                pointerResolver=(
                    pointerResolver
                ),
            )

            pointerList.append(
                pointer
            )

            normalizedReferences.append(
                dict(reference)
            )

        pointerList._postgresqlRuntimeReferences = (
            normalizedReferences
        )

        return True

    def _normalizePointerReference(
            self,
            value: Any,
    ) -> Dict[str, Any]:
        if isinstance(
                value,
                dict,
        ):
            return dict(value)

        if isinstance(
                value,
                str,
        ):
            value = value.strip()

            if not value:
                return {}

            try:
                parsed = json.loads(
                    value
                )
            except Exception:
                return {
                    "version": 0,
                    "kind": "pointer",
                    "uniqueId": value,
                    "extended": "",
                }

            if isinstance(
                    parsed,
                    dict,
            ):
                return dict(parsed)

        return {}

    def _normalizePointerReferences(
            self,
            value: Any,
    ):
        if value is None:
            return []

        if isinstance(
                value,
                str,
        ):
            value = value.strip()

            if not value:
                return []

            try:
                value = json.loads(
                    value
                )
            except Exception:
                value = [
                    value
                ]

        if isinstance(
                value,
                dict,
        ):
            value = [
                value
            ]

        if not isinstance(
                value,
                (
                    list,
                    tuple,
                ),
        ):
            return []

        return [
            reference
            for reference in (
                self._normalizePointerReference(
                    item
                )
                for item in value
            )
            if reference
        ]

    def _setExistingAttributeValue(
            self,
            runtimeSet,
            path: str,
            value: Any,
    ) -> bool:
        current = self._getExistingAttribute(
            runtimeSet=runtimeSet,
            path=path,
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