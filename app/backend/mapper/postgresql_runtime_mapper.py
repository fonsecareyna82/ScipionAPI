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
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pyworkflow.object as pwobject
from pyworkflow.mapper.mapper import Mapper
from pyworkflow.mapper.sqlite import (
    SqliteFlatMapper,
)
from pyworkflow.project.project import PROJECT_CREATION_TIME
from pyworkflow.protocol.protocol import LegacyProtocol, Protocol
from pyworkflow.protocol.params import (
    MultiPointerParam,
    PointerParam,
    RelationParam,
)
from pyworkflow.object import (
    Object as ScipionObject,
    Set as ScipionSet,
    String,
)
from pyworkflow.utils import joinExt, replaceExt
from pyworkflow.config import Config
from pyworkflow.project import config as projectConfig

from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.mapper.scipion_object_mapper import ScipionObjectPostgresqlMapper
from app.backend.mapper.scipion_set_mapper import (
    ScipionSetPostgresqlMapper,
)
from app.backend.runtime.postgresql_runtime_set_factory import (
    PostgresqlRuntimeSetFactory,
)
from app.backend.runtime.protocol_graph_repository import (
    ProtocolGraphRepository,
)
from app.backend.runtime.protocol_status_sync_service import (
    RuntimeProtocolStatusSyncService,
)
from app.backend.mapper.postgresql_scipion_item_hydrator import (
    setPostgresqlRuntimeParentReference,
)

logger = logging.getLogger(__name__)


