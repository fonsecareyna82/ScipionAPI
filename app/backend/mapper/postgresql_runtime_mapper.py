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

import pyworkflow.object as pwobject
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

SQLITE_EXECUTION_CHILD_ID_START = 1_000_000_000


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
        callers = []

        try:
            frame = frame.f_back

            while frame is not None and len(callers) < 4:
                moduleName = str(
                    frame.f_globals.get(
                        "__name__",
                        "",
                    )
                )

                if moduleName != __name__:
                    caller = "%s.%s" % (
                        moduleName,
                        frame.f_code.co_name,
                    )

                    if not callers or callers[-1] != caller:
                        callers.append(caller)

                frame = frame.f_back

        finally:
            del frame

        if not callers:
            return "unknown"

        return " -> ".join(callers)

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

    @staticmethod
    def _clearFallbackMapperCaches(
            *fallbackMappers,
    ) -> None:
        seenMappers = set()

        for fallbackMapper in fallbackMappers:
            if fallbackMapper is None:
                continue

            mapperIdentity = id(
                fallbackMapper
            )

            if mapperIdentity in seenMappers:
                continue

            seenMappers.add(
                mapperIdentity
            )

            for attributeName in (
                    "objDict",
                    "updateDict",
                    "updatePendingPointers",
            ):
                cache = getattr(
                    fallbackMapper,
                    attributeName,
                    None,
                )

                if isinstance(
                        cache,
                        (
                                dict,
                                list,
                                set,
                        ),
                ):
                    cache.clear()

    # ---------------------------------------------------------------------
    # Generic Mapper API
    # ---------------------------------------------------------------------

    def _storeProtocolInWriteFallback(
            self,
            protocol: Protocol,
    ) -> bool:
        """
        Ensure that the protocol root exists in the temporary SQLite
        execution mirror preserving its PostgreSQL object id.

        SqliteObjectsDb.insertObject() cannot be used here because it always
        allocates its own AUTOINCREMENT id. The protocol root must be inserted
        explicitly, while internal SQLite child objects use a separate high
        id range.
        """
        writeFallbackMapper = self.writeFallbackMapper

        if writeFallbackMapper is None:
            raise RuntimeError(
                "SQLite write fallback mapper is not available."
            )

        protocolId = self._getObjId(
            protocol
        )

        if protocolId is None:
            raise RuntimeError(
                "Cannot materialize protocol SQLite root without id."
            )

        protocolId = int(protocolId)

        db = getattr(
            writeFallbackMapper,
            "db",
            None,
        )

        if db is None:
            raise RuntimeError(
                "SQLite write fallback mapper does not expose db."
            )

        expectedClassName = (
            Mapper.getObjectPersistingClassName(
                protocol
            )
        )

        # Keep SQLite-generated child ids away from PostgreSQL-owned ids.
        db.executeCommand(
            """
            UPDATE sqlite_sequence
               SET seq = CASE
                         WHEN seq < ? THEN ?
                         ELSE seq
                         END
             WHERE name = 'Objects'
            """,
            (
                SQLITE_EXECUTION_CHILD_ID_START,
                SQLITE_EXECUTION_CHILD_ID_START,
            ),
        )

        if int(
                getattr(
                    db.cursor,
                    "rowcount",
                    0,
                )
                or 0
        ) == 0:
            db.executeCommand(
                """
                INSERT INTO sqlite_sequence (
                    name,
                    seq
                )
                VALUES ('Objects', ?)
                """,
                (
                    SQLITE_EXECUTION_CHILD_ID_START,
                ),
            )

        existingRow = db.selectObjectById(
            protocolId
        )

        if existingRow is not None:
            existingClassName = str(
                existingRow["classname"]
                or ""
            )

            existingParentId = existingRow[
                "parent_id"
            ]

            if (
                    existingParentId is not None
                    or existingClassName
                    != str(expectedClassName)
            ):
                raise RuntimeError(
                    "SQLite execution id collision for protocol %s: "
                    "expected root class %s, found class %s "
                    "with parentId=%s."
                    % (
                        protocolId,
                        expectedClassName,
                        existingClassName,
                        existingParentId,
                    )
                )

            return False

        objName = str(
            getattr(
                protocol,
                "_objName",
                "",
            )
            or ""
        )

        objLabel = getattr(
            protocol,
            "_objLabel",
            None,
        )

        objComment = getattr(
            protocol,
            "_objComment",
            None,
        )

        db.executeCommand(
            """
            INSERT INTO Objects (
                id,
                parent_id,
                name,
                classname,
                value,
                label,
                comment,
                creation
            )
            VALUES (
                ?,
                NULL,
                ?,
                ?,
                NULL,
                ?,
                ?,
                datetime('now')
            )
            """,
            (
                protocolId,
                objName,
                str(expectedClassName),
                objLabel,
                objComment,
            ),
        )

        logger.info(
            "Inserted protocol root in SQLite execution mirror. "
            "projectId=%s protocolId=%s className=%s",
            self.projectId,
            protocolId,
            expectedClassName,
        )

        return True

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

    def _storeRuntimeProtocol(
            self,
            protocol: Protocol,
    ) -> None:
        """
        Store a protocol using PostgreSQL as the authoritative runtime
        persistence.

        PostgreSQL always allocates and owns the protocol id. When the
        temporary SQLite execution mirror is enabled, it receives an exact
        copy preserving that PostgreSQL id.
        """
        protocolId = self._ensureObjId(
            protocol
        )

        if protocolId is None:
            raise RuntimeError(
                "Cannot store PostgreSQL runtime protocol without id."
            )

        # PostgreSQL is written first and remains authoritative.
        self._storeProtocol(
            protocol
        )

        if self.writeFallbackMapper is not None:
            self.ensureProtocolWriteFallbackMirror(
                protocol
            )

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

            self._sqliteProtocolMirrorIds.discard(
                protocolId
            )

            evictedProtocolIds.append(
                protocolId
            )

        return {
            "evictedProtocolIds": evictedProtocolIds,
            "count": len(evictedProtocolIds),
        }

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

    def ensureProtocolWriteFallbackMirror(
            self,
            protocol: Protocol,
    ) -> Dict[str, Any]:
        """
        Materialize a PostgreSQL runtime protocol in the temporary SQLite
        execution mirror.

        PostgreSQL owns the protocol identity. SQLite preserves that root id
        and allocates only internal child ids from its reserved high range.
        """
        writeFallbackMapper = self.writeFallbackMapper

        if writeFallbackMapper is None:
            raise RuntimeError(
                "Cannot materialize protocol SQLite execution mirror: "
                "write fallback mapper is not available."
            )

        protocolId = self._ensureObjId(
            protocol
        )

        if protocolId is None:
            raise RuntimeError(
                "Cannot materialize protocol SQLite execution mirror "
                "without protocol id."
            )

        protocolId = int(protocolId)

        rootCreated = self._storeProtocolInWriteFallback(
            protocol
        )

        # Remove any object previously cached under this id. A stale cache
        # could otherwise return a String or another compatibility object
        # even after the database row has been corrected.
        self._clearFallbackMapperCaches(
            writeFallbackMapper
        )

        identitySnapshot = (
            self
            ._captureRuntimeObjectTreeIdentity(
                protocol
            )
        )

        try:
            writeFallbackMapper.store(
                protocol
            )

            writeFallbackMapper.commit()

        finally:
            # SQLite is allowed to assign internal compatibility ids,
            # but those ids must never leak back into the authoritative
            # PostgreSQL runtime object.
            self._restoreRuntimeObjectTreeIdentity(
                identitySnapshot
            )

            self._clearFallbackMapperCaches(
                writeFallbackMapper
            )

        mirroredProtocol = (
            writeFallbackMapper.selectById(
                protocolId
            )
        )

        if mirroredProtocol is None:
            raise RuntimeError(
                "Protocol %s was not found in the SQLite "
                "execution mirror after materialization."
                % protocolId
            )

        if not isinstance(
                mirroredProtocol,
                Protocol,
        ):
            raise RuntimeError(
                "Invalid SQLite execution mirror for protocol %s: "
                "expected Protocol, found %s."
                % (
                    protocolId,
                    mirroredProtocol.__class__.__name__,
                )
            )

        self._sqliteProtocolMirrorIds.add(
            protocolId
        )

        report = {
            "protocolId": protocolId,
            "created": bool(rootCreated),
            "updated": not bool(rootCreated),
            "mirrorClassName": (
                mirroredProtocol
                .__class__
                .__name__
            ),
        }

        logger.info(
            "Ensured protocol SQLite execution mirror. "
            "projectId=%s report=%s",
            self.projectId,
            report,
        )

        return report

    def insert(self, obj):
        if obj is None:
            return

        if isinstance(obj, Protocol):
            # PostgreSQL allocates the protocol id. The optional SQLite
            # execution mirror must preserve that same identity.
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
        if self._updateProtocolFromPostgresql(
                obj
        ):
            return None

        if self._updateSetFromPostgresql(
                obj
        ):
            return None

        if self._updateGenericObjectFromPostgresql(
                obj
        ):
            return None

        if self.readFallbackMapper is None:
            raise NotImplementedError(
                "PostgreSQL updateFrom is only implemented "
                "for protocols, PostgreSQL runtime Sets "
                "and supported generic runtime objects."
            )

        self._recordReadFallback(
            "updateFrom",
            objectId=self._getObjId(
                obj
            ),
            objectClass=self._getClassName(
                obj
            ),
        )

        return self.readFallbackMapper.updateFrom(
            obj
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
            if (
                    protocolId
                    in self._sqliteProtocolMirrorIds
            ):
                refreshedProtocol = (
                    self
                    ._refreshSqliteProtocolMirrorFromPostgresqlRow(
                        protocol,
                        row,
                    )
                )

            else:
                refreshedProtocol = (
                    self
                    ._refreshProtocolFromPostgresqlRow(
                        protocol,
                        row,
                    )
                )

            if refreshedProtocol is not protocol:
                raise RuntimeError(
                    "PostgreSQL protocol updateFrom "
                    "replaced protocol identity %s."
                    % protocolId
                )

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

        obj = self._selectGenericObjectByIdFromPostgresql(objId)

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

    def selectRuntimeProtocolById(
            self,
            objId,
            refreshCached: bool = True,
    ):
        """
        Return one stable, fully hydrated protocol for runtime operations.

        Prefer the SQLite compatibility object on the first read because it
        contains native pointers, internal attributes and outputs. Cache that
        instance so all subsequent runtime reads reuse the same protocol
        identity.

        When refreshCached is False, an existing protocol instance is returned
        without applying PostgreSQL status, params or runtime metadata. This is
        used by relation reads to keep owner protocols strictly read-only.
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

        cachedProtocol = self._runtimeProtocolsById.get(
            protocolId
        )

        if cachedProtocol is not None:
            if row:
                if refreshCached:
                    return (
                        self
                        ._getOrBuildProtocolFromPostgresqlRow(
                            row
                        )
                    )

                return cachedProtocol

            if protocolId in self._sqliteProtocolMirrorIds:
                if refreshCached:
                    return self._attachRuntimeContext(
                        cachedProtocol
                    )

                return cachedProtocol

            # A PostgreSQL-native cached protocol whose row disappeared must
            # not remain available as a stale runtime object.
            self._runtimeProtocolsById.pop(
                protocolId,
                None,
            )

        protocol = self._selectByIdFromReadFallback(
            protocolId,
            auditOperation=(
                "selectRuntimeProtocolById."
                "compatibilityMirror"
            ),
        )

        if isinstance(protocol, Protocol):
            if row:
                if refreshCached:
                    return self._adoptSqliteProtocolMirror(
                        protocol,
                        row,
                    )

                return protocol

            if not refreshCached:
                return protocol

            protocol = self._attachRuntimeContext(
                protocol
            )

            # Preserve identity for compatibility-only protocols too. If the
            # PostgreSQL row appears later, it will receive the safe mirror
            # refresh.
            self._runtimeProtocolsById[
                protocolId
            ] = protocol

            self._sqliteProtocolMirrorIds.add(
                protocolId
            )

            return protocol

        if row:
            if refreshCached:
                return (
                    self
                    ._getOrBuildProtocolFromPostgresqlRow(
                        row
                    )
                )

            # Build an independent read representation. Do not place it in
            # the shared protocol cache and do not modify another instance.
            return self._buildProtocolFromPostgresqlRow(
                row
            )

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
            rows
        )

    def _buildGenericObjectFromPostgresqlRows(
            self,
            rows,
    ):
        """
        Build an independent object tree without modifying or attaching it to
        the owner protocol.
        """
        objectsByRowId = {}
        rootObject = None

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
                return None

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

            if (
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
            ):
                return None

            objectClass = (
                self
                ._resolveRuntimeObjectClass(
                    row.get("className")
                )
            )

            if not self._isSupportedGenericRuntimeObjectClass(
                    objectClass
            ):
                return None

            parentObject = None
            attributeName = None

            if depth > 0:
                parentRowId = self._toOptionalInt(
                    row.get("parentObjectId")
                )

                parentObject = objectsByRowId.get(
                    parentRowId
                )

                if parentObject is None:
                    return None

                attributeName = str(
                    row.get("name")
                    or ""
                ).strip()

                if not attributeName:
                    return None

            scipionObject = None

            if parentObject is not None:
                existingAttribute = getattr(
                    parentObject,
                    attributeName,
                    None,
                )

                if isinstance(
                        existingAttribute,
                        objectClass,
                ):
                    scipionObject = (
                        existingAttribute
                    )

            if scipionObject is None:
                try:
                    scipionObject = objectClass()
                except Exception:
                    logger.debug(
                        "Could not instantiate PostgreSQL "
                        "generic object. "
                        "projectId=%s className=%s "
                        "runtimeObjectId=%s",
                        self.projectId,
                        row.get("className"),
                        row.get("scipionObjId"),
                        exc_info=True,
                    )
                    return None

            if self._call(
                    scipionObject,
                    "isPointer",
                    False,
            ):
                return None

            if not self._restoreGenericObjectStateFromPostgresqlRow(
                    scipionObject,
                    row,
            ):
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
                return None

            rootObject = scipionObject

            parentRuntimeObjectId = self._toOptionalInt(
                row.get("rootParentScipionObjId")
            )

            if parentRuntimeObjectId is None:
                parentRuntimeObjectId = self._toOptionalInt(
                    row.get("ownerProtocolId")
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

            if self._resolveCanonicalScipionObjectRowId(runtimeObjectId) is not None:
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

    def selectAll(
            self,
            iterate=False,
            objectFilter=None,
    ):
        """
        Return root runtime objects using the PostgreSQL-first batch reader.

        selectAllBatch owns the PostgreSQL/SQLite compatibility merge.
        selectAll preserves the native Mapper contract by excluding child
        attributes and restoring the project CreationTime root when it is
        not available through the compatibility mapper.
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

            fallbackObjects = self._attachRuntimeContextList(
                fallbackObjects
            )

            for obj in fallbackObjects:
                if not isinstance(obj, Protocol):
                    continue

                protocolId = self._getObjId(obj)

                if protocolId is not None:
                    fallbackProtocolsById[protocolId] = obj

        result = []
        seenProtocolIds = set()
        sqliteMirrorIds = []
        postgresqlNativeProtocolIds = []

        for row in self.flatMapper.getProtocols(self.projectId) or []:
            protocolId = self._toOptionalInt(
                row.get("protocolId")
            )

            if (
                    protocolId is None
                    or protocolId in seenProtocolIds
            ):
                continue

            protocol = fallbackProtocolsById.get(protocolId)

            if protocol is None:
                protocol = self._getOrBuildProtocolFromPostgresqlRow(
                    row
                )

                if protocol is None:
                    continue

                if (
                        objectFilter is not None
                        and not objectFilter(protocol)
                ):
                    continue

                postgresqlNativeProtocolIds.append(protocolId)

            else:
                protocol = self._adoptSqliteProtocolMirror(
                    protocol,
                    row,
                )

                if protocol is None:
                    continue

                if (
                        objectFilter is not None
                        and not objectFilter(protocol)
                ):
                    continue

                sqliteMirrorIds.append(protocolId)

            result.append(protocol)
            seenProtocolIds.add(protocolId)

        genericObjects = self._selectAllGenericObjectsFromPostgresql(
            objectFilter=objectFilter,
        )

        result.extend(genericObjects)

        postgresqlIdentities = set()

        for obj in result:
            identity = self._getRuntimeReadIdentity(obj)

            if identity is not None:
                postgresqlIdentities.add(identity)

        fallbackOnlyIds = []
        fallbackOnlyIdentities = []

        for obj in fallbackObjects:
            identity = self._getRuntimeReadIdentity(obj)

            if (
                    identity is not None
                    and identity in postgresqlIdentities
            ):
                continue

            fallbackOnlyIdentities.append(identity)

            objId = self._getObjId(obj)

            if objId is not None:
                fallbackOnlyIds.append(objId)

        genericObjectIds = []

        for obj in genericObjects:
            objId = self._getObjId(obj)

            if objId is not None:
                genericObjectIds.append(objId)

        if getattr(self, "_fallbackAuditEnabled", False):
            logger.warning(
                "POSTGRESQL_RUNTIME_FALLBACK selectAllBatchDetails %s",
                json.dumps(
                    {
                        "projectId": self.projectId,
                        "postgresqlCount": len(
                            postgresqlIdentities
                        ),
                        "fallbackCount": len(
                            fallbackObjects
                        ),
                        "fallbackOnlyCount": len(
                            fallbackOnlyIdentities
                        ),
                        "fallbackOnlyIds": fallbackOnlyIds,
                        "fallbackOnlyIdentities": (
                            fallbackOnlyIdentities
                        ),
                        "sqliteMirrorCount": len(
                            sqliteMirrorIds
                        ),
                        "sqliteMirrorIds": sqliteMirrorIds,
                        "postgresqlNativeCount": len(
                            postgresqlNativeProtocolIds
                        ),
                        "postgresqlNativeIds": (
                            postgresqlNativeProtocolIds
                        ),
                        "postgresqlGenericCount": len(
                            genericObjects
                        ),
                        "postgresqlGenericIds": (
                            genericObjectIds
                        ),
                    },
                    sort_keys=True,
                ),
            )

        return self._mergeRuntimeClassResults(
            result,
            fallbackObjects,
        )

    def selectBy(
            self,
            iterate=False,
            objectFilter=None,
            **args,
    ):
        if objectFilter is not None and not callable(objectFilter):
            if self.readFallbackMapper is None:
                raise TypeError(
                    "objectFilter must be callable or None"
                )

            return self._selectByFromReadFallback(
                iterate=iterate,
                objectFilter=objectFilter,
                **args,
            )

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

            if self.readFallbackMapper is None:
                return iter(()) if iterate else []

        unsupportedFields = (
                set(args)
                - self.SELECT_BY_FIELDS
        )

        if unsupportedFields:
            return self._selectByFromReadFallback(
                iterate=iterate,
                objectFilter=objectFilter,
                **args,
            )

        if any(
                value is None
                for value in args.values()
        ):
            if self.readFallbackMapper is not None:
                return self._selectByFromReadFallback(
                    iterate=iterate,
                    objectFilter=objectFilter,
                    **args,
                )

            return iter(()) if iterate else []

        if "id" in args:
            runtimeObjectId = self._toOptionalInt(
                args.get("id")
            )

            if runtimeObjectId is None:
                if self.readFallbackMapper is not None:
                    return self._selectByFromReadFallback(
                        iterate=iterate,
                        objectFilter=objectFilter,
                        **args,
                    )

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

            if self.readFallbackMapper is not None:
                return self._selectByFromReadFallback(
                    iterate=iterate,
                    objectFilter=objectFilter,
                    **args,
                )

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

        if self.readFallbackMapper is not None:
            self._recordReadFallback(
                "selectBy.compatibilityMerge",
                query=args,
                objectFilter=objectFilter,
            )

            fallbackResult = self.readFallbackMapper.selectBy(
                iterate=False,
                objectFilter=objectFilter,
                **args,
            )

            fallbackObjects = self._attachRuntimeContextList(
                fallbackResult
            )

            result = self._mergeSelectByResults(
                postgresqlObjects=result,
                fallbackObjects=fallbackObjects,
                ownedPostgresqlObjects=postgresqlObjects,
            )

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

        result = self._mergeRuntimeClassResults(
            result,
            [],
        )

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

    def _mergeSelectByResults(
            self,
            postgresqlObjects,
            fallbackObjects,
            ownedPostgresqlObjects,
    ):
        ownedIds = set()
        ownedObjectsWithoutId = set()

        for obj in ownedPostgresqlObjects:
            objId = self._getObjId(obj)

            if objId is not None:
                ownedIds.add(str(objId))
                continue

            identity = self._getSelectByObjectWithoutIdIdentity(
                obj
            )

            if identity is not None:
                ownedObjectsWithoutId.add(identity)

        compatibleFallbackObjects = []

        for obj in fallbackObjects:
            objId = self._getObjId(obj)

            if (
                    objId is not None
                    and str(objId) in ownedIds
            ):
                continue

            identity = self._getSelectByObjectWithoutIdIdentity(
                obj
            )

            if (
                    identity is not None
                    and identity in ownedObjectsWithoutId
            ):
                continue

            compatibleFallbackObjects.append(obj)

        mergedObjects = self._mergeRuntimeClassResults(
            postgresqlObjects,
            compatibleFallbackObjects,
        )

        return sorted(
            mergedObjects,
            key=self._getSelectBySortKey,
        )

    def _getSelectByObjectWithoutIdIdentity(self, obj):
        objectName = self._getSelectByStoredName(obj)

        if not objectName:
            return None

        return (
            self._getSelectByStoredClassName(obj),
            objectName,
        )

    def _selectByFromReadFallback(
            self,
            iterate=False,
            objectFilter=None,
            **args,
    ):
        if self.readFallbackMapper is None:
            raise NotImplementedError(
                "PostgreSQL selectBy does not support "
                "the requested query fields: %s"
                % sorted(args)
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
            if not self._isSupportedGenericRuntimeObjectClass(requestedClass):
                return self._selectByClassFromReadFallback(
                    className=className,
                    includeSubclasses=includeSubclasses,
                    iterate=iterate,
                    objectFilter=objectFilter,
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

        if self.readFallbackMapper is not None:
            self._recordReadFallback(
                "selectByClass.genericCompatibilityMerge",
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

        return str(objId)

    def getParent(
            self,
            obj,
    ):
        """
        Return the direct parent without refreshing or reattaching it.

        Native PostgreSQL objects may already carry their parent through
        _objParent. Otherwise, resolve the runtime parent id PostgreSQL-first
        and use the SQLite compatibility mapper only as the final fallback.
        """
        if obj is None:
            return None

        parent = getattr(
            obj,
            "_objParent",
            None,
        )

        if parent is not None:
            return parent

        parentId = self._toOptionalInt(
            self._call(
                obj,
                "getObjParentId",
                getattr(
                    obj,
                    "_objParentId",
                    None,
                ),
            )
        )

        if parentId is not None:
            parent = self._selectRelationObjectById(
                parentId
            )

            if parent is not None:
                return parent

        if self.readFallbackMapper is None:
            return None

        self._recordReadFallback(
            "getParent",
            objectId=self._getObjId(
                obj
            ),
            parentId=parentId,
        )

        return self.readFallbackMapper.getParent(
            obj
        )

    def deleteAll(self):
        if (
                self.readFallbackMapper is not None
                and self.writeFallbackMapper is None
        ):
            raise RuntimeError(
                "PostgreSQL deleteAll cannot run with a read "
                "fallback unless a write fallback is also configured."
            )

        if (
                self.readFallbackMapper is not None
                and self.writeFallbackMapper is not None
                and self.readFallbackMapper
                is not self.writeFallbackMapper
        ):
            raise RuntimeError(
                "PostgreSQL deleteAll cannot run when read and "
                "write fallbacks use different mapper instances."
            )

        if self.writeFallbackMapper is not None:
            self.writeFallbackMapper.deleteAll()

        self._clearFallbackMapperCaches(
            self.readFallbackMapper,
            self.writeFallbackMapper,
        )

        deleteResult = self.flatMapper.deleteProjectRuntimeData(
            self.projectId
        )

        self.runtimeSetFactory.clearCaches()
        self._runtimeProtocolsById.clear()
        self._sqliteProtocolMirrorIds.clear()

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
            if self.writeFallbackMapper is not None:
                self.writeFallbackMapper.delete(obj)

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

            if self.writeFallbackMapper is not None:
                self.writeFallbackMapper.delete(obj)

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
            if self.writeFallbackMapper is not None:
                self.writeFallbackMapper.delete(obj)

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

        if self.writeFallbackMapper is not None:
            self.writeFallbackMapper.delete(obj)

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

    def _isRelationSnapshotSynchronized(
            self,
            creatorId,
    ) -> bool:
        """
        Return whether PostgreSQL contains an authoritative relation snapshot.

        The existence of a protocol row alone is not enough. A snapshot only
        becomes authoritative after its complete atomic synchronization.
        """
        creatorId = self._toOptionalInt(
            creatorId
        )

        if creatorId is None:
            return False

        row = self.db.fetchOne(
            """
            SELECT
                "relationsSynchronized"
              FROM protocols
             WHERE "projectId" = %s
               AND "protocolId" = %s
             LIMIT 1
            """,
            (
                self.projectId,
                str(
                    creatorId
                ),
            ),
        )

        return bool(
            row
            and row.get(
                "relationsSynchronized"
            )
        )

    def _buildRuntimeRelationIdentity(
            self,
            relation,
    ):
        """
        Build the logical identity used by PostgreSQL relation uniqueness.

        SQLite relation ids are deliberately excluded.
        """
        def normalizeId(value):
            normalizedValue = (
                self._toOptionalInt(
                    value
                )
            )

            return (
                ""
                if normalizedValue is None
                else str(
                    normalizedValue
                )
            )

        def normalizeText(value):
            return (
                ""
                if value is None
                else str(
                    value
                )
            )

        return (
            normalizeText(
                relation.get(
                    "name"
                )
            ),
            normalizeId(
                relation.get(
                    "parent_id"
                )
            ),
            normalizeId(
                relation.get(
                    "object_parent_id"
                )
            ),
            normalizeId(
                relation.get(
                    "object_child_id"
                )
            ),
            normalizeText(
                relation.get(
                    "object_parent_extended"
                )
            ),
            normalizeText(
                relation.get(
                    "object_child_extended"
                )
            ),
        )

    def _mergeRuntimeRelationRows(
            self,
            postgresqlRelations,
            compatibilityRelations,
    ):
        """
        Merge PostgreSQL and compatibility relations.

        PostgreSQL rows are placed first and therefore win whenever both
        sources expose the same logical relation.
        """
        result = []
        identities = set()

        for relation in (
                list(
                    postgresqlRelations
                    or []
                )
                + list(
                    compatibilityRelations
                    or []
                )
        ):
            identity = (
                self
                ._buildRuntimeRelationIdentity(
                    relation
                )
            )

            if identity in identities:
                continue

            identities.add(
                identity
            )

            result.append(
                relation
            )

        return result

    def _selectCompatibilityRelationsFromReadFallback(
            self,
            *,
            creatorObj=None,
            creatorId=None,
            relationName=None,
            parentId=None,
            childId=None,
            synchronizationByCreator=None,
    ):
        """
        Read relation rows still owned by the SQLite compatibility mapper.

        A fallback row is discarded only when the corresponding protocol has a
        successfully synchronized PostgreSQL relation snapshot.
        """
        if self.readFallbackMapper is None:
            return []

        creatorId = self._toOptionalInt(
            creatorId
        )

        parentId = self._toOptionalInt(
            parentId
        )

        childId = self._toOptionalInt(
            childId
        )

        if creatorObj is not None:
            rawRelations = (
                self.readFallbackMapper
                .getRelationsByCreator(
                    creatorObj
                )
            )

        elif relationName is not None:
            rawRelations = (
                self.readFallbackMapper
                .getRelationsByName(
                    relationName
                )
            )

        else:
            return []

        compatibleRelations = []

        synchronizationByCreator = dict(
            synchronizationByCreator
            or {}
        )

        for rawRelation in rawRelations or []:
            relation = dict(
                rawRelation
            )

            relationCreatorId = (
                self._toOptionalInt(
                    relation.get(
                        "parent_id"
                    )
                )
            )

            if (
                    relationCreatorId is None
                    and creatorId is not None
            ):
                relationCreatorId = (
                    creatorId
                )

                relation[
                    "parent_id"
                ] = creatorId

            if (
                    creatorId is not None
                    and relationCreatorId
                    != creatorId
            ):
                continue

            if (
                    relationName is not None
                    and str(
                        relation.get(
                            "name"
                        )
                        or ""
                    )
                    != str(
                        relationName
                    )
            ):
                continue

            relationParentId = (
                self._toOptionalInt(
                    relation.get(
                        "object_parent_id"
                    )
                )
            )

            if (
                    parentId is not None
                    and relationParentId
                    != parentId
            ):
                continue

            relationChildId = (
                self._toOptionalInt(
                    relation.get(
                        "object_child_id"
                    )
                )
            )

            if (
                    childId is not None
                    and relationChildId
                    != childId
            ):
                continue

            if relationCreatorId is not None:
                if (
                        relationCreatorId
                        not in synchronizationByCreator
                ):
                    synchronizationByCreator[
                        relationCreatorId
                    ] = (
                        self
                        ._isRelationSnapshotSynchronized(
                            relationCreatorId
                        )
                    )

                if synchronizationByCreator[
                        relationCreatorId
                ]:
                    continue

            compatibleRelations.append(
                relation
            )

        return compatibleRelations

    def getRelationsByCreator(
            self,
            creatorObj,
    ):
        creatorId = self._requireObjId(
            creatorObj
        )

        postgresqlRelations = (
            self._selectPostgresqlRelations(
                creatorId=creatorId,
            )
        )

        if self.readFallbackMapper is None:
            return postgresqlRelations

        snapshotSynchronized = (
            self
            ._isRelationSnapshotSynchronized(
                creatorId
            )
        )

        if snapshotSynchronized:
            return postgresqlRelations

        self._recordReadFallback(
            "getRelationsByCreator",
            creatorId=creatorId,
            reason=(
                "merge_unsynchronized_snapshot"
            ),
        )

        compatibilityRelations = (
            self
            ._selectCompatibilityRelationsFromReadFallback(
                creatorObj=creatorObj,
                creatorId=creatorId,
                synchronizationByCreator={
                    creatorId: False,
                },
            )
        )

        return self._mergeRuntimeRelationRows(
            postgresqlRelations,
            compatibilityRelations,
        )

    def getRelationsByName(
            self,
            relationName,
    ):
        postgresqlRelations = (
            self._selectPostgresqlRelations(
                relationName=relationName,
            )
        )

        compatibilityRelations = []

        if self.readFallbackMapper is not None:
            self._recordReadFallback(
                "getRelationsByName",
                relationName=relationName,
                reason=(
                    "merge_unsynchronized_snapshots"
                ),
            )

            compatibilityRelations = (
                self
                ._selectCompatibilityRelationsFromReadFallback(
                    relationName=relationName,
                )
            )

        return self._mergeRuntimeRelationRows(
            postgresqlRelations,
            compatibilityRelations,
        )

    def _selectRelationObjectById(
            self,
            objId,
    ):
        """
        Resolve one relation target without refreshing any owner protocol.
        """
        obj = (
            self
            ._selectProtocolByIdFromPostgresql(
                objId,
                refreshCached=False,
            )
        )

        if obj is not None:
            return obj

        obj = self._selectSetByIdFromPostgresql(
            objId,
            refreshParentProtocol=False,
        )

        if obj is not None:
            return obj

        obj = (
            self
            ._selectGenericObjectByIdFromPostgresql(
                objId
            )
        )

        if obj is not None:
            return obj

        return self._selectByIdFromReadFallback(
            objId,
            auditOperation=(
                "relationObject.selectById"
            ),
        )

    def getRelationChilds(
            self,
            relName,
            parentObj,
    ):
        parentId = self._requireObjId(
            parentObj
        )

        postgresqlRelations = (
            self._selectPostgresqlRelations(
                relationName=relName,
                parentId=parentId,
            )
        )

        compatibilityRelations = []

        if self.readFallbackMapper is not None:
            self._recordReadFallback(
                "getRelationChilds",
                relationName=relName,
                parentId=parentId,
                reason=(
                    "merge_unsynchronized_snapshots"
                ),
            )

            compatibilityRelations = (
                self
                ._selectCompatibilityRelationsFromReadFallback(
                    relationName=relName,
                    parentId=parentId,
                )
            )

        relations = self._mergeRuntimeRelationRows(
            postgresqlRelations,
            compatibilityRelations,
        )

        return [
            self._selectRelationObjectById(
                row[
                    "object_child_id"
                ]
            )
            for row in relations
        ]

    def getRelationParents(
            self,
            relName,
            childObj,
    ):
        childId = self._requireObjId(
            childObj
        )

        postgresqlRelations = (
            self._selectPostgresqlRelations(
                relationName=relName,
                childId=childId,
            )
        )

        compatibilityRelations = []

        if self.readFallbackMapper is not None:
            self._recordReadFallback(
                "getRelationParents",
                relationName=relName,
                childId=childId,
                reason=(
                    "merge_unsynchronized_snapshots"
                ),
            )

            compatibilityRelations = (
                self
                ._selectCompatibilityRelationsFromReadFallback(
                    relationName=relName,
                    childId=childId,
                )
            )

        relations = self._mergeRuntimeRelationRows(
            postgresqlRelations,
            compatibilityRelations,
        )

        return [
            self._selectRelationObjectById(
                row[
                    "object_parent_id"
                ]
            )
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

        if isinstance(
                obj,
                Protocol,
        ):
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

        if not callable(allocator):
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

    def _captureRuntimeObjectTreeIdentity(
            self,
            obj,
    ):
        snapshot = []
        visited = set()

        def visit(candidate):
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

            snapshot.append({
                "object": candidate,
                "objId": getattr(
                    candidate,
                    "_objId",
                    None,
                ),
                "objParentId": getattr(
                    candidate,
                    "_objParentId",
                    None,
                ),
                "objName": getattr(
                    candidate,
                    "_objName",
                    "",
                ),
            })

            attributesGetter = getattr(
                candidate,
                "getAttributesToStore",
                None,
            )

            if not callable(attributesGetter):
                return

            try:
                attributes = list(
                    attributesGetter()
                    or []
                )
            except Exception:
                return

            for _, child in attributes:
                visit(
                    child
                )

        visit(
            obj
        )

        return snapshot

    def _restoreRuntimeObjectTreeIdentity(
            self,
            snapshot,
    ) -> None:
        for item in reversed(
                snapshot
                or []
        ):
            candidate = item["object"]

            candidate._objId = item[
                "objId"
            ]

            candidate._objParentId = item[
                "objParentId"
            ]

            candidate._objName = item[
                "objName"
            ]

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