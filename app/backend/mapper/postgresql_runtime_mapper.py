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
import inspect
import json
import logging
import os
from collections import Counter
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from pyworkflow.mapper.mapper import Mapper
from pyworkflow.project.project import (
    PROJECT_CREATION_TIME,
    PROJECT_RUNS,
)
from pyworkflow.protocol.protocol import Protocol
from pyworkflow.object import (
    Object as ScipionObject,
    Set as ScipionSet,
    String,
)
from pyworkflow.utils import joinExt, replaceExt
from pyworkflow.config import Config

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

logger = logging.getLogger(__name__)


class PostgresqlRuntimeMapper(Mapper):
    """
    Mapper compatible with pyworkflow.mapper.Mapper, backed by PostgreSQL.

    This is the first runtime bridge. It is intentionally conservative:
    - Protocol writes go to the existing protocols table.
    - Step snapshots can go to protocol_steps.
    - Scipion object trees go to scipion_objects.
    - SetOf... objects go to scipion_sets/scipion_set_items.
    - Reads can still fallback to a legacy mapper while the full PostgreSQL
      object reconstruction is implemented.

    The goal is to make Project.mapper and Protocol.mapper replaceable without
    touching scipion-pyworkflow.
    """

    def __init__(
            self,
            flatMapper: PostgresqlFlatMapper,
            projectId: int,
            dictClasses=None,
            readFallbackMapper=None,
            writeFallbackMapper=None,
            project=None,
    ):
        super().__init__(dictClasses=dictClasses)

        self.flatMapper = flatMapper
        self.db = flatMapper.db
        self.projectId = int(projectId)
        self.project = project

        # Temporary bridges while we migrate reads/runtime fully.
        self.readFallbackMapper = readFallbackMapper
        self.writeFallbackMapper = writeFallbackMapper

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
        self.runtimeSetFactory = (
            PostgresqlRuntimeSetFactory()
        )
        self._runtimeProtocolsById = {}
        self._sqliteProtocolMirrorIds = set()
        self._initializeFallbackAudit()

    FALLBACK_AUDIT_ENV = (
        "SCIPION_POSTGRESQL_FALLBACK_AUDIT"
    )

    FALLBACK_AUDIT_TRUE_VALUES = {
        "1",
        "true",
        "yes",
        "on",
    }

    def _initializeFallbackAudit(self):
        auditValue = os.environ.get(
            self.FALLBACK_AUDIT_ENV,
            "",
        )

        self._fallbackAuditEnabled = (
                str(auditValue).strip().lower()
                in self.FALLBACK_AUDIT_TRUE_VALUES
        )

        self._fallbackAuditCounts = Counter()
        self._fallbackAuditContexts = {}

    def _recordReadFallback(
            self,
            operation,
            **context,
    ):
        if not getattr(
                self,
                "_fallbackAuditEnabled",
                False,
        ):
            return

        caller = self._findFallbackAuditCaller()

        key = (
            str(operation),
            caller,
        )

        self._fallbackAuditCounts[key] += 1

        if key not in self._fallbackAuditContexts:
            self._fallbackAuditContexts[key] = {
                str(name): self._normalizeFallbackAuditValue(value)
                for name, value in context.items()
            }

        if self._fallbackAuditCounts[key] == 1:
            logger.warning(
                "POSTGRESQL_RUNTIME_FALLBACK firstUse %s",
                json.dumps(
                    {
                        "projectId": self.projectId,
                        "operation": str(operation),
                        "caller": caller,
                        "context": self._fallbackAuditContexts[key],
                    },
                    sort_keys=True,
                ),
            )

    def getFallbackAuditReport(self):
        counts = getattr(
            self,
            "_fallbackAuditCounts",
            {},
        )

        contexts = getattr(
            self,
            "_fallbackAuditContexts",
            {},
        )

        items = []

        for (
                operation,
                caller,
        ), count in sorted(
            counts.items(),
            key=lambda item: (
                    item[0][0],
                    item[0][1],
            ),
        ):
            items.append({
                "operation": operation,
                "caller": caller,
                "count": int(count),
                "context": contexts.get(
                    (
                        operation,
                        caller,
                    ),
                    {},
                ),
            })

        return {
            "projectId": getattr(
                self,
                "projectId",
                None,
            ),
            "totalCalls": sum(
                int(count)
                for count in counts.values()
            ),
            "items": items,
        }

    def _logFallbackAuditSummary(self):
        if not getattr(
                self,
                "_fallbackAuditEnabled",
                False,
        ):
            return

        report = self.getFallbackAuditReport()

        if report["totalCalls"] == 0:
            return

        logger.warning(
            "POSTGRESQL_RUNTIME_FALLBACK summary %s",
            json.dumps(
                report,
                sort_keys=True,
            ),
        )

        self._fallbackAuditCounts.clear()
        self._fallbackAuditContexts.clear()

    @staticmethod
    def _findFallbackAuditCaller():
        frame = inspect.currentframe()

        try:
            frame = frame.f_back

            while frame is not None:
                moduleName = str(
                    frame.f_globals.get(
                        "__name__",
                        "",
                    )
                )

                if moduleName != __name__:
                    return "%s.%s" % (
                        moduleName,
                        frame.f_code.co_name,
                    )

                frame = frame.f_back

        finally:
            del frame

        return "unknown"

    @classmethod
    def _normalizeFallbackAuditValue(
            cls,
            value,
    ):
        if value is None or isinstance(
                value,
                (
                        str,
                        int,
                        float,
                        bool,
                ),
        ):
            return value

        if isinstance(value, type):
            return value.__name__

        if callable(value):
            return getattr(
                value,
                "__qualname__",
                str(value),
            )

        if isinstance(value, dict):
            return {
                str(key): cls._normalizeFallbackAuditValue(
                    itemValue
                )
                for key, itemValue in value.items()
            }

        if isinstance(
                value,
                (
                        list,
                        tuple,
                        set,
                ),
        ):
            return [
                cls._normalizeFallbackAuditValue(item)
                for item in value
            ]

        return str(value)
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

        if self.writeFallbackMapper is not None:
            self.writeFallbackMapper.commit()

    def close(self):
        self._logFallbackAuditSummary()

        # Do not close the shared PostgreSQL connection here. It belongs to the
        # request/session mapper lifecycle.
        if self.readFallbackMapper is not None:
            try:
                self.readFallbackMapper.close()
            except Exception:
                logger.debug(
                    "Could not close read fallback mapper.",
                    exc_info=True,
                )

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
        self._sqliteProtocolMirrorIds.clear()

    # ---------------------------------------------------------------------
    # Generic Mapper API
    # ---------------------------------------------------------------------

    def _storeProtocolInWriteFallback(self, protocol: Protocol) -> None:
        """
        Store a protocol root in the SQLite write fallback without creating orphan
        children.

        In PostgreSQL runtime mode, _ensureObjId() assigns the protocol id before the
        SQLite fallback sees the object. SqliteMapper.store() interprets "has objId"
        as "already exists" and calls updateTo(), which can insert children like
        175.status,  and calls updateTo(), which can insert children like
        175.status, 175.inputSet, etc. without inserting the root object 175.

        For protocols, check whether the root exists in the fallback mapper. If it
        does not exist, force insert().
        """
        protocolId = self._getObjId(protocol)

        if protocolId is None:
            raise RuntimeError("Cannot insert SQLite fallback root without protocol id")

        protocolId = int(protocolId)

        db = getattr(self.writeFallbackMapper, "db", None)

        if db is None:
            raise RuntimeError("SQLite fallback mapper does not expose db")

        objName = None

        try:
            objName = protocol.getObjName()
        except Exception:
            objName = None

        if not objName:
            try:
                objName = protocol.strId()
            except Exception:
                objName = str(protocolId)

        className = self._getClassName(protocol)

        label = None
        comment = None
        creation = None

        try:
            label = protocol.getObjLabel()
        except Exception:
            label = None

        try:
            comment = protocol.getObjComment()
        except Exception:
            comment = None

        try:
            creation = protocol.getObjCreation()
        except Exception:
            creation = None

        insertObject = getattr(db, "insertObject", None)

        if not callable(insertObject):
            raise RuntimeError(
                "SQLite fallback db does not expose insertObject; "
                "cannot safely insert protocol root preserving id %s"
                % protocolId
            )

        logger.info(
            "Inserting missing protocol root in SQLite fallback preserving id. "
            "projectId=%s protocolId=%s className=%s",
            self.projectId,
            protocolId,
            className,
        )

        # Different Scipion/pyworkflow versions expose different insertObject
        # signatures. Use only the positional arguments accepted by the bound method.
        # In your current version it expects 6 args, not 8.
        try:
            import inspect

            parameters = [
                p
                for p in inspect.signature(insertObject).parameters.values()
                if p.kind in (
                    p.POSITIONAL_ONLY,
                    p.POSITIONAL_OR_KEYWORD,
                )
            ]

            argCount = len(parameters)

        except Exception:
            # Current pyworkflow version from the traceback:
            # insertObject() takes 7 positional arguments including self,
            # so the bound method accepts 6 arguments.
            argCount = 6

        baseArgs = [
            protocolId,
            None,  # parentId
            objName,
            className,
            None,  # value
            label,
            comment,
            creation,
        ]

        insertObject(*baseArgs[:argCount])

    def store(self, obj):
        if obj is None:
            return

        if isinstance(obj, Protocol):
            self._storeRuntimeProtocol(obj)
            return

        self._ensureObjId(obj)

        if self.writeFallbackMapper is not None:
            self.writeFallbackMapper.store(obj)

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
        """
        Store a protocol in PostgreSQL runtime mode while keeping the SQLite
        execution mirror usable.

        Important:
          - New protocols must let SQLite assign the Scipion objId first.
            The classic runner still loads protocols from SQLite.
          - PostgreSQL then stores that same objId as protocols."protocolId".
          - Existing PostgreSQL protocols are mirrored to SQLite only if the root
            already exists there. We do not manually fabricate SQLite rows.
        """
        protocolId = self._getObjId(protocol)

        if self.writeFallbackMapper is not None:
            if protocolId is None:
                # New protocol:
                # Let SQLite do the normal Scipion insert and assign objId.
                # Do NOT call _ensureObjId before this.
                self.writeFallbackMapper.store(protocol)
                protocolId = self._getObjId(protocol)

                logger.info(
                    "SQLite fallback assigned protocol id for new runtime protocol. "
                    "projectId=%s protocolId=%s class=%s",
                    self.projectId,
                    protocolId,
                    self._getClassName(protocol),
                )

            elif self._existsInWriteFallback(protocolId):
                # Existing protocol already mirrored in SQLite.
                # Safe to update it there.
                objIdBeforeStore = self._getObjId(protocol)

                self.writeFallbackMapper.store(protocol)

                objIdAfterStore = self._getObjId(protocol)

                if str(objIdAfterStore) != str(objIdBeforeStore):
                    try:
                        self._setObjId(protocol, int(objIdBeforeStore))
                    except Exception:
                        pass

                    raise RuntimeError(
                        "SQLite fallback changed protocol id from %s to %s. "
                        "This would create a duplicated protocol node."
                        % (objIdBeforeStore, objIdAfterStore)
                    )

            else:
                # Existing PG protocol not present in SQLite.
                # Do not call SQLite store(), because it would update children and
                # create orphan rows like 175.status without root 175.
                logger.warning(
                    "Skipping SQLite fallback protocol update because root is missing. "
                    "projectId=%s protocolId=%s class=%s",
                    self.projectId,
                    protocolId,
                    self._getClassName(protocol),
                )

        self._ensureObjId(protocol)
        self._storeProtocol(protocol)

    def _existsInWriteFallback(self, objId) -> bool:
        if self.writeFallbackMapper is None or objId is None:
            return False

        try:
            return bool(self.writeFallbackMapper.exists(objId))
        except Exception:
            pass

        try:
            return self.writeFallbackMapper.selectById(objId) is not None
        except Exception:
            return False

    def insert(self, obj):
        if obj is None:
            return

        if isinstance(obj, Protocol):
            # Do not pre-allocate PostgreSQL ids for new protocols here.
            # SQLite fallback must assign the execution id first.
            self._storeRuntimeProtocol(obj)
            return

        self._ensureObjId(obj)
        self.store(obj)

    def insertChild(self, obj, key, attr, namePrefix=None):
        """
        Insert/store a child object following the naming convention used by
        SqliteMapper.

        For Protocol parents, mirror children into SQLite only when the protocol root
        already exists in SQLite. Otherwise SQLite creates orphan rows.
        """
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

        shouldWriteFallback = self.writeFallbackMapper is not None

        if isinstance(obj, Protocol):
            shouldWriteFallback = shouldWriteFallback and self._existsInWriteFallback(
                self._getObjId(obj)
            )

        if shouldWriteFallback:
            self.writeFallbackMapper.insertChild(
                obj,
                key,
                attr,
                namePrefix=namePrefix,
            )

        self.store(attr)

    def updateTo(self, obj):
        self.store(obj)

    def updateFrom(self, obj):
        if self.readFallbackMapper is None:
            raise NotImplementedError(
                "PostgreSQL updateFrom is not implemented yet. "
                "Use readFallbackMapper during the migration phase."
            )
        self._recordReadFallback(
            "updateFrom",
            objectId=self._getObjId(obj),
            objectClass=self._getClassName(obj),
        )

        return self.readFallbackMapper.updateFrom(obj)

    def selectById(
            self,
            objId,
    ):
        obj = self._selectProtocolByIdFromPostgresql(
            objId
        )

        if obj is not None:
            return self._attachRuntimeContext(
                obj
            )

        obj = self._selectSetByIdFromPostgresql(
            objId
        )

        if obj is not None:
            return obj

        obj = self._selectByIdFromReadFallback(
            objId
        )

        if obj is not None:
            return self._attachRuntimeContext(
                obj
            )

        return None

    def selectRuntimeProtocolById(self, objId):
        """
        Return one stable, fully hydrated protocol for runtime operations.

        Prefer the SQLite compatibility object on the first read because it
        contains native pointers, internal attributes and outputs. Cache that
        instance so all subsequent runtime reads reuse the same protocol identity.
        """
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
                return self._getOrBuildProtocolFromPostgresqlRow(row)

            if protocolId in self._sqliteProtocolMirrorIds:
                return self._attachRuntimeContext(cachedProtocol)

            # A PostgreSQL-native cached protocol whose row disappeared must
            # not remain available as a stale runtime object.
            self._runtimeProtocolsById.pop(protocolId, None)

        protocol = self._selectByIdFromReadFallback(
            protocolId,
            auditOperation=(
                "selectRuntimeProtocolById."
                "compatibilityMirror"
            ),
        )

        if isinstance(protocol, Protocol):
            if row:
                return self._adoptSqliteProtocolMirror(protocol, row)

            protocol = self._attachRuntimeContext(protocol)

            # Preserve identity for compatibility-only protocols too. If the
            # PostgreSQL row appears later, it will receive the safe mirror refresh.
            self._runtimeProtocolsById[protocolId] = protocol
            self._sqliteProtocolMirrorIds.add(protocolId)

            return protocol

        if row:
            return self._getOrBuildProtocolFromPostgresqlRow(row)

        return None

    def _selectByIdFromReadFallback(
            self,
            objId,
            auditOperation="selectById",
    ):
        if self.readFallbackMapper is None:
            return None

        try:
            obj = self.readFallbackMapper.selectById(objId)
        except Exception:
            logger.debug(
                "Object %s was not found in read fallback mapper. Trying PostgreSQL.",
                objId,
                exc_info=True,
            )
            return None

        if obj is None:
            logger.debug(
                "Object %s was not found in read fallback mapper. Trying PostgreSQL.",
                objId,
            )
            return None

        self._recordReadFallback(
            auditOperation,
            objectId=objId,
        )
        return obj

    def _selectProtocolByIdFromPostgresql(self, objId):
        protocolId = self._toOptionalInt(objId)

        if protocolId is None:
            logger.warning(
                "Cannot select PostgreSQL protocol: objId is not an int. objId=%s",
                objId,
            )
            return None

        logger.debug(
            "Looking for PostgreSQL protocol row. projectId=%s protocolId=%s",
            self.projectId,
            protocolId,
        )

        row = self.flatMapper.getProjectProtocolByProtocolId(
            self.projectId,
            protocolId,
        )

        if not row:
            return None

        return self._getOrBuildProtocolFromPostgresqlRow(row)

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

        if protocolId in self._sqliteProtocolMirrorIds:
            return self._refreshSqliteProtocolMirrorFromPostgresqlRow(
                protocol,
                row,
            )

        return self._refreshProtocolFromPostgresqlRow(protocol, row)

    def _refreshSqliteProtocolMirrorFromPostgresqlRow(self, protocol, row):
        """
        Refresh PostgreSQL-owned runtime metadata without replacing the
        complete protocol state already hydrated from SQLite.

        Stored protocol params are deliberately not reapplied because the
        SQLite protocol already contains native Pointer, PointerList and
        output attributes.
        """
        protocolId = self._toOptionalInt(row.get("protocolId"))

        if protocolId is not None:
            self._setObjId(protocol, protocolId)

        self._attachRuntimeContext(protocol)
        self._applyStoredProtocolStatus(protocol, row.get("status"))
        self._ensureProtocolWorkingDir(protocol)

        return protocol

    def _adoptSqliteProtocolMirror(self, protocol, row):
        protocolId = self._toOptionalInt(row.get("protocolId"))

        if protocolId is None:
            logger.warning(
                "Cannot adopt SQLite protocol mirror without protocolId. row=%s",
                row,
            )
            return None

        protocol = self._refreshSqliteProtocolMirrorFromPostgresqlRow(
            protocol,
            row,
        )

        self._runtimeProtocolsById[protocolId] = protocol
        self._sqliteProtocolMirrorIds.add(protocolId)

        return protocol

    def _selectSetByIdFromPostgresql(
            self,
            objId,
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
                protocolId
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

    def exists(
            self,
            objId,
    ):
        runtimeObjectId = self._toOptionalInt(
            objId
        )

        if runtimeObjectId is not None:
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

            cachedSet = (
                self.runtimeSetFactory
                ._getCachedRuntimeSet(
                    projectId=self.projectId,
                    runtimeObjectId=(
                        runtimeObjectId
                    ),
                )
            )

            if cachedSet is not None:
                return True

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

            if outputInfo is not None:
                return True

        if self.readFallbackMapper is not None:
            self._recordReadFallback(
                "exists",
                objectId=objId,
            )

            return bool(
                self.readFallbackMapper.exists(objId)
            )

        return False

    def selectAll(self, iterate=False, objectFilter=None):
        if self.readFallbackMapper is None:
            raise NotImplementedError(
                "PostgreSQL selectAll is not implemented yet."
            )

        result = self.readFallbackMapper.selectAll(
            iterate=iterate,
            objectFilter=objectFilter,
        )

        if iterate:
            return self._attachRuntimeContextIterator(result)

        return self._attachRuntimeContextList(result)

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

    def selectAllBatch(self, objectFilter=None):
        if objectFilter is not None and not callable(objectFilter):
            raise TypeError("objectFilter must be callable or None")

        fallbackObjects = []
        fallbackProtocolsById = {}

        if self.readFallbackMapper is not None:
            self._recordReadFallback(
                "selectAllBatch.compatibilityMerge",
                objectFilter=objectFilter,
            )
            fallbackObjects = self.readFallbackMapper.selectAllBatch(
                objectFilter=objectFilter,
            )
            fallbackObjects = self._attachRuntimeContextList(fallbackObjects)

            for obj in fallbackObjects:
                if not isinstance(obj, Protocol):
                    continue

                protocolId = self._getObjId(obj)

                if protocolId is not None:
                    fallbackProtocolsById[protocolId] = obj

        result = []
        seenIds = set()

        for row in self.flatMapper.getProtocols(self.projectId) or []:
            protocolId = self._toOptionalInt(row.get("protocolId"))

            if protocolId is None or protocolId in seenIds:
                continue

            protocol = fallbackProtocolsById.get(protocolId)

            if protocol is None:
                protocol = self._getOrBuildProtocolFromPostgresqlRow(row)

                if protocol is None:
                    continue

                if objectFilter is not None and not objectFilter(protocol):
                    continue
            else:
                    protocol = self._adoptSqliteProtocolMirror(protocol, row)

                    if protocol is None:
                        continue

                    if objectFilter is not None and not objectFilter(protocol):
                        continue

            result.append(protocol)
            seenIds.add(protocolId)

        # Preserve objects that only exist in the compatibility mapper.
        # With Project.getRuns(), objectFilter limits these to Protocol.
        for obj in fallbackObjects:
            objId = self._getObjId(obj)

            if objId is not None and objId in seenIds:
                continue

            result.append(obj)

            if objId is not None:
                seenIds.add(objId)

        return result

    def selectBy(self, iterate=False, objectFilter=None, **args):
        if objectFilter is not None and not callable(objectFilter):
            if self.readFallbackMapper is None:
                raise TypeError("objectFilter must be callable or None")

            return self._selectByFromReadFallback(
                iterate=iterate,
                objectFilter=objectFilter,
                **args,
            )

        if self._isProjectCreationTimeQuery(args):
            creationTime = self._selectProjectCreationTimeFromPostgresql()

            if creationTime is not None:
                result = [creationTime]

                if objectFilter is not None and not objectFilter(creationTime):
                    result = []

                return iter(result) if iterate else result

            if self.readFallbackMapper is None:
                return iter(()) if iterate else []

        return self._selectByFromReadFallback(
            iterate=iterate,
            objectFilter=objectFilter,
            **args,
        )

    def _selectByFromReadFallback(
            self,
            iterate=False,
            objectFilter=None,
            **args,
    ):
        if self.readFallbackMapper is None:
            raise NotImplementedError(
                "PostgreSQL selectBy is only implemented "
                "for project CreationTime."
            )

        self._recordReadFallback(
            "selectBy",
            iterate=iterate,
            query=args,
            objectFilter=objectFilter,
        )

        result = self.readFallbackMapper.selectBy(
            iterate=iterate,
            objectFilter=objectFilter,
            **args,
        )

        if iterate:
            return self._attachRuntimeContextIterator(result)

        return self._attachRuntimeContextList(result)

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
            return self._selectByClassFromReadFallback(
                className=className,
                includeSubclasses=includeSubclasses,
                iterate=iterate,
                objectFilter=objectFilter,
            )

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
            return self._selectByClassFromReadFallback(
                className=className,
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

        if self.readFallbackMapper is not None:
            self._recordReadFallback(
                "selectByClass.setCompatibilityMerge",
                className=className,
                includeSubclasses=includeSubclasses,
                objectFilter=objectFilter,
            )

            fallbackResult = self.readFallbackMapper.selectByClass(
                className,
                includeSubclasses=includeSubclasses,
                iterate=False,
                objectFilter=objectFilter,
            )

            fallbackObjects = self._attachRuntimeContextList(
                fallbackResult or []
            )

            result = self._mergeRuntimeClassResults(
                result,
                fallbackObjects,
            )

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

        if self.readFallbackMapper is not None:
            self._recordReadFallback(
                "selectByClass.protocolCompatibilityMerge",
                className=className,
                includeSubclasses=includeSubclasses,
                objectFilter=objectFilter,
            )

            fallbackResult = self.readFallbackMapper.selectByClass(
                className,
                includeSubclasses=includeSubclasses,
                iterate=False,
                objectFilter=objectFilter,
            )

            fallbackObjects = self._attachRuntimeContextList(
                fallbackResult or []
            )

            result = self._mergeRuntimeClassResults(
                result,
                fallbackObjects,
            )

        return iter(result) if iterate else result

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

    def _selectByClassFromReadFallback(
            self,
            className,
            includeSubclasses,
            iterate,
            objectFilter,
    ):
        if self.readFallbackMapper is None:
            raise NotImplementedError(
                "PostgreSQL selectByClass is only implemented "
                "for native Scipion Set classes."
            )

        self._recordReadFallback(
            "selectByClass.unsupportedClass",
            className=className,
            includeSubclasses=includeSubclasses,
            iterate=iterate,
            objectFilter=objectFilter,
        )

        result = self.readFallbackMapper.selectByClass(
            className,
            includeSubclasses=includeSubclasses,
            iterate=iterate,
            objectFilter=objectFilter,
        )

        if iterate:
            return self._attachRuntimeContextIterator(result)

        return self._attachRuntimeContextList(result)

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

    def _mergeRuntimeClassResults(
            self,
            postgresqlObjects,
            fallbackObjects,
    ):
        result = []
        identities = set()

        for obj in list(postgresqlObjects or []) + list(fallbackObjects or []):
            identity = self._getRuntimeReadIdentity(obj)

            if identity is not None and identity in identities:
                continue

            if identity is not None:
                identities.add(identity)

            result.append(obj)

        return result

    def _getRuntimeReadIdentity(self, obj):
        objId = self._getObjId(obj)

        if objId is None:
            return None

        nativeClass = getattr(obj, "_postgresqlNativeSetClass", None)

        if isinstance(nativeClass, type):
            className = nativeClass.__name__
        else:
            className = self._getClassName(obj)

        return str(className), str(objId)

    def getParent(
            self,
            obj,
    ):
        if obj is None:
            return None

        # Native PostgreSQL items and sets are hydrated
        # with their actual parent object.
        parent = getattr(
            obj,
            "_objParent",
            None,
        )

        if parent is not None:
            return self._attachRuntimeContext(
                parent
            )

        parentId = self._call(
            obj,
            "getObjParentId",
            None,
        )

        if parentId is None:
            parentId = getattr(
                obj,
                "_objParentId",
                None,
            )

        if parentId is not None:
            parent = self.selectById(
                parentId
            )

            if parent is not None:
                return self._attachRuntimeContext(
                    parent
                )

        if self.readFallbackMapper is not None:
            self._recordReadFallback(
                "getParent",
                objectId=self._getObjId(obj),
                objectClass=self._getClassName(obj),
            )

            parent = self.readFallbackMapper.getParent(obj)
            return self._attachRuntimeContext(parent)


        return None

    def delete(self, obj):
        if self.writeFallbackMapper is not None:
            self.writeFallbackMapper.delete(obj)

        if isinstance(obj, Protocol):
            self.flatMapper.deleteProtocol(self.projectId, [obj])
            return

        objId = self._getObjId(obj)
        if objId is None:
            return

        self.db.execute(
            """
            DELETE FROM scipion_objects
             WHERE "projectId" = %s
               AND "scipionObjId" = %s
            """,
            (self.projectId, int(objId)),
        )

    # ---------------------------------------------------------------------
    # Relations API
    # ---------------------------------------------------------------------

    def insertRelation(self, relName, creatorObj, parentObj, childObj,
                       parentExt=None, childExt=None):
        if self.writeFallbackMapper is not None:
            self.writeFallbackMapper.insertRelation(
                relName,
                creatorObj,
                parentObj,
                childObj,
                parentExt,
                childExt,
            )

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

        self._insertCanonicalObjectRelationData(
            relName=relName,
            creatorId=creatorId,
            parentId=parentId,
            childId=childId,
            parentExtended=parentExtended,
            childExtended=childExtended,
        )

    def _insertCanonicalObjectRelationData(
            self,
            relName,
            creatorId,
            parentId,
            childId,
            parentExtended=None,
            childExtended=None,
    ):
        """
        Best-effort dual write for PostgreSQL canonical object relations.

        scipion_relations keeps Mapper/Scipion runtime ids.
        scipion_object_relations keeps PostgreSQL scipion_objects.id FKs.

        Not every runtime relation can be canonicalized immediately because some
        objects may still exist only in the fallback mapper. In that case we keep
        the compatibility row and skip the canonical row.
        """
        creatorObjectId = self._resolveCanonicalScipionObjectRowId(creatorId)
        parentObjectId = self._resolveCanonicalScipionObjectRowId(parentId)
        childObjectId = self._resolveCanonicalScipionObjectRowId(childId)

        if creatorObjectId is None or parentObjectId is None or childObjectId is None:
            logger.debug(
                "Skipping canonical object relation dual-write because some objects "
                "are not persisted yet. projectId=%s relation=%s creatorId=%s "
                "parentId=%s childId=%s creatorObjectId=%s parentObjectId=%s "
                "childObjectId=%s",
                self.projectId,
                relName,
                creatorId,
                parentId,
                childId,
                creatorObjectId,
                parentObjectId,
                childObjectId,
            )
            return

        canonicalParentExtended = parentExtended or None
        canonicalChildExtended = childExtended or None

        metadata = {
            "source": "postgresql_runtime_mapper",
            "runtimeRelationTable": "scipion_relations",
            "runtimeCreatorObjId": int(creatorId),
            "runtimeParentObjId": int(parentId),
            "runtimeChildObjId": int(childId),
        }

        self.db.execute(
            """
            INSERT INTO scipion_object_relations (
                "projectId",
                "creatorObjectId",
                "parentObjectId",
                "childObjectId",
                name,
                "parentExtended",
                "childExtended",
                metadata
            )
            SELECT %s, %s, %s, %s, %s, %s, %s, %s::jsonb
            WHERE NOT EXISTS (
                SELECT 1
                  FROM scipion_object_relations existing
                 WHERE existing."projectId" = %s
                   AND existing.name = %s
                   AND existing."creatorObjectId" = %s
                   AND existing."parentObjectId" = %s
                   AND existing."childObjectId" = %s
                   AND COALESCE(existing."parentExtended", '') = COALESCE(%s, '')
                   AND COALESCE(existing."childExtended", '') = COALESCE(%s, '')
            )
            """,
            (
                self.projectId,
                int(creatorObjectId),
                int(parentObjectId),
                int(childObjectId),
                str(relName),
                canonicalParentExtended,
                canonicalChildExtended,
                json.dumps(metadata),
                self.projectId,
                str(relName),
                int(creatorObjectId),
                int(parentObjectId),
                int(childObjectId),
                canonicalParentExtended,
                canonicalChildExtended,
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

    def _deleteCanonicalObjectRelationsByCreatorId(self, creatorId) -> None:
        creatorObjectId = self._resolveCanonicalScipionObjectRowId(creatorId)

        if creatorObjectId is None:
            return

        self.db.execute(
            """
            DELETE FROM scipion_object_relations
             WHERE "projectId" = %s
               AND "creatorObjectId" = %s
            """,
            (
                self.projectId,
                int(creatorObjectId),
            ),
        )

    def deleteRelations(self, creatorObj):
        if self.writeFallbackMapper is not None:
            self.writeFallbackMapper.deleteRelations(creatorObj)

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

        self._deleteCanonicalObjectRelationsByCreatorId(creatorId)

    def getRelationsByCreator(self, creatorObj):
        if self.readFallbackMapper is not None:
            self._recordReadFallback(
                "getRelationsByCreator",
                creatorId=self._getObjId(creatorObj),
            )

            return self.readFallbackMapper.getRelationsByCreator(
                creatorObj
            )

        creatorId = self._requireObjId(creatorObj)

        return self.db.fetchAll(
            """
            SELECT *
              FROM scipion_relations
             WHERE "projectId" = %s
               AND "creatorObjId" = %s
             ORDER BY id ASC
            """,
            (
                self.projectId,
                int(creatorId),
            ),
        )

    def getRelationsByName(self, relationName):
        if self.readFallbackMapper is not None:
            self._recordReadFallback(
                "getRelationsByName",
                relationName=relationName,
            )

            return self.readFallbackMapper.getRelationsByName(
                relationName
            )

        return self.db.fetchAll(
            """
            SELECT *
              FROM scipion_relations
             WHERE "projectId" = %s
               AND name = %s
             ORDER BY id ASC
            """,
            (
                self.projectId,
                str(relationName),
            ),
        )

    def getRelationChilds(self, relName, parentObj):
        if self.readFallbackMapper is not None:
            self._recordReadFallback(
                "getRelationChilds",
                relationName=relName,
                parentId=self._getObjId(parentObj),
            )

            return self.readFallbackMapper.getRelationChilds(
                relName,
                parentObj,
            )

        raise NotImplementedError(
            "PostgreSQL getRelationChilds object reconstruction "
            "is not implemented yet."
        )

    def getRelationParents(self, relName, childObj):
        if self.readFallbackMapper is not None:
            self._recordReadFallback(
                "getRelationParents",
                relationName=relName,
                childId=self._getObjId(childObj),
            )

            return self.readFallbackMapper.getRelationParents(
                relName,
                childObj,
            )

        raise NotImplementedError(
            "PostgreSQL getRelationParents object reconstruction "
            "is not implemented yet."
        )

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

    def _storeSetObject(self, scipionSet):
        ownerProtocol = self._findOwnerProtocol(scipionSet)
        protocolDbId = self._resolveProtocolDbIdFromObject(ownerProtocol)
        outputName = self._getObjectName(scipionSet) or self._getClassName(scipionSet)

        if protocolDbId is None or not outputName:
            logger.debug(
                "Skipping runtime set persistence without owner/outputName: %s",
                scipionSet,
            )
            return

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

    def _shouldSkipRuntimeObjectTree(self, outputName, scipionObj) -> bool:
        """
        Skip only known internal protocol runtime fields that are not real outputs.
        """
        name = str(outputName or "").strip()

        internalNames = {
            "_jobId",
        }

        return name in internalNames

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

    def _ensureObjId(self, obj) -> Optional[int]:
        """
        Ensure Scipion object has an _objId.

        SqliteMapper.insert assigns _objId automatically. If this mapper is used
        as Project.mapper, PostgreSQL must do the same.
        """
        if obj is None:
            return None

        objId = self._getObjId(obj)
        if objId is not None:
            return objId

        allocator = getattr(self.flatMapper, "allocateProjectObjectId", None)
        if not callable(allocator):
            raise RuntimeError("PostgresqlFlatMapper does not provide allocateProjectObjectId")

        objId = int(allocator(self.projectId))

        try:
            self._setObjId(obj, objId)
        except Exception as exc:
            raise RuntimeError("Could not assign _objId=%s to %s" % (objId, obj)) from exc

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

    def _attachRuntimeContext(self, obj):
        if obj is None:
            return obj

        if isinstance(obj, Protocol):
            obj.setMapper(self)

            if self.project is not None:
                try:
                    obj.setProject(self.project)
                except Exception:
                    pass

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

    def _applyStoredProtocolParams(self, protocol, rawParams):
        params = self._normalizeStoredProtocolParams(rawParams)

        for key, storedValue in params.items():
            value = self._extractStoredProtocolParamValue(storedValue)
            if value is None:
                continue

            param = None
            try:
                param = protocol.getParam(key)
            except Exception:
                param = None

            if param is not None:
                setter = getattr(param, "set", None)
                if callable(setter):
                    try:
                        setter(value)
                    except Exception:
                        logger.debug(
                            "Could not restore PostgreSQL protocol param. key=%s value=%s",
                            key,
                            value,
                            exc_info=True,
                        )

                try:
                    protocol.setAttributeValue(key, value)
                except Exception:
                    pass
                continue

            attr = getattr(protocol, key, None)
            attrSetter = getattr(attr, "set", None)
            if callable(attrSetter):
                try:
                    attrSetter(value)
                    continue
                except Exception:
                    pass

            try:
                setattr(protocol, key, value)
            except Exception:
                pass

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

    def _applyStoredProtocolParam(self, protocol: Protocol, key: str, value):
        param = None

        try:
            param = protocol.getParam(key)
        except Exception:
            param = None

        if param is not None:
            setter = getattr(param, "set", None)
            if callable(setter):
                try:
                    setter(value)
                except Exception:
                    logger.debug(
                        "Could not restore protocol param using param.set(). "
                        "param=%s value=%s",
                        key,
                        value,
                        exc_info=True,
                    )

            try:
                protocol.setAttributeValue(key, value)
            except Exception:
                logger.debug(
                    "Could not restore protocol attribute value. param=%s value=%s",
                    key,
                    value,
                    exc_info=True,
                )

            return

        attr = getattr(protocol, key, None)
        attrSetter = getattr(attr, "set", None)
        if callable(attrSetter):
            try:
                attrSetter(value)
                return
            except Exception:
                logger.debug(
                    "Could not restore protocol attr using attr.set(). "
                    "attr=%s value=%s",
                    key,
                    value,
                    exc_info=True,
                )

        try:
            setattr(protocol, key, value)
        except Exception:
            logger.debug(
                "Could not setattr protocol param. attr=%s value=%s",
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

        internalNames = {
            "_jobId",
            "_pid",
            "_outputs",
        }

        for rawName in candidateNames:
            name = str(rawName or "").strip()
            if not name:
                continue

            if name in internalNames:
                return True

            shortName = name.split(".")[-1]
            if shortName in internalNames:
                return True

        return False