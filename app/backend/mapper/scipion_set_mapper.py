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
import logging

import psycopg2.extras

from pyworkflow.object import (
    Pointer,
    PointerList,
    Set as ScipionSet,
)

from app.backend.mapper.scipion_object_mapper import (
    ScipionObjectPostgresqlMapper,
)
from app.backend.runtime.postgresql_runtime_event_service import (
    PostgresqlRuntimeEventPublisher,
)

logger = logging.getLogger(__name__)

try:
    from tomo.constants import BOTTOM_LEFT_CORNER
except Exception:
    BOTTOM_LEFT_CORNER = None


SELF_LABEL = "self"
NESTED_LOGICAL_TABLES_VERSION = 18
SET_PROPERTIES_VERSION = 3


class ScipionSetPostgresqlMapper(ScipionObjectPostgresqlMapper):
    """Store Scipion SetOf... objects in PostgreSQL using a flat JSONB layout."""

    def serializeRuntimeItem(
            self,
            item: Any,
            scipionSet: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Serialize one native Scipion Set item using the
        same representation used by PostgreSQL snapshots.
        """
        itemId = self._getSourceObjId(
            item
        )

        if itemId is None:
            raise ValueError(
                "Runtime Set item must have "
                "a Scipion object id."
            )

        return {
            "scipionItemId": int(
                itemId
            ),
            "enabled": self._getItemEnabled(
                item
            ),
            "label": self._getObjectLabel(
                item
            ),
            "comment": self._getObjectComment(
                item
            ),
            "creation": self._getObjectCreation(
                item
            ),
            "values": self._getItemValues(
                item,
                scipionSet=scipionSet,
            ),
        }

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
            existingSetId = int(existingSet["id"])
            existingProperties = self._normalizeProperties(existingSet.get("properties"))
            if (
                    self.hasStoredSetTables(existingSetId)
                    and self._shouldSkipSetSync(existingProperties, itemsCountHint, maxItemIdHint, sourceMTime)
            ):
                skippedProperties = dict(existingProperties)
                skippedProperties["lastCheckedAt"] = syncTimestamp
                skippedProperties["lastSkipReason"] = "unchanged_signature"
                skippedProperties["skippedLastSync"] = True
                skippedProperties["incremental"] = True
                skippedProperties["nestedTablesVersion"] = NESTED_LOGICAL_TABLES_VERSION
                skippedProperties["setPropertiesVersion"] = SET_PROPERTIES_VERSION
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
        itemClassName = self._getItemClassName(firstItem, itemSchema, scipionSet=scipionSet,)
        columns = self._getSetColumns(itemSchema)
        initialProperties = self._getSetProperties(scipionSet)
        initialProperties["nestedTablesVersion"] = NESTED_LOGICAL_TABLES_VERSION
        initialProperties["setPropertiesVersion"] = SET_PROPERTIES_VERSION

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
                setClassName=(
                        self._getClassName(scipionSet)
                        or scipionSet.__class__.__name__
                ),
                itemClassName=itemClassName,
                properties=initialProperties,
            )

            staleObjectsDeleted = (
                self._deleteStaleObjectTreePaths(
                    projectId=projectId,
                    protocolDbId=protocolDbId,
                    outputName=outputName,
                    storedPaths=storedPaths,
                )
            )

            self._replaceStoredSetSnapshot(
                setId=setId,
            )

            self._upsertSetColumns(
                setId,
                columns,
            )

            rootTableId = self._upsertSetTable(
                setId=setId,
                name="objects",
                alias=self._getClassName(scipionSet) or outputName,
                tableKind="root",
                parentTableId=None,
                parentItemId=None,
                itemClassName=itemClassName,
                properties={
                    "source": "postgresql",
                    "legacySetTable": True,
                },
            )
            self._upsertSetTableColumns(rootTableId, columns)

            itemsCount = 0
            maxItemId = None
            if firstItem is not None:
                itemsCount, maxItemId = self._upsertSetItems(
                    setId=setId,
                    tableId=rootTableId,
                    firstItem=firstItem,
                    remainingItems=itemIterator,
                    batchSize=batchSize,
                    scipionSet=scipionSet,
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
            finalProperties["nestedTablesVersion"] = NESTED_LOGICAL_TABLES_VERSION
            if sourceMTime is not None:
                finalProperties["sourceMTime"] = sourceMTime
            self._updateSetProperties(setId, finalProperties)
            self._upsertSetProperties(setId, finalProperties)

        PostgresqlRuntimeEventPublisher.publish(
            db=self.db,
            projectId=projectId,
            eventType="set_updated",
            protocolDbId=protocolDbId,
            outputName=outputName,
            setId=setId,
            runtimeObjectId=rootObjectId,
            itemsCount=itemsCount,
            maxItemId=maxItemId,
        )

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
            "snapshotReplaced": existingSet is not None,
            "staleObjectsDeleted": staleObjectsDeleted,
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

    def deleteStoredSetOutput(
            self,
            projectId: int,
            setId: int,
            objectId: int,
            runtimeObjectId: int,
    ) -> Dict[str, int]:
        """
        Delete one complete PostgreSQL Set representation.

        The scipion_sets row is deleted first so all dependent Set tables
        disappear through their foreign-key cascades. The compatibility
        runtime relations and canonical scipion_objects root are then removed
        in the same transaction.
        """
        projectId = int(projectId)
        setId = int(setId)
        objectId = int(objectId)
        runtimeObjectId = int(runtimeObjectId)

        result = {
            "deletedSetsCount": 0,
            "deletedObjectsCount": 0,
            "deletedRelationsCount": 0,
        }

        with self.db.transaction():
            deletedSet = self.db.fetchOne(
                """
                DELETE FROM scipion_sets
                 WHERE id = %s
                   AND "projectId" = %s
                   AND "objectId" = %s
                RETURNING id, "objectId"
                """,
                (
                    setId,
                    projectId,
                    objectId,
                ),
            )

            if deletedSet is None:
                raise RuntimeError(
                    "Could not delete PostgreSQL Set %s "
                    "with canonical object %s."
                    % (
                        setId,
                        objectId,
                    )
                )

            result["deletedSetsCount"] = 1

            sharedSet = self.db.fetchOne(
                """
                SELECT id
                  FROM scipion_sets
                 WHERE "objectId" = %s
                 LIMIT 1
                """,
                (
                    objectId,
                ),
            )

            if sharedSet is not None:
                raise RuntimeError(
                    "Cannot delete PostgreSQL Set %s because "
                    "canonical object %s is still referenced "
                    "by Set %s."
                    % (
                        setId,
                        objectId,
                        sharedSet.get("id"),
                    )
                )

            relationsCursor = self.db.execute(
                """
                DELETE FROM scipion_relations
                 WHERE "projectId" = %s
                   AND (
                        "creatorObjId" = %s
                        OR "parentObjId" = %s
                        OR "childObjId" = %s
                   )
                """,
                (
                    projectId,
                    runtimeObjectId,
                    runtimeObjectId,
                    runtimeObjectId,
                ),
                commit=False,
            )

            result["deletedRelationsCount"] = int(
                relationsCursor.rowcount or 0
            )

            objectsCursor = self.db.execute(
                """
                DELETE FROM scipion_objects
                 WHERE id = %s
                   AND "projectId" = %s
                   AND "scipionObjId" = %s
                """,
                (
                    objectId,
                    projectId,
                    runtimeObjectId,
                ),
                commit=False,
            )

            result["deletedObjectsCount"] = int(
                objectsCursor.rowcount or 0
            )

            if result["deletedObjectsCount"] != 1:
                raise RuntimeError(
                    "Could not delete canonical PostgreSQL object %s "
                    "for runtime Set %s."
                    % (
                        objectId,
                        runtimeObjectId,
                    )
                )

        return result

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

    def _getDeclaredItemClassName(
            self,
            scipionSet: Any,
    ) -> Optional[str]:
        if scipionSet is None:
            return None

        itemType = getattr(
            scipionSet,
            "ITEM_TYPE",
            None,
        )

        if itemType is None:
            itemType = getattr(
                scipionSet.__class__,
                "ITEM_TYPE",
                None,
            )

        if isinstance(itemType, str):
            itemType = itemType.strip()
            return itemType or None

        className = getattr(
            itemType,
            "__name__",
            None,
        )

        if className:
            return str(className)

        return None

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

    def _replaceStoredSetSnapshot(
            self,
            setId: int,
    ) -> None:
        """
        Clear the dependent rows of an existing set before writing the current
        snapshot.

        The scipion_sets row and its id are preserved, while columns, items,
        properties and logical tables are rebuilt from the current Scipion set.
        """
        self.db.execute(
            """
            DELETE FROM scipion_set_tables
             WHERE "setId" = %s
            """,
            (setId,),
            commit=False,
        )

        self.db.execute(
            """
            DELETE FROM scipion_set_items
             WHERE "setId" = %s
            """,
            (setId,),
            commit=False,
        )

        self.db.execute(
            """
            DELETE FROM scipion_set_columns
             WHERE "setId" = %s
            """,
            (setId,),
            commit=False,
        )

        self.db.execute(
            """
            DELETE FROM scipion_set_properties
             WHERE "setId" = %s
            """,
            (setId,),
            commit=False,
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
            tableId: Optional[int],
            firstItem: Any,
            remainingItems: Iterator[Any],
            batchSize: int,
            scipionSet: Optional[Any] = None,
    ) -> Tuple[int, Optional[int]]:
        rows: List[Tuple[Any, ...]] = []
        tableRows: List[Tuple[Any, ...]] = []
        itemsCount = 0
        maxItemId: Optional[int] = None

        for item in self._chainFirst(firstItem, remainingItems):
            itemId = self._getSourceObjId(item)
            if itemId is None:
                raise ValueError("Cannot store a Scipion set item without getObjId()/getId()")

            maxItemId = itemId if maxItemId is None else max(maxItemId, itemId)
            itemValues = self._getItemValues(item, scipionSet=scipionSet)

            rows.append(
                (
                    setId,
                    itemId,
                    self._getItemEnabled(item),
                    self._getObjectLabel(item),
                    self._getObjectComment(item),
                    self._getObjectCreation(item),
                    self._jsonParam(itemValues),
                )
            )

            if tableId is not None:
                tableRows.append(
                    (
                        tableId,
                        itemId,
                        None,
                        self._getItemEnabled(item),
                        self._getObjectLabel(item),
                        self._getObjectComment(item),
                        self._getObjectCreation(item),
                        self._jsonParam(itemValues),
                    )
                )

                nestedTableId = (
                    self
                    ._upsertNestedLogicalTablesForItem(
                        setId=setId,
                        parentTableId=tableId,
                        parentItem=item,
                        parentItemId=itemId,
                        batchSize=batchSize,
                    )
                )

                if (
                        self
                                ._hasNestedLogicalItems(
                            item
                        )
                        and nestedTableId is None
                ):
                    raise RuntimeError(
                        "Nested PostgreSQL Set table "
                        "was not persisted. "
                        "setId=%s parentItemId=%s "
                        "parentClass=%s"
                        % (
                            setId,
                            itemId,
                            self._getClassName(
                                item
                            ),
                        )
                    )

            itemsCount += 1

            if len(rows) >= batchSize:
                self._flushSetItems(rows)
                rows = []

                if tableRows:
                    self._flushSetTableItems(tableRows)
                    tableRows = []

        if rows:
            self._flushSetItems(rows)

        if tableRows:
            self._flushSetTableItems(tableRows)

        return itemsCount, maxItemId

    def _upsertNestedLogicalTablesForItem(
            self,
            setId: int,
            parentTableId: int,
            parentItem: Any,
            parentItemId: int,
            batchSize: int,
    ) -> Optional[int]:
        """
        Persist the logical table owned by one nested Set item.

        Every nested Scipion Set must produce a PostgreSQL logical
        table, including empty sets.
        """
        if not self._hasNestedLogicalItems(
                parentItem
        ):
            return None

        childIterator = iter(
            self._iterNestedItems(
                parentItem
            )
        )

        firstChild = self._nextOrNone(
            childIterator
        )

        if firstChild is None:
            childSchema = {}
            childColumns = []

            childItemClassName = (
                self
                ._getDeclaredItemClassName(
                    parentItem
                )
            )

            if not childItemClassName:
                raise RuntimeError(
                    "Cannot persist empty nested "
                    "PostgreSQL Set without ITEM_TYPE. "
                    "setId=%s parentItemId=%s "
                    "parentClass=%s"
                    % (
                        setId,
                        parentItemId,
                        self._getClassName(
                            parentItem
                        ),
                    )
                )

        else:
            childSchema = self._getItemSchema(
                firstChild
            )

            childColumns = self._getSetColumns(
                childSchema
            )

            childItemClassName = (
                self._getItemClassName(
                    firstChild,
                    childSchema,
                    scipionSet=parentItem,
                )
            )

        tableName = (
            self._getNestedLogicalTableName(
                parentItem,
                parentItemId,
            )
        )

        tableAlias = (
            self._getNestedLogicalTableAlias(
                tableName,
                childItemClassName,
            )
        )

        childTableId = self._upsertSetTable(
            setId=setId,
            name=tableName,
            alias=tableAlias,
            tableKind="child",
            parentTableId=parentTableId,
            parentItemId=parentItemId,
            itemClassName=childItemClassName,
            properties={
                "source": "postgresql",
                "parentItemId": (
                    parentItemId
                ),
                "parentClassName": (
                    self._getClassName(
                        parentItem
                    )
                ),
            },
        )

        self._upsertSetTableColumns(
            childTableId,
            childColumns,
        )

        if firstChild is not None:
            self._upsertLogicalTableItems(
                tableId=childTableId,
                parentItemId=parentItemId,
                firstItem=firstChild,
                remainingItems=childIterator,
                batchSize=batchSize,
            )

        return int(
            childTableId
        )

    def _hasNestedLogicalItems(
            self,
            item: Any,
    ) -> bool:
        if item is None:
            return False

        if isinstance(
                item,
                ScipionSet,
        ):
            return True

        iterItems = getattr(
            item,
            "iterItems",
            None,
        )

        return callable(
            iterItems
        )

    def _iterNestedItems(self, item: Any) -> Iterable[Any]:
        iterItems = getattr(item, "iterItems", None)
        if callable(iterItems):
            try:
                return iterItems(iterate=False)
            except TypeError:
                return iterItems()

        return iter(())

    def _getNestedLogicalTableName(
            self,
            parentItem: Any,
            parentItemId: int,
    ) -> str:
        className = (
                self._getClassName(
                    parentItem
                )
                or parentItem.__class__.__name__
        )

        if str(className).startswith(
                "Class"
        ):
            return (
                self
                ._getNestedClassTableName(
                    parentItemId
                )
            )

        stableName = (
            self._getNestedItemStableName(
                parentItem=parentItem,
                parentItemId=parentItemId,
                className=className,
            )
        )

        cleanName = (
            self
            ._sanitizeLogicalTableNamePart(
                stableName
            )
        )

        try:
            itemIdText = str(
                int(parentItemId)
            )
        except Exception:
            itemIdText = (
                self
                ._sanitizeLogicalTableNamePart(
                    parentItemId
                )
            )

        if (
                cleanName != itemIdText
                and not cleanName.endswith(
            "_" + itemIdText
        )
        ):
            cleanName = "%s_%s" % (
                cleanName,
                itemIdText,
            )

        return "%s_Objects" % cleanName

    def _getNestedItemStableName(
            self,
            parentItem: Any,
            parentItemId: int,
            className: str,
    ) -> str:
        for getterName in ("getTsId", "getTomoId", "getObjLabel", "getName"):
            value = self._callOptionalGetter(parentItem, getterName)
            valueText = str(value or "").strip()
            if valueText:
                return valueText

        try:
            return "%s%03d" % (className or "Item", int(parentItemId))
        except Exception:
            return "%s%s" % (className or "Item", str(parentItemId))

    def _sanitizeLogicalTableNamePart(self, value: Any) -> str:
        text = str(value or "").strip()
        chars = []
        previousWasUnderscore = False

        for char in text:
            if char.isalnum():
                chars.append(char)
                previousWasUnderscore = False
                continue

            if char == "_" and not previousWasUnderscore:
                chars.append("_")
                previousWasUnderscore = True
                continue

            if not previousWasUnderscore:
                chars.append("_")
                previousWasUnderscore = True

        cleanText = "".join(chars).strip("_")
        return cleanText or "Item"

    def _getNestedClassTableName(self, parentItemId: int) -> str:
        try:
            return "Class%03d_Objects" % int(parentItemId)
        except Exception:
            return "Class%s_Objects" % str(parentItemId)

    def _getNestedLogicalTableAlias(self, tableName: str, childItemClassName: str) -> str:
        cleanClassName = str(childItemClassName or "Objects").strip() or "Objects"
        if tableName.endswith("_Objects"):
            return "%s_%s" % (tableName[: -len("_Objects")], cleanClassName)
        return "%s_%s" % (tableName, cleanClassName)

    def _upsertLogicalTableItems(
            self,
            tableId: int,
            parentItemId: Optional[int],
            firstItem: Any,
            remainingItems: Iterator[Any],
            batchSize: int,
    ) -> int:
        rows: List[Tuple[Any, ...]] = []
        itemsCount = 0

        for item in self._chainFirst(firstItem, remainingItems):
            itemId = self._getSourceObjId(item)
            if itemId is None:
                continue

            rows.append(
                (
                    tableId,
                    itemId,
                    parentItemId,
                    self._getItemEnabled(item),
                    self._getObjectLabel(item),
                    self._getObjectComment(item),
                    self._getObjectCreation(item),
                    self._jsonParam(self._getItemValues(item)),
                )
            )
            itemsCount += 1

            if len(rows) >= batchSize:
                self._flushSetTableItems(rows)
                rows = []

        if rows:
            self._flushSetTableItems(rows)

        return itemsCount

    def hasStoredSetTables(self, setId: int) -> bool:
        row = self.db.fetchOne(
            """
            SELECT id
              FROM scipion_set_tables
             WHERE "setId" = %s
             LIMIT 1
            """,
            (setId,),
        )
        return row is not None

    def listStoredSetTables(self, setId: int) -> List[Dict[str, Any]]:
        return self.db.fetchAll(
            """
            SELECT id, "setId", name, alias, "tableKind", "parentTableId",
                   "parentItemId", "itemClassName", properties, "createdAt", "updatedAt"
              FROM scipion_set_tables
             WHERE "setId" = %s
             ORDER BY
                   CASE WHEN "tableKind" = 'root' THEN 0 ELSE 1 END,
                   name ASC
            """,
            (setId,),
        )

    def getStoredSetTableColumns(self, tableId: int) -> List[Dict[str, Any]]:
        return self.db.fetchAll(
            """
            SELECT id, "tableId", "labelProperty", "columnName", "className",
                   "valueType", position, indexed, properties
              FROM scipion_set_table_columns
             WHERE "tableId" = %s
             ORDER BY position ASC
            """,
            (tableId,),
        )

    def getStoredSetTableItems(
        self,
        tableId: int,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        if limit is None:
            return self.db.fetchAll(
                """
                SELECT id, "tableId", "scipionItemId", "parentItemId", enabled,
                       label, comment, creation, "values", "createdAt", "updatedAt"
                  FROM scipion_set_table_items
                 WHERE "tableId" = %s
                 ORDER BY "scipionItemId" ASC
                """,
                (tableId,),
            )

        return self.db.fetchAll(
            """
            SELECT id, "tableId", "scipionItemId", "parentItemId", enabled,
                   label, comment, creation, "values", "createdAt", "updatedAt"
              FROM scipion_set_table_items
             WHERE "tableId" = %s
             ORDER BY "scipionItemId" ASC
             LIMIT %s OFFSET %s
            """,
            (tableId, limit, offset),
        )

    def _upsertSetTable(
        self,
        setId: int,
        name: str,
        alias: Optional[str],
        tableKind: str,
        parentTableId: Optional[int],
        parentItemId: Optional[int],
        itemClassName: Optional[str],
        properties: Optional[Dict[str, Any]] = None,
    ) -> int:
        cur = self.db.execute(
            """
            INSERT INTO scipion_set_tables (
                "setId", name, alias, "tableKind", "parentTableId",
                "parentItemId", "itemClassName", properties
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT ON CONSTRAINT ux_scipion_set_tables_set_name
            DO UPDATE SET
                alias = EXCLUDED.alias,
                "tableKind" = EXCLUDED."tableKind",
                "parentTableId" = EXCLUDED."parentTableId",
                "parentItemId" = EXCLUDED."parentItemId",
                "itemClassName" = EXCLUDED."itemClassName",
                properties = EXCLUDED.properties,
                "updatedAt" = NOW()
            RETURNING id
            """,
            (
                setId,
                name,
                alias,
                tableKind,
                parentTableId,
                parentItemId,
                itemClassName,
                self._jsonParam(properties or {}),
            ),
            commit=False,
        )
        return int(cur.fetchone()["id"])

    def _upsertSetTableColumns(self, tableId: int, columns: List[Dict[str, Any]]) -> None:
        for column in columns:
            self.db.execute(
                """
                INSERT INTO scipion_set_table_columns (
                    "tableId", "labelProperty", "columnName", "className",
                    "valueType", position, indexed, properties
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT ON CONSTRAINT ux_scipion_set_table_columns_table_label
                DO UPDATE SET
                    "columnName" = EXCLUDED."columnName",
                    "className" = EXCLUDED."className",
                    "valueType" = EXCLUDED."valueType",
                    position = EXCLUDED.position,
                    indexed = EXCLUDED.indexed,
                    properties = EXCLUDED.properties
                """,
                (
                    tableId,
                    column["labelProperty"],
                    column["columnName"],
                    column["className"],
                    column["valueType"],
                    column["position"],
                    column["indexed"],
                    self._jsonParam(column.get("properties") or {}),
                ),
                commit=False,
            )

    def _flushSetTableItems(self, rows: List[Tuple[Any, ...]]) -> None:
        psycopg2.extras.execute_values(
            self.db.cursor,
            """
            INSERT INTO scipion_set_table_items (
                "tableId", "scipionItemId", "parentItemId", enabled,
                label, comment, creation, "values"
            )
            VALUES %s
            ON CONFLICT ON CONSTRAINT ux_scipion_set_table_items_table_item
            DO UPDATE SET
                "parentItemId" = EXCLUDED."parentItemId",
                enabled = EXCLUDED.enabled,
                label = EXCLUDED.label,
                comment = EXCLUDED.comment,
                creation = EXCLUDED.creation,
                "values" = EXCLUDED."values",
                "updatedAt" = NOW()
            """,
            rows,
            template="(%s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
            page_size=len(rows),
        )

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

        storedNestedTablesVersion = self._toOptionalInt(
            existingProperties.get("nestedTablesVersion")
        )
        if storedNestedTablesVersion != NESTED_LOGICAL_TABLES_VERSION:
            return False

        storedSetPropertiesVersion = self._toOptionalInt(
            existingProperties.get("setPropertiesVersion")
        )

        if storedSetPropertiesVersion != SET_PROPERTIES_VERSION:
            return False

        if itemsCountHint is None:
            return False

        storedItemsCount = self._toOptionalInt(existingProperties.get("itemsCount"))
        if storedItemsCount != itemsCountHint:
            return False

        storedMaxItemId = self._toOptionalInt(existingProperties.get("maxItemId"))
        if maxItemIdHint is not None:
            if storedMaxItemId is None:
                return False
            if storedMaxItemId != maxItemIdHint:
                return False

        # itemsCount + maxItemId are only hints. They cannot detect changes
        # to item values, enabled flags, transforms, coordinates or metadata.
        #
        # Only skip when the set also provides a stable source-file mtime.
        if sourceMTime is None:
            return False

        storedSourceMTime = self._toOptionalFloat(
            existingProperties.get(
                "sourceMTime"
            )
        )

        if storedSourceMTime is None:
            return False

        if (
                abs(
                    storedSourceMTime
                    - sourceMTime
                )
                > 0.000001
        ):
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

    def _iterSetItems(
            self,
            scipionSet: Any,
    ) -> Iterable[Any]:
        iterItems = getattr(
            scipionSet,
            "iterItems",
            None,
        )

        if callable(iterItems):
            try:
                return iterItems(
                    iterate=False
                )
            except TypeError:
                return iterItems()

        try:
            return iter(
                scipionSet
            )
        except TypeError:
            raise ValueError(
                "scipionSet must provide "
                "iterItems() or be iterable"
            )

    def _getItemSchema(
            self,
            item: Any,
    ) -> Dict[str, Any]:
        schema = self._getObjDict(
            item,
            includeClass=True,
        )

        self._removeLegacyPointerListEntries(
            schema
        )

        for path, pointerAttribute in (
                self._iterPointerAttributes(
                    item
                )
        ):
            schema[str(path)] = (
                self._getClassName(
                    pointerAttribute
                ),
                None,
            )

        return schema

    def _getItemValues(
            self,
            item: Any,
            scipionSet: Optional[Any] = None,
    ) -> Dict[str, Any]:
        rawValues = self._getObjDict(
            item,
            includeClass=False,
        )

        self._removeLegacyPointerListEntries(
            rawValues
        )

        rawValues.update(
            self._getItemPointerValues(
                item
            )
        )

        values = {
            str(label): self._toJsonValue(value)
            for label, value in (rawValues or {}).items()
            if str(label) != SELF_LABEL
        }

        self._addRelationIdentityValues(
            item=item,
            values=values,
        )

        classSize = self._getClassItemSize(
            item
        )

        if (
                classSize is not None
                and "_size" not in values
        ):
            values["_size"] = classSize

        self._addCoordinate3dBottomLeftCoordinates(
            item=item,
            values=values,
            scipionSet=scipionSet,
        )

        return values

    def _iterPointerAttributes(
            self,
            scipionObj: Any,
            prefix: str = "",
            visited: Optional[set] = None,
    ):
        if scipionObj is None:
            return

        if visited is None:
            visited = set()

        objectIdentity = id(
            scipionObj
        )

        if objectIdentity in visited:
            return

        visited.add(
            objectIdentity
        )

        for attrName, attrValue in (
                self._getAttributesToStore(
                    scipionObj
                )
        ):
            path = (
                "%s.%s"
                % (
                    prefix,
                    attrName,
                )
                if prefix
                else str(attrName)
            )

            if isinstance(
                    attrValue,
                    Pointer,
            ):
                yield path, attrValue
                continue

            if isinstance(
                    attrValue,
                    PointerList,
            ):
                yield path, attrValue
                continue

            childAttributes = (
                self._getAttributesToStore(
                    attrValue
                )
            )

            if not childAttributes:
                continue

            yield from self._iterPointerAttributes(
                scipionObj=attrValue,
                prefix=path,
                visited=visited,
            )

    def _getItemPointerValues(
            self,
            item: Any,
    ) -> Dict[str, Any]:
        result = {}

        for path, pointerAttribute in (
                self._iterPointerAttributes(
                    item
                )
        ):
            if isinstance(
                    pointerAttribute,
                    PointerList,
            ):
                result[str(path)] = [
                    self._serializePointerReference(
                        pointer
                    )
                    for pointer in pointerAttribute
                    if isinstance(
                        pointer,
                        Pointer,
                    )
                ]

                continue

            result[str(path)] = (
                self._serializePointerReference(
                    pointerAttribute
                )
            )

        return result

    def _serializePointerReference(
            self,
            pointer: Pointer,
    ) -> Dict[str, Any]:
        targetObject = None

        try:
            if pointer.hasValue():
                targetObject = (
                    pointer.getObjValue()
                )
        except Exception:
            targetObject = None

        targetParent = self._callOptionalGetter(
            targetObject,
            "getObjParent",
        )

        if targetParent is None:
            targetParent = getattr(
                targetObject,
                "_objParent",
                None,
            )

        targetObjectId = self._getSourceObjId(
            targetObject
        )

        targetParentObjectId = (
            self._getSourceObjId(
                targetParent
            )
        )

        if targetParentObjectId is None:
            targetParentObjectId = (
                self._toOptionalInt(
                    self._callOptionalGetter(
                        targetObject,
                        "getObjParentId",
                    )
                )
            )

        extended = self._callOptionalGetter(
            pointer,
            "getExtended",
        )

        uniqueId = None

        try:
            if targetObject is not None:
                uniqueId = pointer.getUniqueId()
        except Exception:
            uniqueId = None

        targetObjectName = (
            self._callOptionalGetter(
                targetObject,
                "getObjName",
            )
        )

        return {
            "version": 1,
            "kind": "pointer",
            "targetObjectId": (
                targetObjectId
            ),
            "targetClassName": (
                self._getClassName(
                    targetObject
                )
                if targetObject is not None
                else None
            ),
            "targetObjectName": (
                str(targetObjectName)
                if targetObjectName
                else None
            ),
            "targetParentObjectId": (
                targetParentObjectId
            ),
            "targetParentClassName": (
                self._getClassName(
                    targetParent
                )
                if targetParent is not None
                else None
            ),
            "extended": str(
                extended or ""
            ),
            "uniqueId": (
                str(uniqueId)
                if uniqueId
                else None
            ),
        }

    def _removeLegacyPointerListEntries(
            self,
            values: Dict[str, Any],
    ) -> None:
        if not isinstance(
                values,
                dict,
        ):
            return

        for path in list(
                values.keys()
        ):
            if str(path).startswith(
                    "__item__"
            ):
                values.pop(
                    path,
                    None,
                )

    def _addRelationIdentityValues(
            self,
            item: Any,
            values: Dict[str, Any],
    ) -> None:
        tsId = self._getFirstGetterValue(
            item,
            ("getTsId", "getTiltSeriesId"),
        )
        if tsId is not None and not values.get("_tsId"):
            values["_tsId"] = self._toJsonValue(tsId)

        tomoId = self._getFirstGetterValue(
            item,
            ("getTomoId",),
        )
        if tomoId is not None and not values.get("_tomoId"):
            values["_tomoId"] = self._toJsonValue(tomoId)

    def _getFirstGetterValue(
            self,
            item: Any,
            getterNames: Tuple[str, ...],
    ) -> Optional[Any]:
        for getterName in getterNames:
            getter = getattr(item, getterName, None)
            if not callable(getter):
                continue

            try:
                value = getter()
            except Exception:
                continue

            getterValue = getattr(value, "get", None)
            if callable(getterValue):
                try:
                    value = getterValue()
                except Exception:
                    continue

            if value is None:
                continue

            text = str(value).strip()
            if text:
                return value

        return None

    def _getClassItemSize(self, item: Any) -> Optional[int]:
        className = self._getClassName(item) or item.__class__.__name__
        if not str(className or "").startswith("Class"):
            return None

        for methodName in ("getSize", "getObjSize", "count"):
            getter = getattr(item, methodName, None)
            if not callable(getter):
                continue

            try:
                value = getter()
            except Exception:
                continue

            sizeValue = self._toOptionalInt(value)
            if sizeValue is not None:
                return sizeValue

        try:
            return int(len(item))
        except Exception:
            return None

    def _addCoordinate3dBottomLeftCoordinates(
            self,
            item: Any,
            values: Dict[str, Any],
            scipionSet: Optional[Any] = None,
    ) -> None:
        coords = self._getCoordinate3dBottomLeftCoordinates(
            item=item,
            values=values,
            scipionSet=scipionSet,
        )
        if coords is None:
            return

        x, y, z = coords

        if "_x" in values and "rawX" not in values:
            values["rawX"] = values.get("_x")
        if "_y" in values and "rawY" not in values:
            values["rawY"] = values.get("_y")
        if "_z" in values and "rawZ" not in values:
            values["rawZ"] = values.get("_z")

        values["bottomLeftX"] = x
        values["bottomLeftY"] = y
        values["bottomLeftZ"] = z
        values["coordinateConvention"] = "BOTTOM_LEFT_CORNER"

    def _getCoordinate3dBottomLeftCoordinates(
            self,
            item: Any,
            values: Optional[Dict[str, Any]] = None,
            scipionSet: Optional[Any] = None,
    ) -> Optional[Tuple[float, float, float]]:
        if BOTTOM_LEFT_CORNER is None:
            return None

        self._attachCoordinate3dTomogram(
            item=item,
            values=values or {},
            scipionSet=scipionSet,
        )

        return self._readCoordinate3dBottomLeftCoordinates(item)

    def _readCoordinate3dBottomLeftCoordinates(self, item: Any) -> Optional[Tuple[float, float, float]]:
        getX = getattr(item, "getX", None)
        getY = getattr(item, "getY", None)
        getZ = getattr(item, "getZ", None)

        if not callable(getX) or not callable(getY) or not callable(getZ):
            return None

        try:
            return (
                float(getX(BOTTOM_LEFT_CORNER)),
                float(getY(BOTTOM_LEFT_CORNER)),
                float(getZ(BOTTOM_LEFT_CORNER)),
            )
        except Exception:
            return None

    def _attachCoordinate3dTomogram(
            self,
            item: Any,
            values: Dict[str, Any],
            scipionSet: Optional[Any],
    ) -> bool:
        if scipionSet is None:
            return False

        tomogram = self._resolveCoordinate3dTomogram(
            item=item,
            values=values,
            scipionSet=scipionSet,
        )
        if tomogram is None:
            return False

        setVolume = getattr(item, "setVolume", None)
        if callable(setVolume):
            try:
                setVolume(tomogram)
                return True
            except Exception:
                pass

        return False

    def _resolveCoordinate3dTomogram(
            self,
            item: Any,
            values: Dict[str, Any],
            scipionSet: Any,
    ) -> Optional[Any]:
        candidateKeys = self._getCoordinate3dTomogramCandidateKeys(item, values)
        if not candidateKeys:
            return None

        getTomogram = getattr(scipionSet, "_getTomogram", None)
        if callable(getTomogram):
            for key in candidateKeys:
                for candidate in self._expandTomogramLookupKey(key):
                    try:
                        tomogram = getTomogram(candidate)
                    except Exception:
                        tomogram = None

                    if tomogram is not None:
                        return tomogram

        for tomogram in self._iterLinkedTomograms(scipionSet):
            tomogramKeys = self._getTomogramObjectMatchKeys(tomogram)
            if tomogramKeys.intersection(candidateKeys):
                return tomogram

        return None

    def _getCoordinate3dTomogramCandidateKeys(
            self,
            item: Any,
            values: Dict[str, Any],
    ) -> set:
        candidates = []

        for keyName in (
            "_tomoId",
            "_volId",
            "_volumeId",
            "tomoId",
            "tomogramId",
            "volId",
            "volumeId",
            "tsId",
            "tiltSeriesId",
        ):
            value = self._getValueByNormalizedKey(values, keyName)
            text = self._toMatchText(value)
            if text:
                candidates.append(text)

        for getterName in ("getTomoId", "getVolId", "getVolumeId", "getTsId"):
            value = self._callOptionalGetter(item, getterName)
            text = self._toMatchText(value)
            if text:
                candidates.append(text)

        return {
            str(value)
            for value in candidates
            if value is not None and str(value).strip()
        }

    def _getTomogramObjectMatchKeys(self, tomogram: Any) -> set:
        candidates = []

        for getterName in ("getObjId", "getTsId", "getTomoId", "getNameId", "getObjLabel"):
            value = self._callOptionalGetter(tomogram, getterName)
            text = self._toMatchText(value)
            if text:
                candidates.append(text)

        return {
            str(value)
            for value in candidates
            if value is not None and str(value).strip()
        }

    def _expandTomogramLookupKey(self, key: Any) -> List[Any]:
        values = [key]

        intValue = self._toOptionalInt(key)
        if intValue is not None:
            values.append(intValue)

        return values

    def _getValueByNormalizedKey(self, values: Dict[str, Any], keyName: str) -> Any:
        targetKey = self._normalizeMatchKey(keyName)

        for key, value in values.items():
            if self._normalizeMatchKey(key) == targetKey:
                return value

        return None

    def _normalizeMatchKey(self, value: Any) -> str:
        return str(value).replace("_", "").replace(".", "").replace("-", "").lower()

    def _toMatchText(self, value: Any) -> Optional[str]:
        if value is None:
            return None

        getter = getattr(value, "get", None)
        if callable(getter):
            try:
                value = getter()
            except Exception:
                return None

        text = str(value).strip()
        return text or None

    def _callCoordinateGetter(self, item: Any, getterName: str) -> Optional[float]:
        getter = getattr(item, getterName, None)
        if not callable(getter):
            return None

        try:
            return float(getter(BOTTOM_LEFT_CORNER))
        except Exception:
            return None

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

        if self._schemaIsClassItem(itemSchema) and not any(
                column.get("labelProperty") == "_size"
                for column in columns
        ):
            columns.append(
                {
                    "labelProperty": "_size",
                    "columnName": "c%02d" % position,
                    "className": "Integer",
                    "valueType": "integer",
                    "position": position,
                    "indexed": True,
                }
            )

        return columns

    def _getItemClassName(
            self,
            item: Any,
            itemSchema: Dict[str, Any],
            scipionSet: Optional[Any] = None,
    ) -> str:
        selfSchema = itemSchema.get(
            SELF_LABEL
        )

        schemaClassName = self._getSchemaClassName(
            selfSchema
        )

        if schemaClassName:
            return schemaClassName

        if item is not None:
            return (
                    self._getClassName(item)
                    or item.__class__.__name__
            )

        return (
                self._getDeclaredItemClassName(
                    scipionSet
                )
                or "Unknown"
        )

    def _schemaIsClassItem(self, itemSchema: Dict[str, Any]) -> bool:
        selfSchema = itemSchema.get(SELF_LABEL)
        className = self._getSchemaClassName(selfSchema)
        return str(className or "").startswith("Class")

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
        if className in (
                "String",
                "CsvList",
        ):
            return "text"

        if className == "Pointer":
            return "pointer"

        if className == "PointerList":
            return "pointer_list"
        return className

    def _callOptionalBoolGetter(self, scipionObj: Any, getterName: str) -> Optional[bool]:
        getter = getattr(scipionObj, getterName, None)
        if not callable(getter):
            return None

        try:
            return bool(getter())
        except Exception:
            return None

    def _getTomoSetDisplayFlags(self, scipionSet: Any) -> Dict[str, Any]:
        """
        Store tomography display flags needed to reproduce Scipion output labels.

        Examples:
            SetOfTiltSeries (2 items, 41x400x356, +het, +ali, 10.00 Å/px)
            TiltSeries (..., +ali, ! interp, +ctf, +oe)
        """
        className = str(self._getClassName(scipionSet) or scipionSet.__class__.__name__ or "")
        normalizedClassName = className.replace("_", "").replace("-", "").lower()

        isTomoLike = (
                "tiltseries" in normalizedClassName
                or "tomogram" in normalizedClassName
                or "ctftomo" in normalizedClassName
        )

        if not isTomoLike:
            return {}

        flags: Dict[str, Any] = {}

        heterogeneous = self._callOptionalBoolGetter(scipionSet, "isHeterogeneousSet")
        if heterogeneous is not None:
            flags["isHeterogeneousSet"] = heterogeneous

        hasAlignment = self._callOptionalBoolGetter(scipionSet, "hasAlignment")
        if hasAlignment is not None:
            flags["hasAlignment"] = hasAlignment

        interpolated = self._callOptionalBoolGetter(scipionSet, "interpolated")
        if interpolated is not None:
            flags["interpolated"] = interpolated

        ctfCorrected = self._callOptionalBoolGetter(scipionSet, "ctfCorrected")
        if ctfCorrected is not None:
            flags["ctfCorrected"] = ctfCorrected

        hasOddEven = self._callOptionalBoolGetter(scipionSet, "hasOddEven")
        if hasOddEven is not None:
            flags["hasOddEven"] = hasOddEven

        if flags:
            flags["tomoDisplayFlagsVersion"] = 1

        return flags

    def _getSetProperties(self, scipionSet: Any) -> Dict[str, Any]:
        properties: Dict[str, Any] = {
            "className": self._getClassName(scipionSet),
            "moduleName": self._getModuleName(scipionSet),
            "baseClassName": self._getBaseClassName(scipionSet),
            "scipionObjId": self._getSourceObjId(scipionSet),
        }

        fileName = self._callOptionalGetter(
            scipionSet,
            "getFileName",
        )
        if fileName is not None:
            properties["fileName"] = self._toJsonValue(
                fileName
            )

        streamState = self._callOptionalGetter(
            scipionSet,
            "getStreamState",
        )
        if streamState is not None:
            properties["streamState"] = self._toJsonValue(
                streamState
            )

        linkedTomograms = self._getLinkedTomogramsSummary(
            scipionSet
        )
        if linkedTomograms:
            properties["linkedTomograms"] = linkedTomograms

        tomoDisplayFlags = self._getTomoSetDisplayFlags(
            scipionSet
        )
        if tomoDisplayFlags:
            properties.update(tomoDisplayFlags)

        setValues = self._getObjDict(
            scipionSet,
            includeClass=False,
        )

        self._removeLegacyPointerListEntries(
            setValues
        )

        setValues.update(
            self._getItemPointerValues(
                scipionSet
            )
        )

        for attrPath, value in setValues.items():
            attrPath = str(attrPath)

            if attrPath == SELF_LABEL:
                continue

            properties[attrPath] = self._toJsonValue(
                value
            )

        return {
            key: value
            for key, value in properties.items()
            if value is not None
        }

    def _getLinkedTomogramsSummary(self, scipionSet: Any) -> List[Dict[str, Any]]:
        tomograms = []

        for index, tomogram in enumerate(self._iterLinkedTomograms(scipionSet)):
            item = self._buildLinkedTomogramSummary(tomogram, index)
            if item is not None:
                tomograms.append(item)

        return tomograms

    def _iterLinkedTomograms(self, scipionSet: Any) -> Iterable[Any]:
        for methodName in ("iterTomograms", "iterVolumes"):
            iteratorGetter = getattr(scipionSet, methodName, None)
            if not callable(iteratorGetter):
                continue

            try:
                return iteratorGetter()
            except Exception:
                continue

        getTomograms = getattr(scipionSet, "getTomograms", None)
        if callable(getTomograms):
            try:
                tomograms = getTomograms()
                iterItems = getattr(tomograms, "iterItems", None)
                if callable(iterItems):
                    try:
                        return iterItems(iterate=False)
                    except TypeError:
                        return iterItems()
                return iter(tomograms)
            except Exception:
                pass

        return iter(())

    def _buildLinkedTomogramSummary(self, tomogram: Any, index: int) -> Optional[Dict[str, Any]]:
        objectId = self._callOptionalGetter(tomogram, "getObjId")
        tsId = self._callOptionalGetter(tomogram, "getTsId")
        tomoId = self._callOptionalGetter(tomogram, "getTomoId")

        stableId = tsId or tomoId or objectId or index
        if stableId is None:
            return None

        name = None
        for methodName in ("getObjLabel", "getNameId", "getFileName"):
            value = self._callOptionalGetter(tomogram, methodName)
            if value:
                name = value
                break

        if not name:
            name = stableId

        dims = self._normalizeLinkedTomogramDims(
            self._callOptionalGetter(tomogram, "getDim")
        )

        samplingRate = self._toOptionalFloat(
            self._callOptionalGetter(tomogram, "getSamplingRate")
        )

        item: Dict[str, Any] = {
            "id": str(stableId),
            "tomoId": str(stableId),
            "label": str(stableId),
            "name": str(name),
        }

        if objectId is not None:
            item["objectId"] = str(objectId)
            item["volumeId"] = str(objectId)

        if tsId is not None:
            item["tsId"] = str(tsId)
            item["tiltSeriesId"] = str(tsId)

        fileName = self._callOptionalGetter(tomogram, "getFileName")
        if fileName:
            item["fileName"] = str(fileName)

        if dims is not None:
            item["dims"] = dims

        if samplingRate is not None:
            item["voxelSize"] = [samplingRate, samplingRate, samplingRate]

        return item

    def _normalizeLinkedTomogramDims(self, dims: Any) -> Optional[List[int]]:
        if dims is None:
            return None

        try:
            values = list(dims)
        except Exception:
            return None

        if len(values) < 3:
            return None

        out = []
        for value in values[:3]:
            intValue = self._toOptionalInt(value)
            if intValue is None or intValue <= 0:
                return None
            out.append(intValue)

        return out

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