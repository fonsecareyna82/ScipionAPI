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
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

import psycopg2.extras

from app.backend.mapper.scipion_object_mapper import ScipionObjectPostgresqlMapper


SELF_LABEL = "self"


class ScipionSetPostgresqlMapper(ScipionObjectPostgresqlMapper):
    """Store Scipion SetOf... objects in PostgreSQL using a flat JSONB layout."""

    def storeSet(
        self,
        projectId: int,
        protocolDbId: int,
        outputName: str,
        scipionSet: Any,
        registerType: bool = True,
        batchSize: int = 1000,
    ) -> Dict[str, Any]:
        if not projectId:
            raise ValueError("projectId is required")
        if not protocolDbId:
            raise ValueError("protocolDbId is required")
        if not outputName:
            raise ValueError("outputName is required")
        if batchSize <= 0:
            raise ValueError("batchSize must be greater than zero")

        protocolDbId = self._resolveProtocolDbId(projectId, protocolDbId)
        syncTimestamp = datetime.now(timezone.utc).isoformat()
        itemsCountHint = self._getSetItemsCountHint(scipionSet)
        maxItemIdHint = self._getSetMaxItemIdHint(scipionSet)
        sourceMTime = self._getSetSourceMTime(scipionSet)
        existingSet = self._getExistingSet(projectId, protocolDbId, outputName)

        if existingSet is not None:
            existingProperties = self._normalizeProperties(existingSet.get("properties"))
            if self._shouldSkipSetSync(existingProperties, itemsCountHint, maxItemIdHint, sourceMTime):
                skippedProperties = dict(existingProperties)
                skippedProperties["lastCheckedAt"] = syncTimestamp
                skippedProperties["lastSkipReason"] = "unchanged_signature"
                skippedProperties["skippedLastSync"] = True
                skippedProperties["incremental"] = True
                if sourceMTime is not None:
                    skippedProperties["sourceMTime"] = sourceMTime

                with self.db.transaction():
                    self._updateSetProperties(int(existingSet["id"]), skippedProperties)
                    self._upsertSetProperties(int(existingSet["id"]), skippedProperties)

                return {
                    "setId": int(existingSet["id"]),
                    "rootObjectId": existingSet.get("objectId"),
                    "projectId": projectId,
                    "protocolDbId": protocolDbId,
                    "outputName": outputName,
                    "setClassName": existingSet.get("setClassName"),
                    "itemClassName": existingSet.get("itemClassName"),
                    "columnsCount": self._toOptionalInt(existingProperties.get("columnsCount")),
                    "itemsCount": self._toOptionalInt(existingProperties.get("itemsCount")),
                    "maxItemId": self._toOptionalInt(existingProperties.get("maxItemId")),
                    "lastSyncAt": existingProperties.get("lastSyncAt"),
                    "lastCheckedAt": syncTimestamp,
                    "skipped": True,
                }

        if registerType:
            self.registerObjectTypeFromObject(
                scipionSet,
                mapperKind="flat_set",
                includeProperties=False,
                classSchema={"storage": "flat_set"},
            )

        itemIterator = iter(self._iterSetItems(scipionSet))
        firstItem = self._nextOrNone(itemIterator)
        itemSchema = self._getItemSchema(firstItem) if firstItem is not None else {}
        itemClassName = self._getItemClassName(firstItem, itemSchema)
        columns = self._getSetColumns(itemSchema)
        initialProperties = self._getSetProperties(scipionSet)

        storedPaths: List[str] = []
        with self.db.transaction():
            rootObjectId = self._storeObjectNode(
                projectId=projectId,
                protocolDbId=protocolDbId,
                scipionObj=scipionSet,
                name=outputName,
                path=outputName,
                parentObjectId=None,
                storedPaths=storedPaths,
                includeNestedProperties=False,
                visited=set(),
            )

            setId = self._upsertSet(
                projectId=projectId,
                protocolDbId=protocolDbId,
                objectId=rootObjectId,
                outputName=outputName,
                setClassName=self._getClassName(scipionSet) or scipionSet.__class__.__name__,
                itemClassName=itemClassName,
                properties=initialProperties,
            )
            self._upsertSetColumns(setId, columns)

            itemsCount = 0
            maxItemId = None
            if firstItem is not None:
                itemsCount, maxItemId = self._upsertSetItems(
                    setId=setId,
                    firstItem=firstItem,
                    remainingItems=itemIterator,
                    batchSize=batchSize,
                )

            finalProperties = dict(initialProperties)
            finalProperties["columnsCount"] = len(columns)
            finalProperties["itemsCount"] = itemsCount
            finalProperties["maxItemId"] = maxItemId
            finalProperties["lastSyncAt"] = syncTimestamp
            finalProperties["lastCheckedAt"] = syncTimestamp
            finalProperties["lastSkipReason"] = None
            finalProperties["skippedLastSync"] = False
            finalProperties["incremental"] = True
            if sourceMTime is not None:
                finalProperties["sourceMTime"] = sourceMTime
            self._updateSetProperties(setId, finalProperties)
            self._upsertSetProperties(setId, finalProperties)

        return {
            "setId": setId,
            "rootObjectId": rootObjectId,
            "projectId": projectId,
            "protocolDbId": protocolDbId,
            "outputName": outputName,
            "setClassName": self._getClassName(scipionSet),
            "itemClassName": itemClassName,
            "columnsCount": len(columns),
            "itemsCount": itemsCount,
            "maxItemId": maxItemId,
            "lastSyncAt": syncTimestamp,
            "lastCheckedAt": syncTimestamp,
            "skipped": False,
        }

    def getStoredSet(
        self,
        projectId: int,
        protocolDbId: int,
        outputName: str,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> Optional[Dict[str, Any]]:
        protocolDbId = self._resolveProtocolDbId(projectId, protocolDbId)

        storedSet = self.db.fetchOne(
            """
            SELECT id, "projectId", "protocolDbId", "objectId", "outputName",
                   "setClassName", "itemClassName", properties, "createdAt", "updatedAt"
              FROM scipion_sets
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
               AND "outputName" = %s
            """,
            (projectId, protocolDbId, outputName),
        )
        if storedSet is None:
            return None

        storedSet["columns"] = self.getStoredSetColumns(storedSet["id"])
        storedSet["setProperties"] = self.getStoredSetProperties(storedSet["id"])
        storedSet["items"] = self.getStoredSetItems(storedSet["id"], limit=limit, offset=offset)
        return storedSet

    def listProtocolStoredSets(self, projectId: int, protocolDbId: int) -> List[Dict[str, Any]]:
        protocolDbId = self._resolveProtocolDbId(projectId, protocolDbId)

        return self.db.fetchAll(
            """
            SELECT id, "projectId", "protocolDbId", "objectId", "outputName",
                   "setClassName", "itemClassName", properties, "createdAt", "updatedAt"
              FROM scipion_sets
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
             ORDER BY "outputName" ASC
            """,
            (projectId, protocolDbId),
        )

    def getStoredSetColumns(self, setId: int) -> List[Dict[str, Any]]:
        return self.db.fetchAll(
            """
            SELECT id, "setId", "labelProperty", "columnName", "className",
                   "valueType", position, indexed
              FROM scipion_set_columns
             WHERE "setId" = %s
             ORDER BY position ASC
            """,
            (setId,),
        )

    def getStoredSetProperties(self, setId: int) -> List[Dict[str, Any]]:
        return self.db.fetchAll(
            """
            SELECT id, "setId", key, value
              FROM scipion_set_properties
             WHERE "setId" = %s
             ORDER BY key ASC
            """,
            (setId,),
        )

    def getStoredSetItems(self, setId: int, limit: Optional[int] = None, offset: int = 0) -> List[Dict[str, Any]]:
        if limit is None:
            return self.db.fetchAll(
                """
                SELECT id, "setId", "scipionItemId", enabled, label, comment,
                       creation, "values", "createdAt", "updatedAt"
                  FROM scipion_set_items
                 WHERE "setId" = %s
                 ORDER BY "scipionItemId" ASC
                """,
                (setId,),
            )

        return self.db.fetchAll(
            """
            SELECT id, "setId", "scipionItemId", enabled, label, comment,
                   creation, "values", "createdAt", "updatedAt"
              FROM scipion_set_items
             WHERE "setId" = %s
             ORDER BY "scipionItemId" ASC
             LIMIT %s OFFSET %s
            """,
            (setId, limit, offset),
        )

    def _resolveProtocolDbId(self, projectId: int, protocolDbId: int) -> int:
        byDatabaseId = self.db.fetchOne(
            """
            SELECT id
              FROM protocols
             WHERE id = %s
               AND "projectId" = %s
            """,
            (protocolDbId, projectId),
        )
        if byDatabaseId is not None:
            return int(byDatabaseId["id"])

        byScipionId = self.db.fetchOne(
            """
            SELECT id
              FROM protocols
             WHERE "projectId" = %s
               AND "protocolId" = %s
            """,
            (projectId, str(protocolDbId)),
        )
        if byScipionId is not None:
            return int(byScipionId["id"])

        raise ValueError(
            "Protocol %s was not found in PostgreSQL protocols table for project %s"
            % (protocolDbId, projectId)
        )

    def _getExistingSet(self, projectId: int, protocolDbId: int, outputName: str) -> Optional[Dict[str, Any]]:
        return self.db.fetchOne(
            """
            SELECT id, "objectId", "setClassName", "itemClassName", properties
              FROM scipion_sets
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
               AND "outputName" = %s
            """,
            (projectId, protocolDbId, outputName),
        )

    def _upsertSet(
        self,
        projectId: int,
        protocolDbId: int,
        objectId: int,
        outputName: str,
        setClassName: str,
        itemClassName: str,
        properties: Dict[str, Any],
    ) -> int:
        cur = self.db.execute(
            """
            INSERT INTO scipion_sets (
                "projectId", "protocolDbId", "objectId", "outputName",
                "setClassName", "itemClassName", properties
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT ON CONSTRAINT ux_scipion_sets_project_protocol_output
            DO UPDATE SET
                "objectId" = EXCLUDED."objectId",
                "setClassName" = EXCLUDED."setClassName",
                "itemClassName" = EXCLUDED."itemClassName",
                properties = EXCLUDED.properties,
                "updatedAt" = NOW()
            RETURNING id
            """,
            (
                projectId,
                protocolDbId,
                objectId,
                outputName,
                setClassName,
                itemClassName,
                self._jsonParam(properties),
            ),
            commit=False,
        )
        return int(cur.fetchone()["id"])

    def _upsertSetColumns(self, setId: int, columns: List[Dict[str, Any]]) -> None:
        for column in columns:
            self.db.execute(
                """
                INSERT INTO scipion_set_columns (
                    "setId", "labelProperty", "columnName", "className", "valueType", position, indexed
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT ON CONSTRAINT ux_scipion_set_columns_set_label
                DO UPDATE SET
                    "columnName" = EXCLUDED."columnName",
                    "className" = EXCLUDED."className",
                    "valueType" = EXCLUDED."valueType",
                    position = EXCLUDED.position,
                    indexed = EXCLUDED.indexed
                """,
                (
                    setId,
                    column["labelProperty"],
                    column["columnName"],
                    column["className"],
                    column["valueType"],
                    column["position"],
                    column["indexed"],
                ),
                commit=False,
            )

    def _upsertSetProperties(self, setId: int, properties: Dict[str, Any]) -> None:
        for key, value in sorted(properties.items()):
            self.db.execute(
                """
                INSERT INTO scipion_set_properties ("setId", key, value)
                VALUES (%s, %s, %s)
                ON CONFLICT ON CONSTRAINT ux_scipion_set_properties_set_key
                DO UPDATE SET
                    value = EXCLUDED.value
                """,
                (setId, str(key), self._stringifyPropertyValue(value)),
                commit=False,
            )

    def _upsertSetItems(
        self,
        setId: int,
        firstItem: Any,
        remainingItems: Iterator[Any],
        batchSize: int,
    ) -> Tuple[int, Optional[int]]:
        rows: List[Tuple[Any, ...]] = []
        itemsCount = 0
        maxItemId: Optional[int] = None

        for item in self._chainFirst(firstItem, remainingItems):
            itemId = self._getSourceObjId(item)
            if itemId is None:
                raise ValueError("Cannot store a Scipion set item without getObjId()/getId()")

            maxItemId = itemId if maxItemId is None else max(maxItemId, itemId)
            rows.append(
                (
                    setId,
                    itemId,
                    self._getItemEnabled(item),
                    self._getObjectLabel(item),
                    self._getObjectComment(item),
                    self._getObjectCreation(item),
                    self._jsonParam(self._getItemValues(item)),
                )
            )
            itemsCount += 1

            if len(rows) >= batchSize:
                self._flushSetItems(rows)
                rows = []

        if rows:
            self._flushSetItems(rows)

        return itemsCount, maxItemId

    def _flushSetItems(self, rows: List[Tuple[Any, ...]]) -> None:
        psycopg2.extras.execute_values(
            self.db.cursor,
            """
            INSERT INTO scipion_set_items (
                "setId", "scipionItemId", enabled, label, comment, creation, "values"
            )
            VALUES %s
            ON CONFLICT ON CONSTRAINT ux_scipion_set_items_set_item
            DO UPDATE SET
                enabled = EXCLUDED.enabled,
                label = EXCLUDED.label,
                comment = EXCLUDED.comment,
                creation = EXCLUDED.creation,
                "values" = EXCLUDED."values",
                "updatedAt" = NOW()
            """,
            rows,
            template="(%s, %s, %s, %s, %s, %s, %s::jsonb)",
            page_size=len(rows),
        )

    def _updateSetProperties(self, setId: int, properties: Dict[str, Any]) -> None:
        self.db.execute(
            """
            UPDATE scipion_sets
               SET properties = %s::jsonb,
                   "updatedAt" = NOW()
             WHERE id = %s
            """,
            (self._jsonParam(properties), setId),
            commit=False,
        )

    def _shouldSkipSetSync(
        self,
        existingProperties: Dict[str, Any],
        itemsCountHint: Optional[int],
        maxItemIdHint: Optional[int],
        sourceMTime: Optional[float],
    ) -> bool:
        if not existingProperties or not existingProperties.get("incremental"):
            return False

        if itemsCountHint is None:
            return False

        storedItemsCount = self._toOptionalInt(existingProperties.get("itemsCount"))
        if storedItemsCount != itemsCountHint:
            return False

        storedMaxItemId = self._toOptionalInt(existingProperties.get("maxItemId"))
        if maxItemIdHint is not None and storedMaxItemId is not None and storedMaxItemId != maxItemIdHint:
            return False

        storedSourceMTime = self._toOptionalFloat(existingProperties.get("sourceMTime"))
        if sourceMTime is not None and storedSourceMTime is not None and abs(storedSourceMTime - sourceMTime) > 0.000001:
            return False

        return True

    def _getSetItemsCountHint(self, scipionSet: Any) -> Optional[int]:
        for methodName in ("getSize", "count"):
            getter = getattr(scipionSet, methodName, None)
            if not callable(getter):
                continue
            try:
                value = getter()
            except Exception:
                continue
            countValue = self._toOptionalInt(value)
            if countValue is not None:
                return countValue

        try:
            return int(len(scipionSet))
        except Exception:
            return None

    def _getSetMaxItemIdHint(self, scipionSet: Any) -> Optional[int]:
        for methodName in ("getMaxId", "maxId", "getLastId"):
            getter = getattr(scipionSet, methodName, None)
            if not callable(getter):
                continue
            try:
                value = getter()
            except Exception:
                continue
            maxValue = self._toOptionalInt(value)
            if maxValue is not None:
                return maxValue

        getter = getattr(scipionSet, "getLastItem", None)
        if callable(getter):
            try:
                return self._getSourceObjId(getter())
            except Exception:
                return None

        return None

    def _getSetSourceMTime(self, scipionSet: Any) -> Optional[float]:
        fileName = self._callOptionalGetter(scipionSet, "getFileName")
        if not fileName:
            return None

        try:
            filePath = str(fileName)
            if not os.path.exists(filePath):
                return None
            return float(os.path.getmtime(filePath))
        except Exception:
            return None

    def _normalizeProperties(self, properties: Any) -> Dict[str, Any]:
        if isinstance(properties, dict):
            return dict(properties)
        if isinstance(properties, str):
            try:
                parsed = json.loads(properties)
                return dict(parsed) if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}

    def _toOptionalInt(self, value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except Exception:
            return None

    def _toOptionalFloat(self, value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except Exception:
            return None

    def _iterSetItems(self, scipionSet: Any) -> Iterable[Any]:
        iterItems = getattr(scipionSet, "iterItems", None)
        if callable(iterItems):
            return iterItems()

        try:
            return iter(scipionSet)
        except TypeError:
            raise ValueError("scipionSet must provide iterItems() or be iterable")

    def _getItemSchema(self, item: Any) -> Dict[str, Any]:
        return self._getObjDict(item, includeClass=True)

    def _getItemValues(self, item: Any) -> Dict[str, Any]:
        values = self._getObjDict(item, includeClass=False)
        if not values:
            return {}

        return {
            str(label): self._toJsonValue(value)
            for label, value in values.items()
            if str(label) != SELF_LABEL
        }

    def _getObjDict(self, scipionObj: Any, includeClass: bool) -> Dict[str, Any]:
        getter = getattr(scipionObj, "getObjDict", None)
        if not callable(getter):
            return {}

        try:
            return dict(getter(includeClass=includeClass) or {})
        except TypeError:
            try:
                return dict(getter(includeClass) or {})
            except TypeError:
                if includeClass:
                    return {}
                return dict(getter() or {})
        except Exception:
            return {}

    def _getSetColumns(self, itemSchema: Dict[str, Any]) -> List[Dict[str, Any]]:
        columns = []
        position = 0

        for label, rawValue in itemSchema.items():
            labelProperty = str(label)
            if labelProperty == SELF_LABEL:
                continue

            className = self._getSchemaClassName(rawValue)
            columns.append(
                {
                    "labelProperty": labelProperty,
                    "columnName": "c%02d" % position,
                    "className": className,
                    "valueType": self._getColumnValueType(className),
                    "position": position,
                    "indexed": False,
                }
            )
            position += 1

        return columns

    def _getItemClassName(self, item: Any, itemSchema: Dict[str, Any]) -> str:
        selfSchema = itemSchema.get(SELF_LABEL)
        schemaClassName = self._getSchemaClassName(selfSchema)
        if schemaClassName:
            return schemaClassName
        return self._getClassName(item) or item.__class__.__name__ if item is not None else "Unknown"

    def _getSchemaClassName(self, schemaValue: Any) -> Optional[str]:
        if isinstance(schemaValue, (tuple, list)) and schemaValue:
            return str(schemaValue[0]) if schemaValue[0] else None
        if isinstance(schemaValue, dict):
            className = schemaValue.get("className") or schemaValue.get("class_name")
            return str(className) if className else None
        return None

    def _getColumnValueType(self, className: Optional[str]) -> Optional[str]:
        if className in ("Integer", "Long", "Boolean"):
            return "integer"
        if className in ("Float", "Decimal"):
            return "float"
        if className in ("String", "CsvList", "Pointer", "PointerList"):
            return "text"
        return className

    def _getSetProperties(self, scipionSet: Any) -> Dict[str, Any]:
        properties: Dict[str, Any] = {
            "className": self._getClassName(scipionSet),
            "moduleName": self._getModuleName(scipionSet),
            "baseClassName": self._getBaseClassName(scipionSet),
            "scipionObjId": self._getSourceObjId(scipionSet),
        }

        fileName = self._callOptionalGetter(scipionSet, "getFileName")
        if fileName is not None:
            properties["fileName"] = self._toJsonValue(fileName)

        streamState = self._callOptionalGetter(scipionSet, "getStreamState")
        if streamState is not None:
            properties["streamState"] = self._toJsonValue(streamState)

        for attrName, attrValue in self._getAttributesToStore(scipionSet):
            if self._getAttributesToStore(attrValue):
                continue
            properties[str(attrName)] = self._toJsonValue(self._getObjectValueText(attrValue))

        return {key: value for key, value in properties.items() if value is not None}

    def _getItemEnabled(self, item: Any) -> bool:
        isEnabled = getattr(item, "isEnabled", None)
        if not callable(isEnabled):
            return True
        try:
            return bool(isEnabled())
        except Exception:
            return True

    def _callOptionalGetter(self, scipionObj: Any, getterName: str) -> Any:
        getter = getattr(scipionObj, getterName, None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception:
            return None

    def _toJsonValue(self, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, (list, tuple)):
            return [self._toJsonValue(item) for item in value]
        if isinstance(value, dict):
            return {str(key): self._toJsonValue(item) for key, item in value.items()}

        isoformat = getattr(value, "isoformat", None)
        if callable(isoformat):
            try:
                return isoformat()
            except Exception:
                pass

        getter = getattr(value, "getObjValue", None)
        if callable(getter):
            try:
                return self._toJsonValue(getter())
            except Exception:
                pass

        getter = getattr(value, "get", None)
        if callable(getter):
            try:
                return self._toJsonValue(getter())
            except Exception:
                pass

        return str(value)

    def _stringifyPropertyValue(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(self._toJsonValue(value), ensure_ascii=False)
        return str(value)

    def _nextOrNone(self, iterator: Iterator[Any]) -> Any:
        try:
            return next(iterator)
        except StopIteration:
            return None

    def _chainFirst(self, firstItem: Any, remainingItems: Iterator[Any]) -> Iterator[Any]:
        yield firstItem
        for item in remainingItems:
            yield item
