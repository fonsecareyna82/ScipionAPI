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
import json
from typing import Any, Dict, Iterable, List, Optional

from pyworkflow.mapper.mapper import Mapper
from pyworkflow.project.project import PROJECT_RUNS
from pyworkflow.protocol.protocol import Protocol
from pyworkflow.object import Object as ScipionObject
from pyworkflow.object import Set as ScipionSet
from pyworkflow.utils import joinExt, replaceExt
from pyworkflow.config import Config

from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.mapper.scipion_object_mapper import ScipionObjectPostgresqlMapper
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper

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

        self.objectMapper = ScipionObjectPostgresqlMapper(self.db)
        self.setMapper = ScipionSetPostgresqlMapper(self.db)

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
        # Do not close the shared PostgreSQL connection here. It belongs to the
        # request/session mapper lifecycle.
        if self.readFallbackMapper is not None:
            try:
                self.readFallbackMapper.close()
            except Exception:
                logger.debug("Could not close read fallback mapper.", exc_info=True)

    # ---------------------------------------------------------------------
    # Generic Mapper API
    # ---------------------------------------------------------------------

    def store(self, obj):
        if obj is None:
            return

        self._ensureObjId(obj)

        if self.writeFallbackMapper is not None:
            self.writeFallbackMapper.store(obj)

        if isinstance(obj, Protocol):
            self._storeProtocol(obj)
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

    def insert(self, obj):
        self._ensureObjId(obj)
        self.store(obj)

    def insertChild(self, obj, key, attr, namePrefix=None):
        """
        Insert/store a child object following the naming convention used by
        SqliteMapper.

        This is called by Protocol._insertChild when outputs or internal child
        attributes are registered.
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

        if self.writeFallbackMapper is not None:
            self.writeFallbackMapper.insertChild(obj, key, attr, namePrefix=namePrefix)

        self.store(attr)

    def updateTo(self, obj):
        self.store(obj)

    def updateFrom(self, obj):
        if self.readFallbackMapper is None:
            raise NotImplementedError(
                "PostgreSQL updateFrom is not implemented yet. "
                "Use readFallbackMapper during the migration phase."
            )
        return self.readFallbackMapper.updateFrom(obj)

    def selectById(self, objId):
        obj = self._selectByIdFromReadFallback(objId)
        if obj is not None:
            return self._attachRuntimeContext(obj)

        obj = self._selectProtocolByIdFromPostgresql(objId)
        if obj is not None:
            return self._attachRuntimeContext(obj)

        return None

    def _selectByIdFromReadFallback(self, objId):
        if self.readFallbackMapper is None:
            return None

        try:
            return self.readFallbackMapper.selectById(objId)
        except Exception:
            logger.debug(
                "Object %s was not found in read fallback mapper. Trying PostgreSQL.",
                objId,
                exc_info=True,
            )
            return None

    def _selectProtocolByIdFromPostgresql(self, objId):
        protocolId = self._toOptionalInt(objId)
        if protocolId is None:
            return None

        row = self.flatMapper.getProjectProtocolByProtocolId(
            self.projectId,
            protocolId,
        )

        if not row:
            return None

        return self._buildProtocolFromPostgresqlRow(row)

    def exists(self, objId):
        row = self.db.fetchOne(
            """
            SELECT id
              FROM protocols
             WHERE "projectId" = %s
               AND "protocolId" = %s
             LIMIT 1
            """,
            (self.projectId, str(objId)),
        )
        if row is not None:
            return True

        if self.readFallbackMapper is not None:
            return self.readFallbackMapper.exists(objId)

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
            return None

        protocolClass = self._resolveProtocolClass(protocolClassName)
        if protocolClass is None:
            logger.warning(
                "Cannot build protocol from PostgreSQL: protocol class not found. "
                "projectId=%s protocolId=%s protocolClassName=%s",
                self.projectId,
                row.get("protocolId"),
                protocolClassName,
            )
            return None

        protocol = self._instantiateProtocol(protocolClass)

        protocolId = self._toOptionalInt(row.get("protocolId"))
        if protocolId is not None:
            self._setObjId(protocol, protocolId)

        self._attachRuntimeContext(protocol)
        self._applyStoredProtocolParams(protocol, row.get("params") or {})
        self._ensureProtocolWorkingDir(protocol)

        return protocol

    def selectAllBatch(self, objectFilter=None):
        if self.readFallbackMapper is None:
            raise NotImplementedError(
                "PostgreSQL selectAllBatch is not implemented yet."
            )

        result = self.readFallbackMapper.selectAllBatch(
            objectFilter=objectFilter,
        )
        return self._attachRuntimeContextList(result)

    def selectBy(self, iterate=False, objectFilter=None, **args):
        if self.readFallbackMapper is None:
            raise NotImplementedError(
                "PostgreSQL selectBy is not implemented yet."
            )

        result = self.readFallbackMapper.selectBy(
            iterate=iterate,
            objectFilter=objectFilter,
            **args,
        )

        if iterate:
            return self._attachRuntimeContextIterator(result)

        return self._attachRuntimeContextList(result)

    def selectByClass(
            self,
            className,
            includeSubclasses=True,
            iterate=False,
            objectFilter=None,
    ):
        if self.readFallbackMapper is None:
            raise NotImplementedError(
                "PostgreSQL selectByClass is not implemented yet."
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

    def getParent(self, obj):
        if self.readFallbackMapper is not None:
            parent = self.readFallbackMapper.getParent(obj)
            self._attachRuntimeContext(parent)
            return parent

        parentId = getattr(obj, "_objParentId", None)
        if parentId is None:
            return None

        return self.selectById(parentId)

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
            return self.writeFallbackMapper.insertRelation(
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

    def getRelationsByCreator(self, creatorObj):
        if self.readFallbackMapper is not None:
            return self.readFallbackMapper.getRelationsByCreator(creatorObj)

        creatorId = self._requireObjId(creatorObj)
        return self.db.fetchAll(
            """
            SELECT *
              FROM scipion_relations
             WHERE "projectId" = %s
               AND "creatorObjId" = %s
             ORDER BY id ASC
            """,
            (self.projectId, int(creatorId)),
        )

    def getRelationsByName(self, relationName):
        if self.readFallbackMapper is not None:
            return self.readFallbackMapper.getRelationsByName(relationName)

        return self.db.fetchAll(
            """
            SELECT *
              FROM scipion_relations
             WHERE "projectId" = %s
               AND name = %s
             ORDER BY id ASC
            """,
            (self.projectId, str(relationName)),
        )

    def getRelationChilds(self, relName, parentObj):
        if self.readFallbackMapper is not None:
            return self.readFallbackMapper.getRelationChilds(relName, parentObj)

        raise NotImplementedError(
            "PostgreSQL getRelationChilds object reconstruction is not implemented yet."
        )

    def getRelationParents(self, relName, childObj):
        if self.readFallbackMapper is not None:
            return self.readFallbackMapper.getRelationParents(relName, childObj)

        raise NotImplementedError(
            "PostgreSQL getRelationParents object reconstruction is not implemented yet."
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

    def _instantiateProtocol(self, protocolClass):
        if self.project is not None:
            try:
                return protocolClass(project=self.project)
            except TypeError:
                pass

        return protocolClass()

    def _toOptionalInt(self, value):
        if value in (None, ""):
            return None

        try:
            return int(value)
        except Exception:
            return None

    def _instantiateProtocol(self, protocolClass):
        if self.project is not None:
            try:
                return protocolClass(project=self.project)
            except TypeError:
                pass

        try:
            return protocolClass()
        except TypeError:
            return protocolClass(project=self.project)

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