class PostgresqlRuntimeMapper(Mapper):
    """
    Mapper compatible with pyworkflow.mapper.Mapper, backed by PostgreSQL.

    PostgreSQL is authoritative for project runtime reads and persistence:
    - Protocol metadata goes to protocols.
    - Step snapshots go to protocol_steps.
    - Scipion object trees go to scipion_objects.
    - SetOf... objects go to scipion_sets/scipion_set_items.
    - Runtime relations go to scipion_relations.
    """

    isPostgresqlRuntimeMapper = True

    def __init__(
            self,
            flatMapper: PostgresqlFlatMapper,
            projectId: int,
            dictClasses=None,
            project=None,
    ):
        if not dictClasses or not hasattr(dictClasses, "items"):
            dictClasses = pwobject.Dict(default=LegacyProtocol)
            dictClasses.update(pwobject.OBJECTS_DICT)

            domain = None

            if project is not None:
                getDomain = getattr(
                    project,
                    "getDomain",
                    None,
                )

                if callable(getDomain):
                    domain = getDomain()

            if domain is None:
                domain = Config.getDomain()

            getMapperDict = getattr(
                domain,
                "getMapperDict",
                None,
            )

            if callable(getMapperDict):
                dictClasses.update(
                    getMapperDict() or {}
                )

            dictClasses.update(
                projectConfig.__dict__
            )

        super().__init__(
            dictClasses=dictClasses
        )

        self.flatMapper = flatMapper
        self.db = flatMapper.db
        self.projectId = int(projectId)
        self.project = project

        self.objectMapper = (
            ScipionObjectPostgresqlMapper(
                self.db
            )
        )

        self.setMapper = (
            ScipionSetPostgresqlMapper(
                self.db
            )
        )

        self.protocolGraphRepository = (
            ProtocolGraphRepository()
        )

        # Keep one factory per runtime mapper so native sets,
        # protocols and pointer targets share the same caches.
        self.runtimeSetFactory = PostgresqlRuntimeSetFactory()
        self._runtimeProtocolsById = {}

    SELECT_BY_FIELDS = frozenset({
        "id",
        "parent_id",
        "name",
        "classname",
        "value",
        "label",
        "comment",
        "creation",
    })

    INTERNAL_PROTOCOL_OBJECT_NAMES = frozenset({
        "_jobId",
        "_pid",
        "_outputs",
        "_useOutputList",
    })

    # ---------------------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------------------

    def commit(self):
        # PostgresqlDb.execute commits by default. Transactions are handled
        # explicitly with db.transaction() where needed.
        try:
            if getattr(self.db, "conn", None) is not None:
                self.db.conn.commit()
        except Exception:
            logger.exception("Could not commit PostgreSQL runtime mapper.")
            raise

    def close(self):
        # Do not close the shared PostgreSQL connection here. It belongs to the
        # request/session mapper lifecycle.
        clearRuntimeCaches = getattr(
            self.runtimeSetFactory,
            "clearCaches",
            None,
        )

        if callable(clearRuntimeCaches):
            try:
                clearRuntimeCaches()
            except Exception:
                logger.debug(
                    "Could not clear PostgreSQL runtime set caches.",
                    exc_info=True,
                )

        self._runtimeProtocolsById.clear()

    def store(self, obj):
        if obj is None:
            return

        if isinstance(obj, Protocol):
            self._storeRuntimeProtocol(obj)
            return

        self._ensureObjId(obj)

        if self._shouldSkipInternalRuntimeObject(obj):
            return

        if isinstance(obj, ScipionSet) or self._isSetLike(obj):
            self._storeSetObject(obj)
            return

        if isinstance(obj, ScipionObject):
            self._storeObjectTree(obj)
            return

        logger.debug(
            "PostgresqlRuntimeMapper.store skipped unsupported object: %s",
            type(obj),
        )

    def _storeRuntimeProtocol(self, protocol: Protocol) -> None:
        """Store a protocol using PostgreSQL as the authoritative runtime persistence."""
        protocolId = self._ensureObjId(protocol)

        if protocolId is None:
            raise RuntimeError(
                "Cannot store PostgreSQL runtime protocol without id."
            )

        self._storeProtocol(protocol)

    def evictRuntimeProtocols(self, protocolIds):
        evictedProtocolIds = []

        for protocolId in protocolIds or []:
            try:
                protocolId = int(protocolId)
            except Exception:
                continue

            self._runtimeProtocolsById.pop(
                protocolId,
                None,
            )

            evictedProtocolIds.append(
                protocolId
            )

        return {
            "evictedProtocolIds": evictedProtocolIds,
            "count": len(evictedProtocolIds),
        }

    def evictDeletedRuntimeArtifacts(
            self,
            protocolIds,
            runtimeSetObjectIds=None,
    ):
        """
        Remove deleted protocols and every cached Set/pointer target.

        Clearing Set caches is deliberately global for this mapper:
        delete is uncommon, and retaining one pointer to a deleted
        PostgreSQL Set is more dangerous than rebuilding unrelated
        read-only runtime Sets.
        """
        protocolEviction = (
            self.evictRuntimeProtocols(
                protocolIds
            )
        )

        runtimeSetObjectIds = [
            int(runtimeObjectId)
            for runtimeObjectId in (
                runtimeSetObjectIds or []
            )
            if runtimeObjectId
            not in (
                None,
                "",
            )
        ]

        clearCaches = getattr(
            self.runtimeSetFactory,
            "clearCaches",
            None,
        )

        cachesCleared = False

        if callable(clearCaches):
            clearCaches()
            cachesCleared = True

        return {
            "protocols": protocolEviction,
            "runtimeSetObjectIds": (
                runtimeSetObjectIds
            ),
            "runtimeSetCachesCleared": (
                cachesCleared
            ),
        }

    def insert(self, obj):
        if obj is None:
            return

        if isinstance(obj, Protocol):
            self._storeRuntimeProtocol(obj)
            return

        self._ensureObjId(obj)
        self.store(obj)

    def insertChild(self, obj, key, attr, namePrefix=None):
        """Insert a child object following Scipion's mapper naming convention."""
        if attr is None:
            return

        self._ensureObjId(obj)
        self._ensureObjId(attr)

        if namePrefix is None:
            namePrefix = self._getNamePrefix(obj)

        try:
            self._setObjName(attr, joinExt(namePrefix, key))
            self._setObjParentId(attr, obj.getObjId())
        except Exception:
            logger.debug(
                "Could not assign PostgreSQL child metadata. parent=%s key=%s child=%s",
                obj,
                key,
                attr,
                exc_info=True,
            )

        self.store(attr)

    def updateTo(self, obj):
        self.store(obj)

    def updateFrom(self, obj):
        if self._updateProtocolFromPostgresql(obj):
            return None

        if self._updateSetFromPostgresql(obj):
            return None

        if self._updateGenericObjectFromPostgresql(obj):
            return None

        raise NotImplementedError(
            "PostgreSQL updateFrom is only implemented "
            "for protocols, PostgreSQL runtime Sets "
            "and supported generic runtime objects."
        )

    def _updateProtocolFromPostgresql(
            self,
            protocol,
    ) -> bool:
        if not isinstance(
                protocol,
                Protocol,
        ):
            return False

        protocolId = self._toOptionalInt(
            self._getObjId(
                protocol
            )
        )

        if protocolId is None:
            return False

        row = (
            self.flatMapper
            .getProjectProtocolByProtocolId(
                self.projectId,
                protocolId,
            )
        )

        if not row:
            return False

        storedClassName = str(
            row.get(
                "protocolClassName"
            )
            or ""
        ).strip()

        storedClass = (
            self._resolveProtocolClass(
                storedClassName
            )
            if storedClassName
            else None
        )

        if (
                storedClass is not None
                and not isinstance(
            protocol,
            storedClass,
        )
        ):
            raise TypeError(
                "Runtime object %s resolves to PostgreSQL "
                "protocol class %s, but the supplied object "
                "class is %s."
                % (
                    protocolId,
                    storedClassName,
                    self._getClassName(
                        protocol
                    ),
                )
            )

        stateSnapshot = (
            self._captureRuntimeObjectState(
                protocol
            )
        )

        try:
            refreshedProtocol = self._refreshProtocolFromPostgresqlRow(
                protocol,
                row,
            )

            if refreshedProtocol is not protocol:
                raise RuntimeError(
                    "PostgreSQL protocol updateFrom replaced protocol identity %s." % protocolId)

        except Exception:
            self._restoreRuntimeObjectState(
                protocol,
                stateSnapshot,
            )

            raise

        self._runtimeProtocolsById[
            protocolId
        ] = protocol

        return True

    def _updateSetFromPostgresql(
            self,
            runtimeSet,
    ) -> bool:
        if not (
                isinstance(
                    runtimeSet,
                    ScipionSet,
                )
                or self._isSetLike(
            runtimeSet
        )
        ):
            return False

        runtimeObjectId = self._toOptionalInt(
            self._getObjId(
                runtimeSet
            )
        )

        if runtimeObjectId is None:
            return False

        setMatcher = getattr(
            self.runtimeSetFactory,
            "_isMatchingRuntimeSet",
            None,
        )

        if (
                not callable(setMatcher)
                or not setMatcher(
            runtimeSet=runtimeSet,
            runtimeObjectId=(
                    runtimeObjectId
            ),
        )
        ):
            return False

        outputInfo = (
            self.protocolGraphRepository
            .getPersistedSetOutputRowByRuntimeObjectId(
                mapper=self,
                projectId=self.projectId,
                runtimeObjectId=(
                    runtimeObjectId
                ),
            )
        )

        if not outputInfo:
            return False

        protocolId = self._toOptionalInt(
            outputInfo.get(
                "protocolId"
            )
        )

        outputName = str(
            outputInfo.get(
                "outputName"
            )
            or ""
        ).strip()

        if (
                protocolId is None
                or not outputName
        ):
            return False

        parentProtocol = getattr(
            runtimeSet,
            "_objParent",
            None,
        )

        parentProtocolId = (
            self._toOptionalInt(
                self._getObjId(
                    parentProtocol
                )
            )
        )

        if parentProtocolId != protocolId:
            parentProtocol = (
                self.selectRuntimeProtocolById(
                    protocolId,
                    refreshCached=False,
                )
            )

        if parentProtocol is None:
            return False

        stateSnapshot = (
            self._captureRuntimeObjectState(
                runtimeSet
            )
        )

        previousMapper = getattr(
            runtimeSet,
            "_mapper",
            None,
        )

        try:
            refreshedSet = (
                self.runtimeSetFactory.build(
                    db=self.db,
                    parent=parentProtocol,
                    outputName=outputName,
                    outputInfo=outputInfo,
                    classes=getattr(
                        self,
                        "dictClasses",
                        None,
                    ),
                    runtimeSet=runtimeSet,
                    cache=False,
                )
            )

            if refreshedSet is not runtimeSet:
                raise RuntimeError(
                    "PostgreSQL Set updateFrom "
                    "replaced runtime Set identity %s."
                    % runtimeObjectId
                )

        except Exception:
            failedMapper = getattr(
                runtimeSet,
                "_mapper",
                None,
            )

            if (
                    failedMapper is not None
                    and failedMapper
                    is not previousMapper
            ):
                close = getattr(
                    failedMapper,
                    "close",
                    None,
                )

                if callable(close):
                    try:
                        close()
                    except Exception:
                        logger.debug(
                            "Could not close failed "
                            "PostgreSQL Set mapper.",
                            exc_info=True,
                        )

            self._restoreRuntimeObjectState(
                runtimeSet,
                stateSnapshot,
            )

            raise

        refreshedMapper = getattr(
            runtimeSet,
            "_mapper",
            None,
        )

        if (
                previousMapper is not None
                and previousMapper
                is not refreshedMapper
        ):
            close = getattr(
                previousMapper,
                "close",
                None,
            )

            if callable(close):
                try:
                    close()
                except Exception:
                    logger.debug(
                        "Could not close previous "
                        "PostgreSQL Set mapper.",
                        exc_info=True,
                    )

        clearPointerCache = getattr(
            self.runtimeSetFactory,
            "clearRuntimeSetPointerCache",
            None,
        )

        if callable(clearPointerCache):
            clearPointerCache(
                projectId=self.projectId,
                runtimeObjectId=(
                    runtimeObjectId
                ),
            )

        self.runtimeSetFactory._cacheRuntimeSet(
            runtimeSet
        )

        return True

    def _captureRuntimeObjectState(
            self,
            obj,
    ):
        """
        Capture object attributes and mutable Scipion scalar values.

        The shallow attribute dictionary preserves mapper/project identities.
        Scalar values are stored separately because set() may mutate an object
        already referenced by the shallow snapshot.
        """
        snapshot = {
            "attributes": dict(
                getattr(
                    obj,
                    "__dict__",
                    {},
                )
            ),
            "settableValues": [],
        }

        visited = set()

        def captureValue(
                candidate,
        ):
            if candidate is None:
                return

            candidateIdentity = id(
                candidate
            )

            if candidateIdentity in visited:
                return

            visited.add(
                candidateIdentity
            )

            getter = getattr(
                candidate,
                "get",
                None,
            )

            setter = getattr(
                candidate,
                "set",
                None,
            )

            if (
                    callable(getter)
                    and callable(setter)
            ):
                try:
                    value = getter()
                except TypeError:
                    try:
                        value = getter(
                            None
                        )
                    except Exception:
                        value = None
                except Exception:
                    value = None

                snapshot[
                    "settableValues"
                ].append(
                    (
                        candidate,
                        value,
                    )
                )

            attributesGetter = getattr(
                candidate,
                "getAttributesToStore",
                None,
            )

            if not callable(
                    attributesGetter
            ):
                return

            try:
                attributes = list(
                    attributesGetter()
                    or []
                )
            except Exception:
                return

            for _, child in attributes:
                captureValue(
                    child
                )

        captureValue(
            obj
        )

        return snapshot

    def _restoreRuntimeObjectState(
            self,
            obj,
            snapshot,
    ) -> None:
        attributes = dict(
            snapshot.get(
                "attributes",
                {},
            )
        )

        obj.__dict__.clear()
        obj.__dict__.update(
            attributes
        )

        for candidate, value in reversed(
                snapshot.get(
                    "settableValues",
                    [],
                )
        ):
            setter = getattr(
                candidate,
                "set",
                None,
            )

            if not callable(setter):
                continue

            try:
                setter(
                    value
                )
            except Exception:
                logger.debug(
                    "Could not restore runtime object "
                    "value after failed updateFrom.",
                    exc_info=True,
                )

    def _updateGenericObjectFromPostgresql(self, obj):
        if obj is None:
            return False

        objectClass = obj.__class__

        if not self._isSupportedGenericRuntimeObjectClass(
                objectClass
        ):
            return False

        if self._call(obj, "isPointer", False):
            return False

        runtimeObjectId = self._toOptionalInt(
            self._getObjId(obj)
        )

        if runtimeObjectId is None:
            return False

        storedObject = self._selectGenericObjectByIdFromPostgresql(
            runtimeObjectId
        )

        if storedObject is None:
            return False

        return self._copyGenericObjectStateFromPostgresql(
            targetObject=obj,
            storedObject=storedObject,
            preserveParentObject=True,
        )

    def _copyGenericObjectStateFromPostgresql(
            self,
            targetObject,
            storedObject,
            preserveParentObject=False,
    ):
        parentObject = getattr(
            targetObject,
            "_objParent",
            None,
        )

        storedObjectId = self._getObjId(
            storedObject
        )

        if storedObjectId is not None:
            self._setObjId(
                targetObject,
                storedObjectId,
            )

        storedObjectName = str(
            getattr(
                storedObject,
                "_objName",
                "",
            )
            or ""
        )

        if storedObjectName:
            self._setObjName(
                targetObject,
                storedObjectName,
            )

        storedParentId = self._call(
            storedObject,
            "getObjParentId",
            getattr(
                storedObject,
                "_objParentId",
                None,
            ),
        )

        if storedParentId is None:
            targetObject._objParentId = None
        else:
            self._setObjParentId(
                targetObject,
                storedParentId,
            )

        valueSetter = getattr(
            targetObject,
            "set",
            None,
        )

        if not callable(valueSetter):
            return False

        storedValue = self._call(
            storedObject,
            "getObjValue",
            None,
        )

        try:
            valueSetter(storedValue)
        except Exception:
            logger.debug(
                "Could not update generic object value "
                "from PostgreSQL. projectId=%s "
                "runtimeObjectId=%s className=%s",
                self.projectId,
                storedObjectId,
                self._getClassName(storedObject),
                exc_info=True,
            )
            return False

        self._copyGenericObjectMetadataFromPostgresql(
            targetObject,
            storedObject,
        )

        attributesGetter = getattr(
            storedObject,
            "getAttributesToStore",
            None,
        )

        storedAttributes = []

        if callable(attributesGetter):
            try:
                storedAttributes = list(
                    attributesGetter() or []
                )
            except Exception:
                return False

        for attributeName, storedChild in storedAttributes:
            attributeName = str(attributeName)

            targetChild = getattr(
                targetObject,
                attributeName,
                None,
            )

            if self._canReuseGenericObjectForUpdate(
                    targetChild,
                    storedChild,
            ):
                if not self._copyGenericObjectStateFromPostgresql(
                        targetObject=targetChild,
                        storedObject=storedChild,
                ):
                    return False
            else:
                targetChild = storedChild

                setattr(
                    targetObject,
                    attributeName,
                    targetChild,
                )

            targetChild._objParent = targetObject

            targetObjectId = self._getObjId(
                targetObject
            )

            if targetObjectId is not None:
                self._setObjParentId(
                    targetChild,
                    targetObjectId,
                )

        if preserveParentObject:
            targetObject._objParent = parentObject

        return True

    def _copyGenericObjectMetadataFromPostgresql(
            self,
            targetObject,
            storedObject,
    ):
        label = self._call(
            storedObject,
            "getObjLabel",
            getattr(
                storedObject,
                "_objLabel",
                "",
            ),
        )

        labelSetter = getattr(
            targetObject,
            "setObjLabel",
            None,
        )

        if callable(labelSetter):
            labelSetter(label or "")
        else:
            targetObject._objLabel = label or ""

        comment = self._call(
            storedObject,
            "getObjComment",
            getattr(
                storedObject,
                "_objComment",
                "",
            ),
        )

        commentSetter = getattr(
            targetObject,
            "setObjComment",
            None,
        )

        if callable(commentSetter):
            commentSetter(comment or "")
        else:
            targetObject._objComment = comment or ""

        creation = self._call(
            storedObject,
            "getObjCreation",
            getattr(
                storedObject,
                "_objCreation",
                None,
            ),
        )

        creationSetter = getattr(
            targetObject,
            "setObjCreation",
            None,
        )

        if callable(creationSetter):
            creationSetter(creation)
        else:
            targetObject._objCreation = creation

    def _canReuseGenericObjectForUpdate(
            self,
            targetObject,
            storedObject,
    ):
        if not isinstance(
                targetObject,
                ScipionObject,
        ):
            return False

        if not isinstance(
                storedObject,
                ScipionObject,
        ):
            return False

        targetClassName = self._getSelectByStoredClassName(
            targetObject
        )

        storedClassName = self._getSelectByStoredClassName(
            storedObject
        )

        return targetClassName == storedClassName

    def selectById(self, objId):
        obj = self._selectProtocolByIdFromPostgresql(objId)

        if obj is not None:
            return self._attachRuntimeContext(obj)

        obj = self._selectSetByIdFromPostgresql(objId)

        if obj is not None:
            return obj

        return self._selectGenericObjectByIdFromPostgresql(objId)

    def selectRuntimeProtocolById(self, objId, refreshCached: bool = True):
        """Return one stable PostgreSQL-backed protocol for runtime operations."""
        protocolId = self._toOptionalInt(objId)

        if protocolId is None:
            logger.warning(
                "Cannot select runtime protocol: objId is not an int. objId=%s",
                objId,
            )
            return None

        row = self.flatMapper.getProjectProtocolByProtocolId(
            self.projectId,
            protocolId,
        )

        cachedProtocol = self._runtimeProtocolsById.get(protocolId)

        if cachedProtocol is not None:
            if row:
                if refreshCached:
                    return self._getOrBuildProtocolFromPostgresqlRow(row)

                return cachedProtocol

            self._runtimeProtocolsById.pop(protocolId, None)

        if not row:
            return None

        if refreshCached:
            return self._getOrBuildProtocolFromPostgresqlRow(row)

        return self._buildProtocolFromPostgresqlRow(row)

    def _selectProtocolByIdFromPostgresql(
            self,
            objId,
            refreshCached: bool = True,
    ):
        protocolId = self._toOptionalInt(
            objId
        )

        if protocolId is None:
            logger.warning(
                "Cannot select PostgreSQL protocol: "
                "objId is not an int. objId=%s",
                objId,
            )
            return None

        logger.debug(
            "Looking for PostgreSQL protocol row. "
            "projectId=%s protocolId=%s",
            self.projectId,
            protocolId,
        )

        row = (
            self.flatMapper
            .getProjectProtocolByProtocolId(
                self.projectId,
                protocolId,
            )
        )

        if not row:
            return None

        if refreshCached:
            return (
                self
                ._getOrBuildProtocolFromPostgresqlRow(
                    row
                )
            )

        cachedProtocol = self._runtimeProtocolsById.get(
            protocolId
        )

        if cachedProtocol is not None:
            return cachedProtocol

        # Detached read representation: it is deliberately not cached.
        return self._buildProtocolFromPostgresqlRow(
            row
        )

    def _getOrBuildProtocolFromPostgresqlRow(self, row):
        protocolId = self._toOptionalInt(row.get("protocolId"))

        if protocolId is None:
            logger.warning(
                "Cannot build PostgreSQL protocol without protocolId. row=%s",
                row,
            )
            return None

        protocol = self._runtimeProtocolsById.get(protocolId)

        if protocol is None:
            protocol = self._buildProtocolFromPostgresqlRow(row)

            if protocol is None:
                return None

            self._runtimeProtocolsById[protocolId] = protocol
            return protocol

        return self._refreshProtocolFromPostgresqlRow(
            protocol,
            row,
        )

    def _selectSetByIdFromPostgresql(
            self,
            objId,
            refreshParentProtocol: bool = True,
    ):
        runtimeObjectId = self._toOptionalInt(
            objId
        )

        if runtimeObjectId is None:
            logger.warning(
                "Cannot select PostgreSQL runtime set: "
                "objId is not an int. objId=%s",
                objId,
            )

            return None

        cachedSet = (
            self.runtimeSetFactory
            ._getCachedRuntimeSet(
                projectId=self.projectId,
                runtimeObjectId=runtimeObjectId,
            )
        )

        if cachedSet is not None:
            return cachedSet

        outputInfo = (
            self.protocolGraphRepository
            .getPersistedSetOutputRowByRuntimeObjectId(
                mapper=self,
                projectId=self.projectId,
                runtimeObjectId=runtimeObjectId,
            )
        )

        if not outputInfo:
            return None

        protocolId = self._toOptionalInt(
            outputInfo.get(
                "protocolId"
            )
        )

        if protocolId is None:
            logger.warning(
                "Cannot reconstruct PostgreSQL runtime set: "
                "parent protocol id is missing. "
                "projectId=%s runtimeObjectId=%s setId=%s",
                self.projectId,
                runtimeObjectId,
                outputInfo.get("setId"),
            )

            return None

        parentProtocol = (
            self.selectRuntimeProtocolById(
                protocolId,
                refreshCached=refreshParentProtocol,
            )
        )

        if parentProtocol is None:
            logger.warning(
                "Cannot reconstruct PostgreSQL runtime set: "
                "parent protocol was not found. "
                "projectId=%s protocolId=%s "
                "runtimeObjectId=%s",
                self.projectId,
                protocolId,
                runtimeObjectId,
            )

            return None

        outputName = str(
            outputInfo.get(
                "outputName"
            )
            or ""
        ).strip()

        if not outputName:
            logger.warning(
                "Cannot reconstruct PostgreSQL runtime set: "
                "output name is missing. "
                "projectId=%s protocolId=%s "
                "runtimeObjectId=%s",
                self.projectId,
                protocolId,
                runtimeObjectId,
            )

            return None

        attachedSet = getattr(
            parentProtocol,
            outputName,
            None,
        )

        if (
                self.runtimeSetFactory
                        ._isMatchingRuntimeSet(
                    runtimeSet=attachedSet,
                    runtimeObjectId=runtimeObjectId,
                )
        ):
            self.runtimeSetFactory._cacheRuntimeSet(
                attachedSet
            )

            return attachedSet

        runtimeSet = self.runtimeSetFactory.build(
            db=self.db,
            parent=parentProtocol,
            outputName=outputName,
            outputInfo=outputInfo,
            classes=getattr(self, "dictClasses", None),
        )

        if runtimeSet is None:
            return None

        # Mapper reads must not attach or replace outputs on the owner protocol.
        # The runtime set keeps its parent identity and is reused through the
        # shared factory cache.
        self.runtimeSetFactory._cacheRuntimeSet(runtimeSet)

        return runtimeSet

    def _selectGenericObjectByIdFromPostgresql(
            self,
            objId,
            allowPartialTree: bool = False,
    ):
        """
        Reconstruct one detached, generic Scipion object from PostgreSQL.

        Protocols and sets have their own readers and are deliberately rejected
        here. Pointer-containing trees are also rejected until their complete
        target and extended semantics can be restored safely.
        """
        runtimeObjectId = self._toOptionalInt(
            objId
        )

        if runtimeObjectId is None:
            return None

        objectMapper = getattr(
            self,
            "objectMapper",
            None,
        )

        reader = getattr(
            objectMapper,
            "getStoredObjectSubtreeByScipionObjId",
            None,
        )

        if not callable(reader):
            return None

        rows = reader(
            projectId=self.projectId,
            scipionObjId=runtimeObjectId,
        )

        if not rows:
            return None

        return self._buildGenericObjectFromPostgresqlRows(
            rows,
            allowPartialTree=allowPartialTree,
        )

    @staticmethod
    def _isRuntimeOnlyGenericObjectRow(
            row,
    ) -> bool:
        objectPath = str(
            (row or {}).get("path")
            or ""
        )

        return "_objParent" in objectPath.split(".")

    def _buildGenericObjectFromPostgresqlRows(
            self,
            rows,
            allowPartialTree: bool = False,
    ):
        """
        Build an independent PostgreSQL object tree.

        Normal mapper reads remain strict. Runtime input preparation may skip
        unsupported nested nodes, but the root object must always be rebuilt
        completely enough to preserve its identity and concrete class.
        """
        objectsByRowId = {}
        skippedRowIds = set()
        rootObject = None

        def rejectOrSkip(
                row,
                rowId,
                depth,
                reason,
        ) -> bool:
            objectPath = str(
                row.get("path")
                or row.get("name")
                or ""
            ).strip()

            className = str(
                row.get("className")
                or ""
            ).strip()

            if (
                    allowPartialTree
                    and depth > 0
            ):
                skippedRowIds.add(
                    rowId
                )

                logger.warning(
                    "Skipping unsupported nested PostgreSQL "
                    "runtime object. projectId=%s "
                    "runtimeObjectId=%s path=%s "
                    "className=%s reason=%s",
                    self.projectId,
                    row.get("scipionObjId"),
                    objectPath,
                    className,
                    reason,
                )

                return True

            logger.warning(
                "Could not reconstruct PostgreSQL generic "
                "runtime object. projectId=%s "
                "runtimeObjectId=%s path=%s "
                "className=%s reason=%s",
                self.projectId,
                row.get("scipionObjId"),
                objectPath,
                className,
                reason,
            )

            return False

        for row in rows or []:
            rowId = self._toOptionalInt(
                row.get("id")
            )

            depth = self._toOptionalInt(
                row.get("depth")
            )

            if (
                    rowId is None
                    or depth is None
            ):
                logger.warning(
                    "Could not reconstruct PostgreSQL generic "
                    "object because a stored row has no valid "
                    "id/depth. projectId=%s row=%s",
                    self.projectId,
                    row,
                )

                return None

            parentRowId = None

            if depth > 0:
                parentRowId = self._toOptionalInt(
                    row.get("parentObjectId")
                )

            if self._isRuntimeOnlyGenericObjectRow(
                    row
            ):
                skippedRowIds.add(
                    rowId
                )
                continue

            if (
                    depth > 0
                    and parentRowId
                    in skippedRowIds
            ):
                skippedRowIds.add(
                    rowId
                )
                continue

            parentObject = None
            attributeName = None
            existingAttribute = None

            if depth > 0:
                if parentRowId is None:
                    if rejectOrSkip(
                            row,
                            rowId,
                            depth,
                            "missing_parent_row_id",
                    ):
                        continue

                    return None

                parentObject = objectsByRowId.get(
                    parentRowId
                )

                if parentObject is None:
                    if rejectOrSkip(
                            row,
                            rowId,
                            depth,
                            "parent_not_reconstructed",
                    ):
                        continue

                    return None

                attributeName = str(
                    row.get("name")
                    or ""
                ).strip()

                if not attributeName:
                    if rejectOrSkip(
                            row,
                            rowId,
                            depth,
                            "missing_attribute_name",
                    ):
                        continue

                    return None

                existingAttribute = getattr(
                    parentObject,
                    attributeName,
                    None,
                )

            metadata = (
                self
                ._normalizeStoredObjectMetadata(
                    row.get("metadata")
                )
            )

            pointerFlag = metadata.get(
                "isPointer",
                False,
            )

            isStoredPointer = (
                    pointerFlag is True
                    or str(pointerFlag)
                    .strip()
                    .lower()
                    in {
                        "1",
                        "true",
                        "yes",
                        "on",
                    }
            )

            if isStoredPointer:
                if rejectOrSkip(
                        row,
                        rowId,
                        depth,
                        "pointer_node",
                ):
                    continue

                return None

            objectClass = (
                self
                ._resolveRuntimeObjectClass(
                    row.get("className")
                )
            )

            # Some nested plugin classes are not present in dictClasses,
            # although the parent constructor already created the correct
            # concrete attribute. Reuse that class when its name matches.
            if (
                    objectClass is None
                    and isinstance(
                existingAttribute,
                ScipionObject,
            )
            ):
                storedClassName = str(
                    row.get("className")
                    or ""
                ).strip()

                existingClassName = str(
                    self._getClassName(
                        existingAttribute
                    )
                    or ""
                ).strip()

                if (
                        not storedClassName
                        or storedClassName
                        == existingClassName
                ):
                    objectClass = (
                        existingAttribute
                        .__class__
                    )

            if not self._isSupportedGenericRuntimeObjectClass(
                    objectClass
            ):
                if rejectOrSkip(
                        row,
                        rowId,
                        depth,
                        "unsupported_class",
                ):
                    continue

                return None

            scipionObject = None

            if isinstance(
                    existingAttribute,
                    objectClass,
            ):
                scipionObject = (
                    existingAttribute
                )

            if scipionObject is None:
                try:
                    scipionObject = (
                        objectClass()
                    )

                except Exception:
                    logger.debug(
                        "Could not instantiate PostgreSQL "
                        "generic object. projectId=%s "
                        "className=%s runtimeObjectId=%s",
                        self.projectId,
                        row.get("className"),
                        row.get("scipionObjId"),
                        exc_info=True,
                    )

                    if rejectOrSkip(
                            row,
                            rowId,
                            depth,
                            "instantiation_failed",
                    ):
                        continue

                    return None

            if self._call(
                    scipionObject,
                    "isPointer",
                    False,
            ):
                if rejectOrSkip(
                        row,
                        rowId,
                        depth,
                        "runtime_pointer_object",
                ):
                    continue

                return None

            stateSnapshot = (
                self
                ._captureRuntimeObjectState(
                    scipionObject
                )
            )

            if not self._restoreGenericObjectStateFromPostgresqlRow(
                    scipionObject,
                    row,
            ):
                self._restoreRuntimeObjectState(
                    scipionObject,
                    stateSnapshot,
                )

                if rejectOrSkip(
                        row,
                        rowId,
                        depth,
                        "state_restore_failed",
                ):
                    continue

                return None

            objectsByRowId[
                rowId
            ] = scipionObject

            if parentObject is not None:
                setattr(
                    parentObject,
                    attributeName,
                    scipionObject,
                )

                scipionObject._objParent = (
                    parentObject
                )

                parentRuntimeObjectId = (
                    self._getObjId(
                        parentObject
                    )
                )

                if parentRuntimeObjectId is not None:
                    self._setObjParentId(
                        scipionObject,
                        parentRuntimeObjectId,
                    )

                continue

            if rootObject is not None:
                logger.warning(
                    "Could not reconstruct PostgreSQL generic "
                    "object because the stored subtree contains "
                    "more than one root. projectId=%s "
                    "runtimeObjectId=%s",
                    self.projectId,
                    row.get("scipionObjId"),
                )

                return None

            rootObject = scipionObject

            parentRuntimeObjectId = (
                self._toOptionalInt(
                    row.get(
                        "rootParentScipionObjId"
                    )
                )
            )

            if parentRuntimeObjectId is None:
                parentRuntimeObjectId = (
                    self._toOptionalInt(
                        row.get(
                            "ownerProtocolId"
                        )
                    )
                )

            if parentRuntimeObjectId is not None:
                self._setObjParentId(
                    rootObject,
                    parentRuntimeObjectId,
                )

        return rootObject

    @staticmethod
    def _isSupportedGenericRuntimeObjectClass(
            objectClass,
    ):
        if not isinstance(
                objectClass,
                type,
        ):
            return False

        try:
            if not issubclass(
                    objectClass,
                    ScipionObject,
            ):
                return False

            if issubclass(
                    objectClass,
                    (
                            Protocol,
                            ScipionSet,
                    ),
            ):
                return False

        except TypeError:
            return False

        return True

    def _restoreGenericObjectStateFromPostgresqlRow(
            self,
            scipionObject,
            row,
    ):
        runtimeObjectId = self._toOptionalInt(
            row.get("scipionObjId")
        )

        if runtimeObjectId is not None:
            self._setObjId(
                scipionObject,
                runtimeObjectId,
            )

        objectPath = str(
            row.get("path")
            or row.get("name")
            or ""
        ).strip()

        if objectPath:
            self._setObjName(
                scipionObject,
                objectPath,
            )

        valueSetter = getattr(
            scipionObject,
            "set",
            None,
        )

        if not callable(valueSetter):
            return False

        try:
            valueSetter(
                row.get("value")
            )
        except Exception:
            logger.debug(
                "Could not restore PostgreSQL "
                "generic object value. "
                "projectId=%s runtimeObjectId=%s "
                "className=%s value=%s",
                self.projectId,
                runtimeObjectId,
                row.get("className"),
                row.get("value"),
                exc_info=True,
            )
            return False

        label = row.get("label")
        comment = row.get("comment")

        labelSetter = getattr(
            scipionObject,
            "setObjLabel",
            None,
        )

        if callable(labelSetter):
            labelSetter(
                label or ""
            )
        else:
            scipionObject._objLabel = (
                label or ""
            )

        commentSetter = getattr(
            scipionObject,
            "setObjComment",
            None,
        )

        if callable(commentSetter):
            commentSetter(
                comment or ""
            )
        else:
            scipionObject._objComment = (
                comment or ""
            )

        creation = row.get("creation")

        if creation not in (
                None,
                "",
        ):
            creation = (
                self
                ._formatProjectCreationTime(
                    creation
                )
            )

            if creation is None:
                return False

        creationSetter = getattr(
            scipionObject,
            "setObjCreation",
            None,
        )

        if callable(creationSetter):
            creationSetter(
                creation
            )
        else:
            scipionObject._objCreation = (
                creation
            )

        return True

    @staticmethod
    def _normalizeStoredObjectMetadata(
            metadata,
    ):
        if isinstance(
                metadata,
                dict,
        ):
            return metadata

        if isinstance(
                metadata,
                str,
        ):
            try:
                parsedMetadata = json.loads(
                    metadata
                )
            except Exception:
                return {}

            if isinstance(
                    parsedMetadata,
                    dict,
            ):
                return parsedMetadata

        return {}

    def exists(self, objId):
        runtimeObjectId = self._toOptionalInt(objId)

        if runtimeObjectId is None:
            return False

        protocolRow = self.db.fetchOne(
            """
            SELECT id
              FROM protocols
             WHERE "projectId" = %s
               AND "protocolId" = %s
             LIMIT 1
            """,
            (
                self.projectId,
                str(runtimeObjectId),
            ),
        )

        if protocolRow is not None:
            return True

        cachedSet = self.runtimeSetFactory._getCachedRuntimeSet(
            projectId=self.projectId,
            runtimeObjectId=runtimeObjectId,
        )

        if cachedSet is not None:
            return True

        outputInfo = self.protocolGraphRepository.getPersistedSetOutputRowByRuntimeObjectId(
            mapper=self,
            projectId=self.projectId,
            runtimeObjectId=runtimeObjectId,
        )

        if outputInfo is not None:
            return True

        return self._resolveCanonicalScipionObjectRowId(runtimeObjectId) is not None

    def selectAll(
            self,
            iterate=False,
            objectFilter=None,
    ):
        """
        Return root runtime objects using the PostgreSQL batch reader.

        selectAllBatch returns PostgreSQL-backed protocols and generic objects.
        selectAll preserves the native Mapper contract by excluding child
        attributes and restoring the project CreationTime root when needed.
        """
        if (
                objectFilter is not None
                and not callable(objectFilter)
        ):
            raise TypeError(
                "objectFilter must be callable or None"
            )

        def rootObjectFilter(obj):
            parentObject = getattr(obj, "_objParent", None)
            parentId = self._call(
                obj,
                "getObjParentId",
                getattr(obj, "_objParentId", None),
            )

            if parentObject is not None or parentId is not None:
                return False

            if objectFilter is None:
                return True

            return bool(objectFilter(obj))

        result = list(
            self.selectAllBatch(
                objectFilter=rootObjectFilter,
            )
        )

        creationTimeIndex = next(
            (
                index
                for index, obj in enumerate(result)
                if self._getObjectName(obj)
                   == PROJECT_CREATION_TIME
            ),
            None,
        )

        if creationTimeIndex is None:
            creationTime = (
                self
                ._selectProjectCreationTimeFromPostgresql()
            )

            if (
                    creationTime is not None
                    and rootObjectFilter(creationTime)
            ):
                result.insert(
                    0,
                    creationTime,
                )

        elif creationTimeIndex > 0:
            creationTime = result.pop(
                creationTimeIndex
            )

            result.insert(
                0,
                creationTime,
            )

        if iterate:
            return iter(
                result
            )

        return result

    def _buildProtocolFromPostgresqlRow(self, row):

        protocolClassName = str(row.get("protocolClassName") or "").strip()
        if not protocolClassName:
            logger.warning(
                "Cannot build PostgreSQL protocol: empty protocolClassName. row=%s",
                row,
            )
            return None

        protocolClass = self._resolveProtocolClass(protocolClassName)
        if protocolClass is None:
            logger.warning(
                "Cannot build PostgreSQL protocol: class not found. "
                "projectId=%s protocolId=%s protocolClassName=%s",
                self.projectId,
                row.get("protocolId"),
                protocolClassName,
            )
            return None

        protocol = self._instantiateProtocol(protocolClass)
        protocol = self._refreshProtocolFromPostgresqlRow(protocol, row)
        protocolId = self._toOptionalInt(row.get("protocolId"))

        logger.debug(
            "Built PostgreSQL protocol object. projectId=%s protocolId=%s protocol=%s class=%s workingDir=%s",
            self.projectId,
            protocolId,
            protocol,
            protocol.__class__.__name__,
            getattr(protocol, "getWorkingDir", lambda: None)(),
        )

        return protocol

    def _refreshProtocolFromPostgresqlRow(self, protocol, row):
        protocolId = self._toOptionalInt(row.get("protocolId"))

        if protocolId is not None:
            self._setObjId(protocol, protocolId)

        self._attachRuntimeContext(protocol)
        self._applyStoredProtocolStatus(protocol, row.get("status"))
        self._applyStoredProtocolParams(protocol, row.get("params") or {})
        self._ensureProtocolWorkingDir(protocol)

        return protocol

    def getPostgresqlProtocolLabels(self):
        labels = []

        for row in self.flatMapper.getProtocols(self.projectId) or []:
            params = self._normalizeStoredProtocolParams(
                row.get("params") or {}
            )

            label = self._extractStoredProtocolParamValue(
                params.get("object.label")
            )

            label = str(label or "").strip()

            if label:
                labels.append(label)

        return labels

    def _selectAllGenericObjectsFromPostgresql(
            self,
            objectFilter=None,
    ):
        rows = self._getPostgresqlGenericObjectRowsForClass(
            requestedClassName=ScipionObject.__name__,
            requestedClass=ScipionObject,
            includeSubclasses=True,
        )

        result = []

        for row in rows:
            runtimeObjectId = self._toOptionalInt(
                row.get("runtimeObjectId")
            )

            if runtimeObjectId is None:
                continue

            runtimeObject = self._selectGenericObjectByIdFromPostgresql(
                runtimeObjectId
            )

            if runtimeObject is None:
                continue

            if callable(objectFilter) and not objectFilter(runtimeObject):
                continue

            result.append(runtimeObject)

        return result

    def selectAllBatch(self, objectFilter=None):
        if objectFilter is not None and not callable(objectFilter):
            raise TypeError("objectFilter must be callable or None")

        result = []
        seenProtocolIds = set()

        for row in self.flatMapper.getProtocols(self.projectId) or []:
            protocolId = self._toOptionalInt(row.get("protocolId"))

            if protocolId is None or protocolId in seenProtocolIds:
                continue

            protocol = self._getOrBuildProtocolFromPostgresqlRow(row)

            if protocol is None:
                continue

            if objectFilter is not None and not objectFilter(protocol):
                continue

            result.append(protocol)
            seenProtocolIds.add(protocolId)

        genericObjects = self._selectAllGenericObjectsFromPostgresql(objectFilter=objectFilter)
        result.extend(genericObjects)

        return result

    def selectBy(
            self,
            iterate=False,
            objectFilter=None,
            **args,
    ):
        if objectFilter is not None and not callable(objectFilter):
            raise TypeError("objectFilter must be callable or None")

        if self._isProjectCreationTimeQuery(args):
            creationTime = self._selectProjectCreationTimeFromPostgresql()

            if creationTime is not None:
                result = [creationTime]

                if (
                        objectFilter is not None
                        and not objectFilter(creationTime)
                ):
                    result = []

                return iter(result) if iterate else result

            return iter(()) if iterate else []

        unsupportedFields = (
                set(args)
                - self.SELECT_BY_FIELDS
        )

        if unsupportedFields:
            raise NotImplementedError(
                "PostgreSQL selectBy does not support query fields: %s"
                % sorted(unsupportedFields)
            )

        if any(value is None for value in args.values()):
            return iter(()) if iterate else []

        if "id" in args:
            runtimeObjectId = self._toOptionalInt(
                args.get("id")
            )

            if runtimeObjectId is None:
                return iter(()) if iterate else []

            runtimeObject = self._selectPostgresqlObjectForSelectById(
                runtimeObjectId
            )

            if runtimeObject is not None:
                result = []

                if self._matchesSelectByQuery(
                        runtimeObject,
                        args,
                ):
                    if (
                            objectFilter is None
                            or objectFilter(runtimeObject)
                    ):
                        result.append(runtimeObject)

                return iter(result) if iterate else result

            return iter(()) if iterate else []

        postgresqlObjects = (
            self._selectAllPostgresqlObjectsForSelectBy()
        )

        result = []

        for obj in postgresqlObjects:
            if not self._matchesSelectByQuery(
                    obj,
                    args,
            ):
                continue

            if (
                    objectFilter is not None
                    and not objectFilter(obj)
            ):
                continue

            result.append(obj)

        return iter(result) if iterate else result

    def _selectPostgresqlObjectForSelectById(
            self,
            runtimeObjectId,
    ):
        obj = self._selectProtocolByIdFromPostgresql(
            runtimeObjectId
        )

        if obj is not None:
            return obj

        obj = self._selectSetByIdFromPostgresql(
            runtimeObjectId,
            refreshParentProtocol=False,
        )

        if obj is not None:
            return obj

        return self._selectGenericObjectByIdFromPostgresql(
            runtimeObjectId
        )

    def selectRuntimeInputObjectById(
            self,
            objId,
    ):
        runtimeObjectId = (
            self._toOptionalInt(
                objId
            )
        )

        if runtimeObjectId is None:
            return None

        runtimeSet = (
            self
            ._selectSetByIdFromPostgresql(
                runtimeObjectId,
                refreshParentProtocol=False,
            )
        )

        if runtimeSet is not None:
            return runtimeSet

        return (
            self
            ._selectGenericObjectByIdFromPostgresql(
                runtimeObjectId,
                allowPartialTree=True,
            )
        )

    def _selectAllPostgresqlObjectsForSelectBy(self):
        result = []

        for row in self.flatMapper.getProtocols(self.projectId) or []:
            protocolId = self._toOptionalInt(
                row.get("protocolId")
            )

            if protocolId is None:
                continue

            protocol = self._runtimeProtocolsById.get(
                protocolId
            )

            if protocol is None:
                protocol = self._buildProtocolFromPostgresqlRow(
                    row
                )

            if protocol is not None:
                result.append(protocol)

        setRows = self.protocolGraphRepository.listPersistedSetOutputRows(
            mapper=self,
            projectId=self.projectId,
        )

        for row in setRows:
            runtimeObjectId = self._toOptionalInt(
                row.get("runtimeObjectId")
            )

            if runtimeObjectId is None:
                continue

            runtimeSet = self._selectSetByIdFromPostgresql(
                runtimeObjectId,
                refreshParentProtocol=False,
            )

            if runtimeSet is not None:
                result.append(runtimeSet)

        result.extend(
            self._selectAllGenericObjectsFromPostgresql()
        )

        creationTime = self._selectProjectCreationTimeFromPostgresql()

        if creationTime is not None:
            result.append(creationTime)

        result = self._deduplicateRuntimeObjects(result)

        return sorted(
            result,
            key=self._getSelectBySortKey,
        )

    def _getSelectBySortKey(self, obj):
        objectName = self._getSelectByStoredName(obj)

        if objectName == PROJECT_CREATION_TIME:
            return 0, 0

        objId = self._getObjId(obj)

        if objId is not None:
            return 1, objId

        return 2, 0

    def _matchesSelectByQuery(
            self,
            obj,
            query,
    ):
        for fieldName, expectedValue in query.items():
            actualValue = self._getSelectByFieldValue(
                obj,
                fieldName,
            )

            if not self._selectByValuesMatch(
                    fieldName,
                    actualValue,
                    expectedValue,
            ):
                return False

        return True

    def _getSelectByFieldValue(
            self,
            obj,
            fieldName,
    ):
        if fieldName == "id":
            return self._getObjId(obj)

        if fieldName == "parent_id":
            parentId = self._call(
                obj,
                "getObjParentId",
                getattr(obj, "_objParentId", None),
            )

            return self._toOptionalInt(parentId)

        if fieldName == "name":
            return self._getSelectByStoredName(obj)

        if fieldName == "classname":
            return self._getSelectByStoredClassName(obj)

        if fieldName == "value":
            value = self._call(
                obj,
                "getObjValue",
                None,
            )

            if self._call(obj, "isPointer", False):
                targetId = self._getObjId(value)

                if targetId is not None:
                    return targetId

            return self._scalarValue(value)

        if fieldName == "label":
            value = self._call(
                obj,
                "getObjLabel",
                getattr(obj, "_objLabel", ""),
            )

            return self._scalarValue(value)

        if fieldName == "comment":
            value = self._call(
                obj,
                "getObjComment",
                getattr(obj, "_objComment", ""),
            )

            return self._scalarValue(value)

        if fieldName == "creation":
            value = self._call(
                obj,
                "getObjCreation",
                getattr(obj, "_objCreation", None),
            )

            return self._scalarValue(value)

        return None

    @staticmethod
    def _getSelectByStoredName(obj):
        return str(
            getattr(obj, "_objName", "")
            or ""
        )

    def _getSelectByStoredClassName(self, obj):
        try:
            className = Mapper.getObjectPersistingClassName(
                obj
            )
        except Exception:
            className = self._getClassName(obj)

        return str(className or "")

    def _selectByValuesMatch(
            self,
            fieldName,
            actualValue,
            expectedValue,
    ):
        if (
                actualValue is None
                or expectedValue is None
        ):
            return False

        if fieldName in {
            "id",
            "parent_id",
        }:
            actualId = self._toOptionalInt(actualValue)
            expectedId = self._toOptionalInt(expectedValue)

            return (
                    actualId is not None
                    and expectedId is not None
                    and actualId == expectedId
            )

        if (
                fieldName == "classname"
                and isinstance(expectedValue, type)
        ):
            expectedValue = expectedValue.__name__

        if fieldName == "creation":
            actualValue = self._normalizeSelectByCreationValue(
                actualValue
            )

            expectedValue = self._normalizeSelectByCreationValue(
                expectedValue
            )

        return str(actualValue) == str(expectedValue)

    def _normalizeSelectByCreationValue(self, value):
        if isinstance(value, datetime):
            return self._formatProjectCreationTime(value)

        return str(value)


    @staticmethod
    def _isProjectCreationTimeQuery(args):
        name = str(args.get("name") or "").strip()

        if name != PROJECT_CREATION_TIME:
            return False

        return all(
            key == "name" or value is None
            for key, value in args.items()
        )

    def _selectProjectCreationTimeFromPostgresql(self):
        row = self.flatMapper.getProjectRuntimeMetadata(self.projectId)

        if not row:
            return None

        value = self._formatProjectCreationTime(row.get("createdAt"))

        if value is None:
            logger.warning(
                "PostgreSQL project does not have a valid creation time. "
                "projectId=%s createdAt=%s",
                self.projectId,
                row.get("createdAt"),
            )
            return None

        creationTime = String(value)
        self._setObjName(creationTime, PROJECT_CREATION_TIME)

        return creationTime

    @staticmethod
    def _formatProjectCreationTime(value):
        if value in (None, ""):
            return None

        if isinstance(value, datetime):
            creationTime = value
        else:
            valueText = str(value).strip()

            try:
                creationTime = datetime.fromisoformat(
                    valueText.replace("Z", "+00:00")
                )
            except ValueError:
                try:
                    creationTime = String.getDatetime(valueText)
                except ValueError:
                    return None

        if creationTime.tzinfo is not None:
            creationTime = creationTime.replace(tzinfo=None)

        return creationTime.strftime(
            String.DATETIME_FORMAT + String.FS
        )

    def selectByClass(
            self,
            className,
            includeSubclasses=True,
            iterate=False,
            objectFilter=None,
    ):
        if isinstance(className, type):
            requestedClassName = className.__name__
        else:
            requestedClassName = str(className or "").strip()

        requestedClass = self._resolveRuntimeObjectClass(requestedClassName)

        if objectFilter is not None and not callable(objectFilter):
            raise TypeError("objectFilter must be callable or None")

        if self._isProtocolClass(requestedClass):
            return self._selectProtocolByClass(
                className=className,
                requestedClassName=requestedClassName,
                requestedClass=requestedClass,
                includeSubclasses=includeSubclasses,
                iterate=iterate,
                objectFilter=objectFilter,
            )

        isSetRequest = (
                self._isScipionSetClass(requestedClass)
                or requestedClassName.startswith("SetOf")
        )

        if not isSetRequest:
            if not self._isSupportedGenericRuntimeObjectClass(requestedClass):
                raise NotImplementedError(
                    "PostgreSQL selectByClass does not support class: %s"
                    % requestedClassName
                )

            return self._selectGenericObjectByClass(
                className=className,
                requestedClassName=requestedClassName,
                requestedClass=requestedClass,
                includeSubclasses=includeSubclasses,
                iterate=iterate,
                objectFilter=objectFilter,
            )

        rows = self._getPostgresqlSetRowsForClass(
            requestedClassName=requestedClassName,
            requestedClass=requestedClass,
            includeSubclasses=includeSubclasses,
        )

        result = []

        for row in rows:
            runtimeObjectId = self._toOptionalInt(row.get("runtimeObjectId"))

            if runtimeObjectId is None:
                continue

            runtimeSet = self._selectSetByIdFromPostgresql(runtimeObjectId)

            if runtimeSet is None:
                continue

            if callable(objectFilter) and not objectFilter(runtimeSet):
                continue

            result.append(runtimeSet)

        return iter(result) if iterate else result

    def _selectProtocolByClass(
            self,
            className,
            requestedClassName,
            requestedClass,
            includeSubclasses,
            iterate,
            objectFilter,
    ):
        rows = self.flatMapper.getProtocols(self.projectId) or []
        result = []

        for row in rows:
            candidateClassName = str(
                row.get("protocolClassName") or ""
            ).strip()

            if not self._matchesRuntimeProtocolClass(
                    candidateClassName=candidateClassName,
                    requestedClassName=requestedClassName,
                    requestedClass=requestedClass,
                    includeSubclasses=includeSubclasses,
            ):
                continue

            protocol = self._getOrBuildProtocolFromPostgresqlRow(row)

            if protocol is None:
                continue

            if callable(objectFilter) and not objectFilter(protocol):
                continue

            result.append(protocol)

        return iter(result) if iterate else result

    def _selectGenericObjectByClass(
            self,
            className,
            requestedClassName,
            requestedClass,
            includeSubclasses,
            iterate,
            objectFilter,
    ):
        rows = self._getPostgresqlGenericObjectRowsForClass(
            requestedClassName=requestedClassName,
            requestedClass=requestedClass,
            includeSubclasses=includeSubclasses,
        )

        result = []

        for row in rows:
            runtimeObjectId = self._toOptionalInt(row.get("runtimeObjectId"))

            if runtimeObjectId is None:
                continue

            runtimeObject = self._selectGenericObjectByIdFromPostgresql(
                runtimeObjectId
            )

            if runtimeObject is None:
                continue

            if callable(objectFilter) and not objectFilter(runtimeObject):
                continue

            result.append(runtimeObject)

        return iter(result) if iterate else result

    def _getPostgresqlGenericObjectRowsForClass(
            self,
            requestedClassName,
            requestedClass,
            includeSubclasses,
    ):
        objectMapper = getattr(self, "objectMapper", None)
        reader = getattr(
            objectMapper,
            "listCanonicalStoredObjectRows",
            None,
        )

        if not callable(reader):
            return []

        canonicalClassName = (
            requestedClass.__name__
            if isinstance(requestedClass, type)
            else requestedClassName
        )

        if not includeSubclasses:
            return reader(
                projectId=self.projectId,
                className=canonicalClassName,
            )

        rows = reader(projectId=self.projectId)

        return [
            row
            for row in rows
            if self._matchesRuntimeGenericObjectClass(
                candidateClassName=row.get("className"),
                requestedClassName=canonicalClassName,
                requestedClass=requestedClass,
                includeSubclasses=True,
            )
        ]

    def _matchesRuntimeGenericObjectClass(
            self,
            candidateClassName,
            requestedClassName,
            requestedClass,
            includeSubclasses,
    ):
        candidateClassName = str(candidateClassName or "").strip()

        if not candidateClassName:
            return False

        if candidateClassName == requestedClassName:
            return True

        if not includeSubclasses:
            return False

        candidateClass = self._resolveRuntimeObjectClass(
            candidateClassName
        )

        if not self._isSupportedGenericRuntimeObjectClass(candidateClass):
            return False

        try:
            return issubclass(candidateClass, requestedClass)
        except TypeError:
            return False

    def _matchesRuntimeProtocolClass(
            self,
            candidateClassName,
            requestedClassName,
            requestedClass,
            includeSubclasses,
    ):
        candidateClassName = str(candidateClassName or "").strip()

        if not candidateClassName:
            return False

        if candidateClassName == requestedClassName:
            return True

        if not includeSubclasses:
            return False

        candidateClass = self._resolveRuntimeObjectClass(
            candidateClassName
        )

        if candidateClass is None or requestedClass is None:
            return False

        try:
            return issubclass(candidateClass, requestedClass)
        except TypeError:
            return False

    def _getPostgresqlSetRowsForClass(
            self,
            requestedClassName,
            requestedClass,
            includeSubclasses,
    ):
        canonicalClassName = (
            requestedClass.__name__
            if isinstance(requestedClass, type)
            else requestedClassName
        )

        if not includeSubclasses or requestedClass is None:
            return self.protocolGraphRepository.listPersistedSetOutputRows(
                mapper=self,
                projectId=self.projectId,
                className=canonicalClassName,
            )

        rows = self.protocolGraphRepository.listPersistedSetOutputRows(
            mapper=self,
            projectId=self.projectId,
        )

        return [
            row
            for row in rows
            if self._matchesRuntimeSetClass(
                candidateClassName=row.get("className"),
                requestedClassName=canonicalClassName,
                requestedClass=requestedClass,
            )
        ]

    def _matchesRuntimeSetClass(
            self,
            candidateClassName,
            requestedClassName,
            requestedClass,
    ):
        candidateClassName = str(candidateClassName or "").strip()

        if not candidateClassName:
            return False

        candidateClass = self._resolveRuntimeObjectClass(candidateClassName)

        if candidateClass is None or requestedClass is None:
            return candidateClassName == requestedClassName

        try:
            return issubclass(candidateClass, requestedClass)
        except TypeError:
            return False

    def _resolveRuntimeObjectClass(self, className):
        if isinstance(className, type):
            return className

        className = str(className or "").strip()

        if not className:
            return None

        if className == "Set":
            return ScipionSet

        if className == "Protocol":
            return Protocol

        classes = getattr(self, "dictClasses", None) or {}

        candidate = classes.get(className)

        if isinstance(candidate, type):
            return candidate

        for registeredName, registeredClass in classes.items():
            if str(registeredName).lower() != className.lower():
                continue

            if isinstance(registeredClass, type):
                return registeredClass

        coreObjectClass = getattr(
            pwobject,
            className,
            None,
        )

        if isinstance(
                coreObjectClass,
                type,
        ):
            try:
                if issubclass(
                        coreObjectClass,
                        ScipionObject,
                ):
                    return coreObjectClass
            except TypeError:
                pass

        protocolClass = self._resolveProtocolClass(className)

        if isinstance(protocolClass, type):
            return protocolClass

        return None

    @staticmethod
    def _isProtocolClass(candidateClass):
        if not isinstance(candidateClass, type):
            return False

        try:
            return issubclass(candidateClass, Protocol)
        except TypeError:
            return False

    @staticmethod
    def _isScipionSetClass(candidateClass):
        if not isinstance(candidateClass, type):
            return False

        try:
            return issubclass(candidateClass, ScipionSet)
        except TypeError:
            return False

    def _deduplicateRuntimeObjects(self, objects):
        result = []
        identities = set()

        for obj in objects or []:
            objId = self._getObjId(obj)

            if objId is not None:
                identity = str(objId)

                if identity in identities:
                    continue

                identities.add(identity)

            result.append(obj)

        return result

    def getParent(self, obj):
        """
        Return the direct parent without refreshing or reattaching it.

        Native PostgreSQL objects may already carry their parent through
        _objParent. Otherwise, resolve the runtime parent id from PostgreSQL.
        """
        if obj is None:
            return None

        parent = getattr(obj, "_objParent", None)

        if parent is not None:
            return parent

        parentId = self._toOptionalInt(
            self._call(
                obj,
                "getObjParentId",
                getattr(obj, "_objParentId", None),
            )
        )

        if parentId is None:
            return None

        return self._selectRelationObjectById(parentId)

    def deleteAll(self):
        deleteResult = self.flatMapper.deleteProjectRuntimeData(
            self.projectId
        )

        self.runtimeSetFactory.clearCaches()
        self._runtimeProtocolsById.clear()

        logger.debug(
            "Deleted all PostgreSQL runtime objects. "
            "projectId=%s deletedProtocols=%s "
            "deletedSets=%s deletedObjects=%s "
            "deletedRelations=%s",
            self.projectId,
            deleteResult.get(
                "deletedProtocolsCount",
                0,
            ),
            deleteResult.get(
                "deletedSetsCount",
                0,
            ),
            deleteResult.get(
                "deletedObjectsCount",
                0,
            ),
            deleteResult.get(
                "deletedRelationsCount",
                0,
            ),
        )

    def delete(self, obj):
        if obj is None:
            return

        if isinstance(obj, Protocol):

            self.flatMapper.deleteProtocol(
                self.projectId,
                [obj],
            )

            return

        objId = self._toOptionalInt(
            self._getObjId(obj)
        )

        if objId is None:
            return

        isSetObject = (
                isinstance(obj, ScipionSet)
                or self._isSetLike(obj)
        )

        persistedSet = self.protocolGraphRepository.getPersistedSetOutputRowByRuntimeObjectId(
            mapper=self,
            projectId=self.projectId,
            runtimeObjectId=objId,
        )

        if persistedSet is not None:
            if not isSetObject:
                raise TypeError(
                    "Runtime object %s resolves to a PostgreSQL Set, "
                    "but the supplied object class is %s."
                    % (
                        objId,
                        self._getClassName(obj),
                    )
                )

            setId = self._toOptionalInt(
                persistedSet.get("setId")
            )

            objectId = self._toOptionalInt(
                persistedSet.get("objectId")
            )

            if setId is None or objectId is None:
                raise RuntimeError(
                    "Persisted PostgreSQL Set %s does not expose "
                    "its set or canonical object identity."
                    % objId
                )

            deleteResult = self.setMapper.deleteStoredSetOutput(
                projectId=self.projectId,
                setId=setId,
                objectId=objectId,
                runtimeObjectId=objId,
            )

            self.runtimeSetFactory.evictRuntimeSet(
                projectId=self.projectId,
                runtimeObjectId=objId,
                runtimeSet=obj,
            )

            logger.debug(
                "Deleted PostgreSQL runtime Set. "
                "projectId=%s runtimeObjectId=%s "
                "deletedSets=%s deletedObjects=%s "
                "deletedRelations=%s",
                self.projectId,
                objId,
                deleteResult.get(
                    "deletedSetsCount",
                    0,
                ),
                deleteResult.get(
                    "deletedObjectsCount",
                    0,
                ),
                deleteResult.get(
                    "deletedRelationsCount",
                    0,
                ),
            )

            return

        if isSetObject:
            return

        if not isinstance(obj, ScipionObject):
            logger.debug(
                "PostgresqlRuntimeMapper.delete skipped "
                "unsupported object. projectId=%s "
                "runtimeObjectId=%s className=%s",
                self.projectId,
                objId,
                self._getClassName(obj),
            )

            return

        deleteResult = self.objectMapper.deleteStoredObjectSubtreesByScipionObjId(
            projectId=self.projectId,
            scipionObjId=objId,
        )

        logger.debug(
            "Deleted PostgreSQL generic object tree. "
            "projectId=%s runtimeObjectId=%s "
            "deletedObjects=%s deletedRelations=%s",
            self.projectId,
            objId,
            deleteResult.get(
                "deletedObjectsCount",
                0,
            ),
            deleteResult.get(
                "deletedRelationsCount",
                0,
            ),
        )

    # ---------------------------------------------------------------------
    # Relations API
    # ---------------------------------------------------------------------

    def insertRelation(self, relName, creatorObj, parentObj, childObj,
                       parentExt=None, childExt=None):
        self.insertRelationData(
            relName,
            self._requireObjId(creatorObj),
            self._requireObjId(parentObj),
            self._requireObjId(childObj),
            parentExt,
            childExt,
        )

    def insertRelationData(self, relName, creatorId, parentId, childId,
                           parentExtended=None, childExtended=None):

        parentExtended = self._normalizeRelationExtended(parentExtended)
        childExtended = self._normalizeRelationExtended(childExtended)

        self.db.execute(
            """
            INSERT INTO scipion_relations (
                "projectId",
                name,
                "creatorObjId",
                "parentObjId",
                "childObjId",
                "parentExtended",
                "childExtended"
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                self.projectId,
                str(relName),
                int(creatorId),
                int(parentId),
                int(childId),
                parentExtended,
                childExtended,
            ),
        )

    def _resolveCanonicalScipionObjectRowId(self, runtimeObjId) -> Optional[int]:
        runtimeObjId = self._toOptionalInt(runtimeObjId)

        if runtimeObjId is None:
            return None

        row = self.db.fetchOne(
            """
            SELECT o.id
              FROM scipion_objects o
             WHERE o."projectId" = %s
               AND o."scipionObjId" = %s
             ORDER BY o.id DESC
             LIMIT 1
            """,
            (
                self.projectId,
                int(runtimeObjId),
            ),
        )

        if not row:
            return None

        return self._toOptionalInt(row.get("id"))

    def deleteRelations(self, creatorObj):
        creatorId = self._getObjId(creatorObj)
        if creatorId is None:
            return

        self.db.execute(
            """
            DELETE FROM scipion_relations
             WHERE "projectId" = %s
               AND "creatorObjId" = %s
            """,
            (self.projectId, int(creatorId)),
        )

    def _selectPostgresqlRelations(
            self,
            creatorId: Optional[int] = None,
            relationName: Optional[str] = None,
            parentId: Optional[int] = None,
            childId: Optional[int] = None,
    ):
        """
        Read relation rows from PostgreSQL using the column names exposed
        by Scipion's native SQLite Relations table.

        This method returns relation metadata only. It never reconstructs,
        stores or modifies the related parent or child objects.
        """
        filters = [
            '"projectId" = %s',
        ]
        values = [
            self.projectId,
        ]

        if creatorId is not None:
            filters.append(
                '"creatorObjId" = %s'
            )
            values.append(
                int(creatorId)
            )

        if relationName is not None:
            filters.append(
                'name = %s'
            )
            values.append(
                str(relationName)
            )

        if parentId is not None:
            filters.append(
                '"parentObjId" = %s'
            )
            values.append(
                int(parentId)
            )

        if childId is not None:
            filters.append(
                '"childObjId" = %s'
            )
            values.append(
                int(childId)
            )

        whereSql = "\n               AND ".join(
            filters
        )

        return self.db.fetchAll(
            f"""
            SELECT
                id,
                "creatorObjId" AS parent_id,
                name,
                NULL::text AS classname,
                NULL::text AS value,
                NULL::text AS label,
                NULL::text AS comment,
                "parentObjId" AS object_parent_id,
                "childObjId" AS object_child_id,
                "createdAt" AS creation,
                NULLIF(
                    "parentExtended",
                    ''
                ) AS object_parent_extended,
                NULLIF(
                    "childExtended",
                    ''
                ) AS object_child_extended
              FROM scipion_relations
             WHERE {whereSql}
             ORDER BY id ASC
            """,
            tuple(values),
        )

    def getRelationsByCreator(self, creatorObj):
        creatorId = self._requireObjId(creatorObj)
        return self._selectPostgresqlRelations(creatorId=creatorId)

    def getRelationsByName(self, relationName):
        return self._selectPostgresqlRelations(relationName=relationName)

    def _selectRelationObjectById(self, objId):
        """
        Resolve one PostgreSQL relation target without refreshing any owner
        protocol or modifying its outputs.
        """
        obj = self._selectProtocolByIdFromPostgresql(objId, refreshCached=False)

        if obj is not None:
            return obj

        obj = self._selectSetByIdFromPostgresql(objId, refreshParentProtocol=False)

        if obj is not None:
            return obj

        return self._selectGenericObjectByIdFromPostgresql(objId)

    def getRelationChilds(self, relName, parentObj):
        parentId = self._requireObjId(parentObj)

        relations = self._selectPostgresqlRelations(
            relationName=relName,
            parentId=parentId,
        )

        return [
            self._selectRelationObjectById(row["object_child_id"])
            for row in relations
        ]

    def getRelationParents(self, relName, childObj):
        childId = self._requireObjId(childObj)

        relations = self._selectPostgresqlRelations(
            relationName=relName,
            childId=childId,
        )

        return [
            self._selectRelationObjectById(row["object_parent_id"])
            for row in relations
        ]

    # ---------------------------------------------------------------------
    # PostgreSQL persistence helpers
    # ---------------------------------------------------------------------

    def _storeProtocol(self, protocol: Protocol):
        protocolId = self._ensureObjId(protocol)
        if protocolId is None:
            raise ValueError("Cannot store protocol without object id.")

        context = self._buildProtocolContext(protocol)
        protocolDbId = self.flatMapper.saveProtocol(context)

        steps = self._buildProtocolSteps(protocol)
        if steps:
            self.flatMapper.replaceProtocolSteps(
                projectId=self.projectId,
                protocolDbId=int(protocolDbId),
                protocolId=int(protocolId),
                steps=steps,
            )

    def _prepareNativeSetForPostgresqlSnapshot(
            self,
            scipionSet,
    ) -> Dict[str, Any]:
        """
        Reopen a newly-created native SQLite Set before iterating it.

        A SqliteFlatMapper created for a new file does not build
        _objColumns during construction. Once the first item creates
        the tables, reopening the mapper loads the final schema and
        makes the Set safe to iterate for PostgreSQL snapshotting.
        """
        runtimeChecker = getattr(
            scipionSet,
            "isPostgresqlRuntimeOutput",
            None,
        )

        if callable(runtimeChecker):
            try:
                if runtimeChecker():
                    return {
                        "reopened": False,
                        "reason": (
                            "postgresql_runtime_set"
                        ),
                    }

            except Exception:
                pass

        currentMapper = getattr(
            scipionSet,
            "_mapper",
            None,
        )

        if not isinstance(
                currentMapper,
                SqliteFlatMapper,
        ):
            return {
                "reopened": False,
                "reason": (
                    "not_native_sqlite_set"
                ),
            }

        # An empty new Set has no item schema yet.
        # iterItems() already handles that case.
        if getattr(
                currentMapper,
                "doCreateTables",
                False,
        ):
            return {
                "reopened": False,
                "reason": (
                    "empty_native_set"
                ),
            }

        if hasattr(
                currentMapper,
                "_objColumns",
        ):
            return {
                "reopened": False,
                "reason": (
                    "mapper_schema_ready"
                ),
            }

        fileName = scipionSet.getFileName()

        if not fileName:
            raise RuntimeError(
                "Cannot prepare native output Set "
                "without a mapper filename."
            )

        # Commit items/properties before replacing
        # the current mapper instance.
        scipionSet.write()
        scipionSet.close()
        scipionSet.load()

        reopenedMapper = getattr(
            scipionSet,
            "_mapper",
            None,
        )

        if (
                not isinstance(
                    reopenedMapper,
                    SqliteFlatMapper,
                )
                or not hasattr(
                    reopenedMapper,
                    "_objColumns",
                )
        ):
            raise RuntimeError(
                "Native output Set mapper schema "
                "could not be initialized after "
                "reopening %s."
                % fileName
            )

        return {
            "reopened": True,
            "reason": (
                "native_mapper_schema_initialized"
            ),
            "fileName": str(
                fileName
            ),
        }

    def getPostgresqlOutputSetCapability(
            self,
            setClass,
    ) -> Dict[str, Any]:
        if not isinstance(
                setClass,
                type,
        ):
            return {
                "supported": False,
                "reason": "invalid_set_class",
            }

        try:
            if not issubclass(
                    setClass,
                    ScipionSet,
            ):
                return {
                    "supported": False,
                    "reason": "not_a_scipion_set",
                }
        except TypeError:
            return {
                "supported": False,
                "reason": "invalid_set_class",
            }

        classRegistry = (
            self.runtimeSetFactory
            ._loadClasses(
                getattr(
                    self,
                    "dictClasses",
                    None,
                )
            )
        )

        itemType = getattr(
            setClass,
            "ITEM_TYPE",
            None,
        )

        if isinstance(
                itemType,
                str,
        ):
            nativeItemClass = (
                classRegistry.get(
                    itemType
                )
            )
        else:
            nativeItemClass = itemType

        if not isinstance(
                nativeItemClass,
                type,
        ):
            return {
                "supported": False,
                "reason": (
                    "unresolved_item_class"
                ),
            }

        if (
                self.runtimeSetFactory
                        ._isScipionSetClass(
                    nativeItemClass
                )
        ):
            nestedItemType = getattr(
                nativeItemClass,
                "ITEM_TYPE",
                None,
            )

            if isinstance(
                    nestedItemType,
                    str,
            ):
                nativeNestedItemClass = (
                    classRegistry.get(
                        nestedItemType
                    )
                )

            else:
                nativeNestedItemClass = (
                    nestedItemType
                )

            if not isinstance(
                    nativeNestedItemClass,
                    type,
            ):
                return {
                    "supported": False,
                    "reason": (
                        "unresolved_nested_item_class"
                    ),
                    "itemClassName": (
                        nativeItemClass.__name__
                    ),
                }

            # The current implementation supports:
            #
            # root Set
            #   └── item Set
            #         └── normal items
            #
            # Do not silently accept deeper hierarchies yet.
            if (
                    self.runtimeSetFactory
                            ._isScipionSetClass(
                        nativeNestedItemClass
                    )
            ):
                return {
                    "supported": False,
                    "reason": (
                        "nested_set_depth_unsupported"
                    ),
                    "itemClassName": (
                        nativeItemClass.__name__
                    ),
                    "childItemClassName": (
                        nativeNestedItemClass
                        .__name__
                    ),
                }

            return {
                "supported": True,
                "reason": None,
                "storageKind": (
                    "nested_logical_tables"
                ),
                "nestedSetItems": True,
                "itemClassName": (
                    nativeItemClass.__name__
                ),
                "childItemClassName": (
                    nativeNestedItemClass.__name__
                ),
            }

        return {
            "supported": True,
            "reason": None,
            "storageKind": "flat_items",
            "nestedSetItems": False,
            "itemClassName": (
                nativeItemClass.__name__
            ),
        }

    @staticmethod
    def _closeSetMapper(runtimeSet) -> None:
        currentMapper = getattr(runtimeSet, "_mapper", None)

        if currentMapper is not None:
            closeMapper = getattr(currentMapper, "close", None)

            if callable(closeMapper):
                closeMapper()

        runtimeSet._mapper = None

    @staticmethod
    def _captureNativeSetAdoptionState(runtimeSet) -> Dict[str, Any]:
        return {
            "objId": runtimeSet.getObjId(),
            "name": runtimeSet.getObjName(),
            "label": runtimeSet.getObjLabel(),
            "parentId": runtimeSet.getObjParentId(),
            "objParent": getattr(runtimeSet, "_objParent", None),
            "hasRuntimeParentRef": "_postgresqlRuntimeParentRef" in runtimeSet.__dict__,
            "runtimeParentRef": getattr(runtimeSet, "_postgresqlRuntimeParentRef", None),
        }

    def _restoreNativeSetAfterFailedAdoption(
            self,
            runtimeSet,
            originalClass,
            originalState=None,
    ) -> None:
        try:
            self._closeSetMapper(runtimeSet)
        except Exception:
            logger.debug(
                "Could not close PostgreSQL mapper after failed Set adoption.",
                exc_info=True,
            )

        if runtimeSet.__class__ is not originalClass:
            try:
                runtimeSet.__class__ = originalClass
            except TypeError:
                logger.exception(
                    "Could not restore native Set class after failed PostgreSQL adoption. "
                    "currentClass=%s originalClass=%s objectId=%s",
                    runtimeSet.__class__.__name__,
                    originalClass.__name__,
                    runtimeSet.getObjId(),
                )
                return

        for attributeName in (
                "_postgresqlNativeSetClass",
                "_postgresqlRuntimeInfo",
                "_postgresqlRuntimeProperties",
                "_postgresqlRuntimeClasses",
                "_postgresqlRuntimeValues",
                "_postgresqlSqliteMaterializer",
                "_postgresqlMaterializedFileName",
                "_postgresqlMaterializedRevision",
                "_postgresqlSupportsNativeWrite",
                "_postgresqlWritable",
                "_postgresqlMapperFactory",
                "_postgresqlRuntimeParentRef",
        ):
            runtimeSet.__dict__.pop(attributeName, None)

        if originalState is not None:
            originalObjectId = originalState["objId"]

            if originalObjectId is None:
                runtimeSet.setObjId(None)
            else:
                self._setObjId(runtimeSet, originalObjectId)

            runtimeSet.setName(originalState["name"])
            runtimeSet.setObjLabel(originalState["label"])
            runtimeSet._objParentId = originalState["parentId"]
            runtimeSet._objParent = originalState["objParent"]

            if originalState["hasRuntimeParentRef"]:
                runtimeSet._postgresqlRuntimeParentRef = originalState["runtimeParentRef"]

        loadSet = getattr(runtimeSet, "load", None)

        if callable(loadSet):
            try:
                loadSet()
            except Exception:
                logger.exception(
                    "Could not reopen native Set after failed PostgreSQL adoption. "
                    "className=%s objectId=%s",
                    originalClass.__name__,
                    runtimeSet.getObjId(),
                )

    def _adoptPopulatedPostgresqlOutputSet(
            self,
            protocol,
            protocolDbId: int,
            setClass,
            provisionalOutputName: str,
            reservationToken,
            runtimeSet,
    ):
        originalClass = runtimeSet.__class__
        originalState = self._captureNativeSetAdoptionState(runtimeSet)
        snapshotReport = None
        runtimeObjectId = None

        try:
            self._prepareNativeSetForPostgresqlSnapshot(runtimeSet)

            runtimeObjectId = self._assignFreshRuntimeObjectId(
                runtimeSet
            )

            snapshotReport = self.setMapper.storeSet(
                projectId=self.projectId,
                protocolDbId=protocolDbId,
                outputName=provisionalOutputName,
                scipionSet=runtimeSet,
                runtimeReserved=True,
                reservationToken=reservationToken,
            )

            storedRuntimeObjectId = snapshotReport.get(
                "runtimeObjectId"
            )

            if (
                    storedRuntimeObjectId is None
                    or int(storedRuntimeObjectId) != runtimeObjectId
            ):
                raise RuntimeError(
                    "PostgreSQL populated Set reservation changed "
                    "runtime identity. expected=%s actual=%s"
                    % (
                        runtimeObjectId,
                        storedRuntimeObjectId,
                    )
                )

            outputInfo = {
                "setId": int(snapshotReport["setId"]),
                "rootTableId": int(snapshotReport["rootTableId"]),
                "projectId": int(self.projectId),
                "protocolDbId": int(protocolDbId),
                "protocolId": int(protocol.getObjId()),
                "objectId": int(snapshotReport["rootObjectId"]),
                "runtimeObjectId": int(runtimeObjectId),
                "outputName": provisionalOutputName,
                "className": str(snapshotReport["setClassName"]),
                "setClassName": str(snapshotReport["setClassName"]),
                "itemClassName": str(snapshotReport["itemClassName"]),
                "properties": dict(snapshotReport.get("properties") or {}),
            }

            self._closeSetMapper(runtimeSet)

            self.runtimeSetFactory._promoteRuntimeSetInstance(
                runtimeSet=runtimeSet,
                nativeSetClass=setClass,
            )

            runtimeSet = self.runtimeSetFactory.build(
                db=self.db,
                parent=protocol,
                outputName=provisionalOutputName,
                outputInfo=outputInfo,
                classes=getattr(self, "dictClasses", None),
                runtimeSet=runtimeSet,
                cache=True,
            )

            setPostgresqlRuntimeParentReference(
                runtimeObject=runtimeSet,
                parent=protocol,
            )

            runtimeSet.enablePostgresqlWrite()
            return runtimeSet

        except Exception:
            self._restoreNativeSetAfterFailedAdoption(
                runtimeSet=runtimeSet,
                originalClass=originalClass,
                originalState=originalState,
            )

            if (
                    snapshotReport is not None
                    and runtimeObjectId is not None
            ):
                try:
                    self.setMapper.deleteStoredSetOutput(
                        projectId=self.projectId,
                        setId=int(snapshotReport["setId"]),
                        objectId=int(snapshotReport["rootObjectId"]),
                        runtimeObjectId=int(runtimeObjectId),
                    )
                except Exception:
                    logger.exception(
                        "Could not delete failed populated PostgreSQL Set snapshot. "
                        "projectId=%s protocolId=%s runtimeObjectId=%s",
                        self.projectId,
                        protocol.getObjId(),
                        runtimeObjectId,
                    )

            raise

    def createPostgresqlOutputSet(
            self,
            protocol,
            setClass,
            provisionalOutputName: str,
            constructorKwargs=None,
            reservationToken=None,
            runtimeSet=None,
    ):
        capability = (
            self
            .getPostgresqlOutputSetCapability(
                setClass
            )
        )

        if not capability.get(
                "supported"
        ):
            raise NotImplementedError(
                "Native PostgreSQL output Set "
                "creation is not supported: %s"
                % capability.get(
                    "reason"
                )
            )

        protocolDbId = (
            self
            ._resolveProtocolDbIdFromObject(
                protocol
            )
        )

        if protocolDbId is None:
            raise RuntimeError(
                "Cannot create a PostgreSQL output "
                "Set without its owner protocol."
            )

        if runtimeSet is not None:
            if not isinstance(runtimeSet, setClass):
                raise TypeError(
                    "Cannot adopt output Set %s as %s."
                    % (
                        runtimeSet.__class__.__name__,
                        setClass.__name__,
                    )
                )

            if not runtimeSet.isEmpty():
                return self._adoptPopulatedPostgresqlOutputSet(
                    protocol=protocol,
                    protocolDbId=protocolDbId,
                    setClass=setClass,
                    provisionalOutputName=provisionalOutputName,
                    reservationToken=reservationToken,
                    runtimeSet=runtimeSet,
                )

        originalRuntimeSetClass = None
        originalRuntimeSetState = None

        if runtimeSet is None:
            runtimeSetClass = (
                self.runtimeSetFactory
                ._getRuntimeSetClass(
                    setClass
                )
            )

            runtimeSet = runtimeSetClass(
                **dict(
                    constructorKwargs
                    or {}
                )
            )
        else:
            originalRuntimeSetClass = runtimeSet.__class__
            originalRuntimeSetState = self._captureNativeSetAdoptionState(runtimeSet)
            self._closeSetMapper(runtimeSet)
            self.runtimeSetFactory._promoteRuntimeSetInstance(
                runtimeSet=runtimeSet,
                nativeSetClass=setClass,
            )

        if originalRuntimeSetClass is None:
            runtimeObjectId = self._ensureObjId(
                runtimeSet
            )
        else:
            runtimeObjectId = self._assignFreshRuntimeObjectId(
                runtimeSet
            )

        runtimeSet.setName(
            provisionalOutputName
        )

        runtimeSet.setObjLabel(
            provisionalOutputName
        )

        runtimeSet._objParentId = (
            protocol.getObjId()
        )

        setPostgresqlRuntimeParentReference(
            runtimeObject=runtimeSet,
            parent=protocol,
        )

        reservation = None

        try:
            reservation = (
                self.setMapper
                .reserveRuntimeSet(
                    projectId=self.projectId,
                    protocolDbId=protocolDbId,
                    outputName=(
                        provisionalOutputName
                    ),
                    scipionSet=runtimeSet,
                    reservationToken=(
                        reservationToken
                    ),
                )
            )

            reservation["protocolId"] = int(
                protocol.getObjId()
            )

            runtimeSet = (
                self.runtimeSetFactory
                .build(
                    db=self.db,
                    parent=protocol,
                    outputName=(
                        provisionalOutputName
                    ),
                    outputInfo=reservation,
                    classes=getattr(
                        self,
                        "dictClasses",
                        None,
                    ),
                    runtimeSet=runtimeSet,
                    cache=True,
                )
            )

            setPostgresqlRuntimeParentReference(
                runtimeObject=runtimeSet,
                parent=protocol,
            )

            runtimeSet.enablePostgresqlWrite()

            return runtimeSet

        except Exception:
            if reservation is not None:
                try:
                    self.setMapper.discardReservedRuntimeSet(
                        projectId=self.projectId,
                        protocolDbId=protocolDbId,
                        runtimeObjectId=runtimeObjectId,
                    )

                except Exception:
                    logger.exception(
                        "Could not discard failed "
                        "PostgreSQL output Set reservation. "
                        "projectId=%s protocolId=%s "
                        "runtimeObjectId=%s",
                        self.projectId,
                        protocol.getObjId(),
                        runtimeObjectId,
                    )
            if originalRuntimeSetClass is not None:
                self._restoreNativeSetAfterFailedAdoption(
                    runtimeSet=runtimeSet,
                    originalClass=originalRuntimeSetClass,
                    originalState=originalRuntimeSetState,
                )

            raise

    def replacePostgresqlOutputSetSnapshot(
            self,
            protocol,
            outputName: str,
            runtimeSet,
            sourceSet,
    ):
        protocolDbId = self._resolveProtocolDbIdFromObject(
            protocol
        )

        if protocolDbId is None:
            raise RuntimeError(
                "Cannot replace PostgreSQL output "
                "without its owner protocol."
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
                "Existing protocol output is not "
                "a PostgreSQL runtime Set."
            )

        runtimeObjectId = self._getObjId(
            runtimeSet
        )

        if runtimeObjectId is None:
            raise RuntimeError(
                "Existing PostgreSQL output Set "
                "does not have a runtime object id."
            )

        nativeSetClass = getattr(
            runtimeSet,
            "_postgresqlNativeSetClass",
            None,
        )

        if not isinstance(nativeSetClass, type):
            nativeSetClass = runtimeSet.getClass()

        if not isinstance(sourceSet, nativeSetClass):
            raise TypeError(
                "Cannot replace PostgreSQL output %s "
                "using Set class %s. Expected %s."
                % (
                    outputName,
                    sourceSet.__class__.__name__,
                    nativeSetClass.__name__,
                )
            )

        originalSourceClass = sourceSet.__class__
        originalSourceState = (
            self._captureNativeSetAdoptionState(
                sourceSet
            )
        )

        try:
            self._prepareNativeSetForPostgresqlSnapshot(
                sourceSet
            )

            self._setObjId(
                sourceSet,
                runtimeObjectId,
            )

            sourceSet.setName(
                outputName
            )

            sourceSet.setObjLabel(
                outputName
            )

            sourceSet._objParentId = (
                protocol.getObjId()
            )

            snapshotReport = self.setMapper.storeSet(
                projectId=self.projectId,
                protocolDbId=protocolDbId,
                outputName=outputName,
                scipionSet=sourceSet,
                runtimeReserved=False,
                replaceRuntimeOutput=True,
            )

            storedRuntimeObjectId = (
                snapshotReport.get(
                    "runtimeObjectId"
                )
            )

            if (
                    storedRuntimeObjectId is None
                    or int(storedRuntimeObjectId)
                    != int(runtimeObjectId)
            ):
                raise RuntimeError(
                    "PostgreSQL output snapshot changed "
                    "runtime identity. expected=%s actual=%s"
                    % (
                        runtimeObjectId,
                        storedRuntimeObjectId,
                    )
                )

            runtimeInfo = getattr(
                runtimeSet,
                "_postgresqlRuntimeInfo",
                {},
            )

            expectedSetId = (
                runtimeInfo.get("setId")
                if isinstance(runtimeInfo, dict)
                else None
            )

            storedSetId = snapshotReport.get(
                "setId"
            )

            if (
                    expectedSetId is not None
                    and storedSetId is not None
                    and int(storedSetId)
                    != int(expectedSetId)
            ):
                raise RuntimeError(
                    "PostgreSQL output snapshot changed "
                    "Set identity. expected=%s actual=%s"
                    % (
                        expectedSetId,
                        storedSetId,
                    )
                )

            self._closeSetMapper(
                sourceSet
            )

            if not self._updateSetFromPostgresql(
                    runtimeSet
            ):
                raise RuntimeError(
                    "Updated PostgreSQL output Set "
                    "could not be refreshed in place. "
                    "outputName=%s runtimeObjectId=%s"
                    % (
                        outputName,
                        runtimeObjectId,
                    )
                )

            runtimeSet.enablePostgresqlWrite()

            return runtimeSet

        except Exception:
            self._restoreNativeSetAfterFailedAdoption(
                runtimeSet=sourceSet,
                originalClass=originalSourceClass,
                originalState=originalSourceState,
            )

            raise

    def finalizePostgresqlOutputSet(
            self,
            protocol,
            outputName: str,
            runtimeSet,
    ) -> Dict[str, Any]:
        protocolDbId = (
            self
            ._resolveProtocolDbIdFromObject(
                protocol
            )
        )

        if protocolDbId is None:
            raise RuntimeError(
                "Cannot finalize PostgreSQL output "
                "without its owner protocol."
            )

        runtimeInfo = getattr(
            runtimeSet,
            "_postgresqlRuntimeInfo",
            {},
        )

        provisionalName = (
            runtimeInfo.get(
                "outputName"
            )
            if isinstance(
                runtimeInfo,
                dict,
            )
            else None
        )

        currentLabel = None

        try:
            currentLabel = (
                runtimeSet.getObjLabel()
            )
        except Exception:
            pass

        runtimeSet.setName(
            outputName
        )

        if (
                not currentLabel
                or currentLabel
                == provisionalName
        ):
            runtimeSet.setObjLabel(
                outputName
            )

        runtimeSet._objParentId = (
            protocol.getObjId()
        )

        setPostgresqlRuntimeParentReference(
            runtimeObject=runtimeSet,
            parent=protocol,
        )

        report = (
            self.setMapper
            .finalizeRuntimeSetOutput(
                projectId=self.projectId,
                protocolDbId=protocolDbId,
                outputName=outputName,
                scipionSet=runtimeSet,
            )
        )

        runtimeSet._postgresqlRuntimeInfo = dict(
            report
        )

        runtimeSet._postgresqlRuntimeProperties = dict(
            report.get(
                "properties"
            )
            or {}
        )

        self.runtimeSetFactory._cacheRuntimeSet(
            runtimeSet
        )

        return report

    def discardPostgresqlOutputSet(
            self,
            protocol,
            runtimeSet,
    ) -> bool:
        protocolDbId = (
            self
            ._resolveProtocolDbIdFromObject(
                protocol
            )
        )

        runtimeObjectId = self._getObjId(
            runtimeSet
        )

        if (
                protocolDbId is None
                or runtimeObjectId is None
        ):
            return False

        deleted = (
            self.setMapper
            .discardReservedRuntimeSet(
                projectId=self.projectId,
                protocolDbId=protocolDbId,
                runtimeObjectId=(
                    runtimeObjectId
                ),
            )
        )

        if deleted:
            self.runtimeSetFactory.evictRuntimeSet(
                projectId=self.projectId,
                runtimeObjectId=runtimeObjectId,
                runtimeSet=runtimeSet,
            )

        return bool(
            deleted
        )

    def _storeSetObject(self, scipionSet):
        ownerProtocol = (
            self._findOwnerProtocol(
                scipionSet
            )
        )

        protocolDbId = (
            self
            ._resolveProtocolDbIdFromObject(
                ownerProtocol
            )
        )

        outputName = (
                self._getObjectName(
                    scipionSet
                )
                or self._getClassName(
            scipionSet
        )
        )

        if (
                protocolDbId is None
                or not outputName
        ):
            logger.debug(
                "Skipping runtime set persistence "
                "without owner/outputName: %s",
                scipionSet,
            )

            return

        runtimeChecker = getattr(
            scipionSet,
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

        if isPostgresqlRuntimeSet:
            ownerProtocol = (
                self._findOwnerProtocol(
                    scipionSet
                )
            )

            if ownerProtocol is None:
                raise RuntimeError(
                    "PostgreSQL output Set %s does not "
                    "have an owner protocol."
                    % self._getObjId(
                        scipionSet
                    )
                )

            self.finalizePostgresqlOutputSet(
                protocol=ownerProtocol,
                outputName=outputName,
                runtimeSet=scipionSet,
            )

            return

        preparationReport = (
            self
            ._prepareNativeSetForPostgresqlSnapshot(
                scipionSet
            )
        )

        logger.debug(
            "Prepared runtime Set for PostgreSQL "
            "snapshot. projectId=%s "
            "protocolDbId=%s outputName=%s "
            "report=%s",
            self.projectId,
            protocolDbId,
            outputName,
            preparationReport,
        )

        self.setMapper.storeSet(
            projectId=self.projectId,
            protocolDbId=protocolDbId,
            outputName=outputName,
            scipionSet=scipionSet,
        )

    def _storeObjectTree(self, scipionObj):
        ownerProtocol = self._findOwnerProtocol(scipionObj)
        protocolDbId = self._resolveProtocolDbIdFromObject(ownerProtocol)
        outputName = self._getObjectName(scipionObj) or self._getClassName(scipionObj)

        if self._shouldSkipRuntimeObjectTree(outputName, scipionObj):
            logger.debug(
                "Skipping internal runtime object persistence. projectId=%s outputName=%s class=%s",
                self.projectId,
                outputName,
                self._getClassName(scipionObj),
            )
            return

        if protocolDbId is None or not outputName:
            logger.debug(
                "Skipping runtime object persistence without owner/outputName: %s",
                scipionObj,
            )
            return

        self.objectMapper.storeObjectTree(
            projectId=self.projectId,
            protocolDbId=protocolDbId,
            outputName=outputName,
            scipionObj=scipionObj,
        )

    def _shouldSkipRuntimeObjectTree(
            self,
            outputName,
            scipionObj,
    ) -> bool:
        """
        Skip internal protocol runtime fields that are not real outputs.
        """
        name = str(
            outputName or ""
        ).strip()

        return (
                name
                in self.INTERNAL_PROTOCOL_OBJECT_NAMES
        )

    # ---------------------------------------------------------------------
    # Serialization helpers
    # ---------------------------------------------------------------------

    def _buildProtocolContext(self, protocol: Protocol) -> Dict[str, Any]:
        protocolId = self._requireObjId(protocol)

        values = {}

        try:
            values = protocol.getDefinitionDict()
        except Exception:
            logger.debug(
                "Could not get protocol definition dict for %s",
                protocol,
                exc_info=True,
            )

        try:
            values = dict(values or {})
        except Exception:
            values = {}

        runtimeStatusSyncService = (
            RuntimeProtocolStatusSyncService()
        )

        values[runtimeStatusSyncService.RUNTIME_METADATA_KEY] = runtimeStatusSyncService.buildRuntimeMetadata(protocol)

        return {
            "info": {
                "projectId": self.projectId,
                "protocolId": str(protocolId),
                "protocolClassName": self._getClassName(protocol),
                "status": self._call(protocol, "getStatus", "pending"),
            },
            "values": values,
            "parentIds": self._safeIntList(self._call(protocol, "getPrerequisites", [])),
            "childIds": [],
        }

    def _buildProtocolSteps(self, protocol: Protocol) -> List[Dict[str, Any]]:
        steps = []

        try:
            rawSteps = list(protocol.loadSteps() or [])
        except Exception:
            rawSteps = list(getattr(protocol, "_steps", []) or [])

        for step in rawSteps:
            stepIndex = self._call(step, "getIndex", None)
            if stepIndex is None:
                continue

            elapsedSeconds = None
            elapsed = self._call(step, "getElapsedTime", None)
            try:
                if elapsed is not None:
                    elapsedSeconds = elapsed.total_seconds()
            except Exception:
                elapsedSeconds = None

            funcName = self._scalarValue(getattr(step, "funcName", None))
            if not funcName:
                funcName = self._getClassName(step)

            prerequisites = self._call(step, "getPrerequisites", [])
            try:
                prerequisites = [int(x) for x in (prerequisites or [])]
            except Exception:
                prerequisites = []

            args = self._scalarValue(getattr(step, "argsStr", None))
            try:
                import json
                args = json.loads(args) if args else None
            except Exception:
                args = str(args) if args else None

            steps.append({
                "index": int(stepIndex),
                "name": str(funcName or ""),
                "status": self._call(step, "getStatus", ""),
                "prerequisites": prerequisites,
                "args": args,
                "initTime": self._scalarValue(getattr(step, "initTime", None)),
                "endTime": self._scalarValue(getattr(step, "endTime", None)),
                "elapsedSeconds": elapsedSeconds,
                "error": self._call(step, "getErrorMessage", None),
                "interactive": bool(self._call(step, "isInteractive", False)),
                "needsGpu": bool(self._call(step, "needsGPU", True)),
                "event": "runtime_mapper",
            })

        return steps

    # ---------------------------------------------------------------------
    # Small utilities
    # ---------------------------------------------------------------------

    def _assignFreshRuntimeObjectId(
            self,
            obj,
    ) -> int:
        allocator = getattr(
            self.flatMapper,
            "allocateProjectObjectId",
            None,
        )

        if not callable(allocator):
            raise RuntimeError(
                "PostgresqlFlatMapper does not provide allocateProjectObjectId."
            )

        objId = int(allocator(self.projectId))
        self._setObjId(obj, objId)

        return objId

    def _ensureObjId(
            self,
            obj,
    ) -> Optional[int]:
        """
        Ensure that a runtime object has an id.

        Protocols and non-protocol runtime objects use independent
        PostgreSQL id namespaces.
        """
        if obj is None:
            return None

        objId = self._getObjId(
            obj
        )

        if objId is not None:
            return int(objId)

        isProtocol = isinstance(
            obj,
            Protocol,
        )

        if isProtocol:
            allocatorName = (
                "allocateProjectProtocolId"
            )
        else:
            allocatorName = (
                "allocateProjectObjectId"
            )

        allocator = getattr(
            self.flatMapper,
            allocatorName,
            None,
        )

        if not callable(
                allocator
        ):
            raise RuntimeError(
                "PostgresqlFlatMapper does not provide %s."
                % allocatorName
            )

        objId = int(
            allocator(
                self.projectId
            )
        )

        try:
            self._setObjId(
                obj,
                objId,
            )
        except Exception as exc:
            raise RuntimeError(
                "Could not assign _objId=%s to %s."
                % (
                    objId,
                    obj,
                )
            ) from exc

        return objId

    def _getNamePrefix(self, obj) -> str:
        objName = str(getattr(obj, "_objName", "") or "")

        try:
            objId = obj.strId()
        except Exception:
            objId = str(self._requireObjId(obj))

        if objName and "." in objName:
            return replaceExt(objName, objId)

        return objId

    def _attachProtocolHostConfig(
            self,
            protocol,
    ) -> bool:
        """
        Restore the non-persistent Scipion HostConfig for a
        PostgreSQL-hydrated protocol.

        HostConfig is loaded from the current project configuration
        using the persisted protocol hostName. It is deliberately
        never stored in PostgreSQL.
        """
        if (
                protocol is None
                or self.project is None
        ):
            return False

        try:
            existingHostConfig = (
                protocol.getHostConfig()
            )

        except (
                AttributeError,
                TypeError,
        ):
            existingHostConfig = None

        except Exception:
            existingHostConfig = None

        if existingHostConfig is not None:
            return True

        try:
            hostName = (
                protocol.getHostName()
            )

        except Exception:
            hostName = None

        hostName = str(
            hostName or ""
        ).strip()

        if not hostName:
            logger.warning(
                "Cannot attach HostConfig to PostgreSQL "
                "protocol without hostName. "
                "projectId=%s protocolId=%s",
                self.projectId,
                self._getObjId(
                    protocol
                ),
            )

            return False

        getHostConfig = getattr(
            self.project,
            "getHostConfig",
            None,
        )

        if not callable(
                getHostConfig
        ):
            logger.warning(
                "Current PostgreSQL project does not expose "
                "getHostConfig(). projectId=%s protocolId=%s "
                "hostName=%s",
                self.projectId,
                self._getObjId(
                    protocol
                ),
                hostName,
            )

            return False

        try:
            hostConfig = getHostConfig(
                hostName
            )

        except Exception:
            logger.exception(
                "Could not resolve PostgreSQL protocol "
                "HostConfig. projectId=%s protocolId=%s "
                "hostName=%s",
                self.projectId,
                self._getObjId(
                    protocol
                ),
                hostName,
            )

            return False

        if hostConfig is None:
            logger.warning(
                "HostConfig was not found for PostgreSQL "
                "protocol. projectId=%s protocolId=%s "
                "hostName=%s",
                self.projectId,
                self._getObjId(
                    protocol
                ),
                hostName,
            )

            return False

        try:
            protocol.setHostConfig(
                hostConfig
            )

        except Exception:
            logger.exception(
                "Could not attach HostConfig to PostgreSQL "
                "protocol. projectId=%s protocolId=%s "
                "hostName=%s",
                self.projectId,
                self._getObjId(
                    protocol
                ),
                hostName,
            )

            return False

        return True

    def _attachRuntimeContext(
            self,
            obj,
    ):
        if obj is None:
            return obj

        if isinstance(
                obj,
                Protocol,
        ):
            obj.setMapper(
                self
            )

            if self.project is not None:
                try:
                    obj.setProject(
                        self.project
                    )

                except Exception:
                    logger.debug(
                        "Could not attach PostgreSQL project "
                        "to runtime protocol. projectId=%s "
                        "protocolId=%s",
                        self.projectId,
                        self._getObjId(
                            obj
                        ),
                        exc_info=True,
                    )

            self._attachProtocolHostConfig(
                obj
            )

        return obj

    def _attachRuntimeContextList(self, values):
        return [self._attachRuntimeContext(value) for value in (values or [])]

    def _attachRuntimeContextIterator(self, values):
        for value in values or []:
            yield self._attachRuntimeContext(value)

    def _getObjId(self, obj) -> Optional[int]:
        if obj is None:
            return None

        getter = getattr(obj, "getObjId", None)
        if callable(getter):
            try:
                value = getter()
                if value is not None:
                    return int(value)
            except Exception:
                pass

        value = getattr(obj, "_objId", None)
        if value is None:
            return None

        try:
            return int(value)
        except Exception:
            return None

    def _requireObjId(self, obj) -> int:
        objId = self._getObjId(obj)
        if objId is None:
            raise ValueError("Object does not have an id: %s" % obj)
        return int(objId)

    def _getClassName(self, obj) -> str:
        getter = getattr(obj, "getClassName", None)
        if callable(getter):
            try:
                value = getter()
                if value:
                    return str(value)
            except Exception:
                pass
        return obj.__class__.__name__ if obj is not None else "Unknown"

    def _getObjectName(self, obj) -> Optional[str]:
        for attrName in ("_objName",):
            value = getattr(obj, attrName, None)
            if value:
                return str(value).split(".")[-1]

        getter = getattr(obj, "getName", None)
        if callable(getter):
            try:
                value = getter()
                return str(value) if value else None
            except Exception:
                return None

        return None

    def _call(self, obj, methodName: str, default=None):
        method = getattr(obj, methodName, None)
        if not callable(method):
            return default

        try:
            value = method()
            return value if value is not None else default
        except Exception:
            return default

    def _scalarValue(self, value):
        if value is None:
            return None

        try:
            if hasattr(value, "hasValue") and not value.hasValue():
                return None
        except Exception:
            pass

        getter = getattr(value, "get", None)
        if callable(getter):
            try:
                return getter()
            except TypeError:
                try:
                    return getter(None)
                except Exception:
                    return None
            except Exception:
                return None

        return value

    def _safeIntList(self, values) -> List[int]:
        result = []
        for value in values or []:
            try:
                result.append(int(value))
            except Exception:
                continue
        return result

    def _isSetLike(self, obj) -> bool:
        className = self._getClassName(obj)
        return str(className or "").startswith("SetOf")

    def _findOwnerProtocol(self, obj):
        parentId = getattr(obj, "_objParentId", None)
        if parentId is None:
            return None

        try:
            parent = self.selectById(int(parentId))
            if isinstance(parent, Protocol):
                return parent
        except Exception:
            return None

        return None

    def _resolveProtocolDbIdFromObject(self, protocol) -> Optional[int]:
        protocolId = self._getObjId(protocol)
        if protocolId is None:
            return None

        row = self.db.fetchOne(
            """
            SELECT id
              FROM protocols
             WHERE "projectId" = %s
               AND "protocolId" = %s
             LIMIT 1
            """,
            (self.projectId, str(protocolId)),
        )
        if not row:
            return None

        return int(row["id"])

    def _normalizeRelationExtended(self, value) -> str:
        if value is None:
            return ""
        return str(value)

    def _setObjId(self, obj, objId: int) -> None:
        setter = getattr(obj, "setObjId", None)
        if callable(setter):
            setter(int(objId))
            return

        obj._objId = int(objId)

    def _setObjName(self, obj, name: str) -> None:
        setter = getattr(obj, "setObjName", None)
        if callable(setter):
            setter(str(name))
            return

        obj._objName = str(name)

    def _setObjParentId(self, obj, parentId: int) -> None:
        setter = getattr(obj, "setObjParentId", None)
        if callable(setter):
            setter(int(parentId))
            return

        obj._objParentId = int(parentId)

    def _resolveProtocolClass(self, protocolClassName: str):
        domain = None

        if self.project is not None:
            try:
                domain = self.project.getDomain()
            except Exception:
                domain = None

        if domain is None:
            try:
                from pyworkflow.config import Config
                domain = Config.getDomain()
            except Exception:
                domain = None

        if domain is None:
            return None

        protocols = domain.getProtocols() or {}

        if protocolClassName in protocols:
            return protocols[protocolClassName]

        for name, protocolClass in protocols.items():
            if str(name).lower() == protocolClassName.lower():
                return protocolClass

        return None

    def _toOptionalInt(self, value):
        if value in (None, ""):
            return None

        try:
            return int(value)
        except Exception:
            return None

    def _instantiateProtocol(self, protocolClass):
        if self.project is not None:
            newProtocol = getattr(self.project, "newProtocol", None)
            if callable(newProtocol):
                protocol = newProtocol(protocolClass)
                protocol.setMapper(self)
                protocol.setProject(self.project)
                return protocol

        protocol = protocolClass()
        self._attachRuntimeContext(protocol)
        return protocol

    def _toOptionalInt(self, value) -> Optional[int]:
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

    def _applyStoredProtocolStatus(self, protocol: Protocol, statusValue):
        if statusValue in (None, ""):
            return

        statusText = str(statusValue)

        setter = getattr(protocol, "setStatus", None)
        if callable(setter):
            try:
                setter(statusText)
                return
            except Exception:
                logger.debug(
                    "Could not restore protocol status using setStatus. status=%s",
                    statusText,
                    exc_info=True,
                )

        statusAttr = getattr(protocol, "status", None)
        setMethod = getattr(statusAttr, "set", None)
        if callable(setMethod):
            try:
                setMethod(statusText)
                return
            except Exception:
                logger.debug(
                    "Could not restore protocol status using status.set(). status=%s",
                    statusText,
                    exc_info=True,
                )

    def _applyStoredProtocolRuntimeMetadata(
            self,
            protocol,
            rawParams,
    ) -> None:
        params = (
            self._normalizeStoredProtocolParams(
                rawParams
            )
        )

        runtimeMetadata = params.get(
            RuntimeProtocolStatusSyncService
            .RUNTIME_METADATA_KEY
        )

        if not isinstance(
                runtimeMetadata,
                dict,
        ):
            return

        if "pid" in runtimeMetadata:
            storedPid = (
                self._toOptionalInt(
                    runtimeMetadata.get(
                        "pid"
                    )
                )
                or 0
            )

            setPid = getattr(
                protocol,
                "setPid",
                None,
            )

            if callable(setPid):
                setPid(
                    storedPid
                )

            else:
                pidAttribute = getattr(
                    protocol,
                    "_pid",
                    None,
                )

                pidSetter = getattr(
                    pidAttribute,
                    "set",
                    None,
                )

                if callable(pidSetter):
                    pidSetter(
                        storedPid
                    )

        if "jobIds" not in runtimeMetadata:
            return

        rawJobIds = runtimeMetadata.get(
            "jobIds"
        )

        if rawJobIds is None:
            rawValues = []

        elif isinstance(
                rawJobIds,
                str,
        ):
            rawValues = (
                rawJobIds
                .replace(";", ",")
                .split(",")
            )

        else:
            try:
                rawValues = list(
                    rawJobIds
                )

            except TypeError:
                rawValues = [
                    rawJobIds,
                ]

        jobIds = []
        seen = set()

        for rawValue in rawValues:
            jobId = str(
                rawValue or ""
            ).strip()

            if (
                    not jobId
                    or jobId == "0"
                    or jobId in seen
            ):
                continue

            seen.add(
                jobId
            )

            jobIds.append(
                jobId
            )

        jobIdAttribute = getattr(
            protocol,
            "_jobId",
            None,
        )

        clearJobIds = getattr(
            jobIdAttribute,
            "clear",
            None,
        )

        if callable(clearJobIds):
            clearJobIds()

        appendJobId = getattr(
            protocol,
            "appendJobId",
            None,
        )

        if callable(appendJobId):
            for jobId in jobIds:
                appendJobId(
                    jobId
                )

            return

        appendToAttribute = getattr(
            jobIdAttribute,
            "append",
            None,
        )

        if callable(appendToAttribute):
            for jobId in jobIds:
                appendToAttribute(
                    jobId
                )

    def _applyStoredProtocolParams(
            self,
            protocol,
            rawParams,
    ):
        params = (
            self._normalizeStoredProtocolParams(
                rawParams
            )
        )

        self._applyStoredProtocolRuntimeMetadata(
            protocol,
            params,
        )

        runtimeMetadataKey = (
            RuntimeProtocolStatusSyncService
            .RUNTIME_METADATA_KEY
        )

        for key, storedValue in params.items():
            if key == runtimeMetadataKey:
                continue
            value = (
                self
                ._extractStoredProtocolParamValue(
                    storedValue
                )
            )

            if value is None:
                continue

            try:
                param = protocol.getParam(
                    key
                )
            except Exception:
                param = None

            # Pointer state is authoritative in protocol_input_refs.
            # Raw textual values from protocols.params must never be
            # assigned to Pointer or PointerList runtime attributes.
            if isinstance(
                    param,
                    (
                            PointerParam,
                            MultiPointerParam,
                            RelationParam,
                    ),
            ):
                continue

            # Param is the form definition. Never mutate it with
            # param.set(value). Only update the runtime attribute.
            if param is not None:
                try:
                    protocol.setAttributeValue(
                        key,
                        value,
                    )
                except Exception:
                    logger.debug(
                        "Could not restore PostgreSQL protocol "
                        "attribute value. key=%s value=%s",
                        key,
                        value,
                        exc_info=True,
                    )

                continue

            attr = getattr(
                protocol,
                key,
                None,
            )

            attrSetter = getattr(
                attr,
                "set",
                None,
            )

            if callable(attrSetter):
                try:
                    attrSetter(
                        value
                    )
                    continue
                except Exception:
                    logger.debug(
                        "Could not restore PostgreSQL protocol "
                        "runtime attribute. key=%s value=%s",
                        key,
                        value,
                        exc_info=True,
                    )

            try:
                setattr(
                    protocol,
                    key,
                    value,
                )
            except Exception:
                logger.debug(
                    "Could not assign PostgreSQL protocol "
                    "runtime value. key=%s value=%s",
                    key,
                    value,
                    exc_info=True,
                )

    def _normalizeStoredProtocolParams(self, rawParams):
        if rawParams is None:
            return {}

        if isinstance(rawParams, str):
            try:
                import json
                rawParams = json.loads(rawParams)
            except Exception:
                return {}

        return rawParams if isinstance(rawParams, dict) else {}

    def _extractStoredProtocolParamValue(self, storedValue):
        if isinstance(storedValue, dict):
            for key in ("editableValue", "value", "objValue", "_value", "default"):
                if key in storedValue:
                    return storedValue.get(key)
            return None

        return storedValue

    def _applyStoredProtocolParam(
            self,
            protocol: Protocol,
            key: str,
            value,
    ):
        try:
            param = protocol.getParam(
                key
            )
        except Exception:
            param = None

        if isinstance(
                param,
                (
                        PointerParam,
                        MultiPointerParam,
                        RelationParam,
                ),
        ):
            return

        if param is not None:
            try:
                protocol.setAttributeValue(
                    key,
                    value,
                )
            except Exception:
                logger.debug(
                    "Could not restore protocol attribute "
                    "value. param=%s value=%s",
                    key,
                    value,
                    exc_info=True,
                )

            return

        attr = getattr(
            protocol,
            key,
            None,
        )

        attrSetter = getattr(
            attr,
            "set",
            None,
        )

        if callable(attrSetter):
            try:
                attrSetter(
                    value
                )
                return
            except Exception:
                logger.debug(
                    "Could not restore protocol attr. "
                    "attr=%s value=%s",
                    key,
                    value,
                    exc_info=True,
                )

        try:
            setattr(
                protocol,
                key,
                value,
            )
        except Exception:
            logger.debug(
                "Could not setattr protocol param. "
                "attr=%s value=%s",
                key,
                value,
                exc_info=True,
            )

    def _ensureProtocolWorkingDir(self, protocol):
        if self.project is None:
            return

        try:
            workingDirName = self.project.getProtWorkingDir(protocol)
            workingDir = self.project.getPath("Runs", workingDirName)
            protocol.setWorkingDir(workingDir)
        except Exception:
            logger.debug(
                "Could not restore PostgreSQL protocol workingDir. projectId=%s protocolId=%s",
                self.projectId,
                getattr(protocol, "getObjId", lambda: None)(),
                exc_info=True,
            )

    def _shouldSkipInternalRuntimeObject(self, obj) -> bool:
        if obj is None:
            return False

        candidateNames = []

        for attrName in ("_objName", "_objLabel"):
            value = getattr(obj, attrName, None)

            try:
                value = value.get() if hasattr(value, "get") else value
            except Exception:
                pass

            if value not in (None, ""):
                candidateNames.append(str(value))

        try:
            candidateNames.append(str(obj.getName()))
        except Exception:
            pass

        for rawName in candidateNames:
            name = str(rawName or "").strip()
            if not name:
                continue

            if name in self.INTERNAL_PROTOCOL_OBJECT_NAMES:
                return True

            shortName = name.split(".")[-1]
            if shortName in self.INTERNAL_PROTOCOL_OBJECT_NAMES:
                return True

        return False
