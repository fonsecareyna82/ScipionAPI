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

POSTGRESQL_RUNTIME_STORAGE_PROPERTY_KEYS = (
    "fileName",
    "_mapperPath",
    "materializedFileName",
)

RELATION_IDENTITY_FIELDS = (
    (
        "_tsId",
        (
            "getTsId",
            "getTiltSeriesId",
        ),
    ),
    (
        "_tomoId",
        (
            "getTomoId",
        ),
    ),
)


class ScipionSetPostgresqlMapper(ScipionObjectPostgresqlMapper):
    """Store Scipion SetOf... objects in PostgreSQL using a flat JSONB layout."""

    def _getObjectDisplayText(
            self,
            scipionObj: Any,
    ) -> Optional[str]:
        if isinstance(
                scipionObj,
                ScipionSet,
        ):
            return None

        return super()._getObjectDisplayText(
            scipionObj
        )

    def _getObjectValueText(
            self,
            scipionObj: Any,
    ) -> Optional[str]:
        if isinstance(
                scipionObj,
                ScipionSet,
        ):
            return None

        return super()._getObjectValueText(
            scipionObj
        )

    def closeProtocolOutputSets(
            self,
            projectId: int,
            protocolDbId: int,
    ) -> Dict[str, Any]:
        storedSets = self.db.fetchAll(
            """
            SELECT id,
                   "outputName"
              FROM scipion_sets
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
             ORDER BY "outputName"
            """,
            (
                int(projectId),
                int(protocolDbId),
            ),
        ) or []

        if not storedSets:
            return {
                "protocolDbId": int(protocolDbId),
                "setsClosed": 0,
                "outputs": [],
            }

        closedState = int(ScipionSet.STREAM_CLOSED)

        with self.db.transaction():
            self.db.execute(
                """
                UPDATE scipion_sets
                   SET properties = jsonb_set(
                           jsonb_set(
                               COALESCE(
                                   properties,
                                   '{}'::jsonb
                               ),
                               '{streamState}',
                               TO_JSONB(%s::integer),
                               TRUE
                           ),
                           '{_streamState}',
                           TO_JSONB(%s::integer),
                           TRUE
                       ),
                       "updatedAt" = NOW()
                 WHERE "projectId" = %s
                   AND "protocolDbId" = %s
                """,
                (
                    closedState,
                    closedState,
                    int(projectId),
                    int(protocolDbId),
                ),
                commit=False,
            )

            for propertyName in (
                    "streamState",
                    "_streamState",
            ):
                self.db.execute(
                    """
                    INSERT INTO scipion_set_properties (
                        "setId",
                        key,
                        value
                    )
                    SELECT id,
                           %s,
                           %s
                      FROM scipion_sets
                     WHERE "projectId" = %s
                       AND "protocolDbId" = %s
                    ON CONFLICT ON CONSTRAINT
                        ux_scipion_set_properties_set_key
                    DO UPDATE SET
                        value = EXCLUDED.value
                    """,
                    (
                        propertyName,
                        str(closedState),
                        int(projectId),
                        int(protocolDbId),
                    ),
                    commit=False,
                )

        return {
            "protocolDbId": int(protocolDbId),
            "setsClosed": len(storedSets),
            "outputs": [
                str(row.get("outputName") or "")
                for row in storedSets
            ],
        }

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

        itemValues = self._getItemValues(
            item,
            scipionSet=scipionSet,
        )

        itemSchema = self._getCompleteItemSchema(
            item,
            scipionSet=scipionSet,
            itemValues=itemValues,
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
            "values": itemValues,

            # Runtime-only metadata. It is consumed by
            # PostgresqlSetRuntimeMapper and is never persisted
            # inside the item JSONB values.
            "_schema": itemSchema,
        }

    def synchronizeRuntimeItemSchema(
            self,
            setId: int,
            rootTableId: int,
            item: Any,
            scipionSet: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Persist the item schema discovered by the first
        incremental PostgreSQL append.

        The caller must already own the PostgreSQL transaction.
        """
        if item is None:
            raise ValueError(
                "item is required to synchronize "
                "a PostgreSQL Set schema."
            )

        setId = int(
            setId
        )

        rootTableId = int(
            rootTableId
        )

        itemSchema = self._getCompleteItemSchema(
            item,
            scipionSet=scipionSet,
        )

        itemClassName = self._getItemClassName(
            item=item,
            itemSchema=itemSchema,
            scipionSet=scipionSet,
        )

        columns = self._getSetColumns(
            itemSchema
        )

        self._upsertSetColumns(
            setId=setId,
            columns=columns,
        )

        self._upsertSetTableColumns(
            tableId=rootTableId,
            columns=columns,
        )

        # Read the complete stored representation because
        # columns may already exist from a previous execution.
        storedColumns = self.getStoredSetColumns(
            setId
        )

        columnsCount = len(
            storedColumns
        )

        self.db.execute(
            """
            UPDATE scipion_sets
               SET "itemClassName" = %s,
                   properties = (
                       COALESCE(
                           properties,
                           '{}'::jsonb
                       )
                       || jsonb_build_object(
                           'columnsCount',
                           %s,
                           'itemClassName',
                           %s,
                           'incremental',
                           TRUE
                       )
                   ),
                   "updatedAt" = NOW()
             WHERE id = %s
            """,
            (
                str(itemClassName),
                columnsCount,
                str(itemClassName),
                setId,
            ),
            commit=False,
        )

        self.db.execute(
            """
            UPDATE scipion_set_tables
               SET "itemClassName" = %s,
                   properties = (
                       COALESCE(
                           properties,
                           '{}'::jsonb
                       )
                       || jsonb_build_object(
                           'columnsCount',
                           %s,
                           'incremental',
                           TRUE
                       )
                   ),
                   "updatedAt" = NOW()
             WHERE id = %s
               AND "setId" = %s
               AND "tableKind" = 'root'
            """,
            (
                str(itemClassName),
                columnsCount,
                rootTableId,
                setId,
            ),
            commit=False,
        )

        self._upsertSetProperties(
            setId=setId,
            properties={
                "columnsCount": (
                    columnsCount
                ),
            },
        )

        return {
            "setId": setId,
            "rootTableId": rootTableId,
            "itemClassName": (
                str(itemClassName)
            ),
            "columns": [
                dict(column)
                for column
                in storedColumns
            ],
            "columnsCount": (
                columnsCount
            ),
        }

    def synchronizeRuntimeLogicalItemSchema(
            self,
            tableId: int,
            item: Any,
            parentSet: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Persist the schema discovered by the first append to a
        writable PostgreSQL logical-table Set.

        The caller already owns the PostgreSQL transaction.
        """
        if item is None:
            raise ValueError(
                "item is required to synchronize a "
                "PostgreSQL logical-table schema."
            )

        tableId = int(
            tableId
        )

        itemSchema = self._getCompleteItemSchema(
            item,
            scipionSet=parentSet,
        )

        itemClassName = (
            self._getItemClassName(
                item=item,
                itemSchema=itemSchema,
                scipionSet=parentSet,
            )
        )

        columns = self._getSetColumns(
            itemSchema
        )

        self._upsertSetTableColumns(
            tableId=tableId,
            columns=columns,
        )

        storedColumns = (
            self.getStoredSetTableColumns(
                tableId
            )
        )

        columnsCount = len(
            storedColumns
        )

        self.db.execute(
            """
            UPDATE scipion_set_tables
               SET "itemClassName" = %s,
                   properties = (
                       COALESCE(
                           properties,
                           '{}'::jsonb
                       )
                       || jsonb_build_object(
                           'columnsCount',
                           %s,
                           'itemClassName',
                           %s,
                           'runtimeWritable',
                           TRUE,
                           'incremental',
                           TRUE
                       )
                   ),
                   "updatedAt" = NOW()
             WHERE id = %s
               AND "tableKind" = 'child'
            """,
            (
                str(itemClassName),
                columnsCount,
                str(itemClassName),
                tableId,
            ),
            commit=False,
        )

        return {
            "tableId": tableId,
            "itemClassName": str(
                itemClassName
            ),
            "columns": [
                dict(column)
                for column in storedColumns
            ],
            "columnsCount": columnsCount,
        }

    def storeSet(
            self,
            projectId: int,
            protocolDbId: int,
            outputName: str,
            scipionSet: Any,
            registerType: bool = True,
            batchSize: int = 1000,
            runtimeReserved: bool = False,
            reservationToken: Optional[str] = None,
            replaceRuntimeOutput: bool = False,
    ) -> Dict[str, Any]:
        if not projectId:
            raise ValueError("projectId is required")
        if not protocolDbId:
            raise ValueError("protocolDbId is required")
        if not outputName:
            raise ValueError("outputName is required")
        if batchSize <= 0:
            raise ValueError("batchSize must be greater than zero")
        runtimeObjectId = self._getSourceObjId(scipionSet)

        if runtimeReserved and runtimeObjectId is None:
            raise ValueError(
                "Cannot reserve a populated PostgreSQL runtime Set "
                "without a Scipion object id."
            )

        protocolDbId = self._resolveProtocolDbId(
            projectId,
            protocolDbId,
        )

        existingSet = self._getExistingSet(
            projectId,
            protocolDbId,
            outputName,
        )

        existingProperties = (
            self._normalizeProperties(
                existingSet.get(
                    "properties"
                )
            )
            if existingSet is not None
            else {}
        )

        if (
                existingSet is not None
                and self._hasPostgresqlNativeOutputFlag(
            existingProperties
        )
                and not replaceRuntimeOutput
        ):
            return self.finalizeRuntimeSetOutput(
                projectId=projectId,
                protocolDbId=protocolDbId,
                outputName=outputName,
                scipionSet=scipionSet,
            )

        syncTimestamp = datetime.now(
            timezone.utc
        ).isoformat()

        itemsCountHint = (
            self._getSetItemsCountHint(
                scipionSet
            )
        )

        maxItemIdHint = (
            self._getSetMaxItemIdHint(
                scipionSet
            )
        )

        sourceMTime = (
            self._getSetSourceMTime(
                scipionSet
            )
        )

        if existingSet is not None:
            existingSetId = int(existingSet["id"])
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
        itemSchema = (
            self._getCompleteItemSchema(
                firstItem,
                scipionSet=scipionSet,
            )
            if firstItem is not None
            else {}
        )
        itemClassName = self._getItemClassName(firstItem, itemSchema, scipionSet=scipionSet,)
        columns = self._getSetColumns(itemSchema)
        initialProperties = self._getSetProperties(
            scipionSet
        )

        initialProperties[
            "nestedTablesVersion"
        ] = NESTED_LOGICAL_TABLES_VERSION

        initialProperties[
            "setPropertiesVersion"
        ] = SET_PROPERTIES_VERSION

        nativeRuntimeOutput = bool(
            runtimeReserved
            or replaceRuntimeOutput
        )

        if nativeRuntimeOutput:
            self._removePostgresqlRuntimeStorageProperties(
                initialProperties
            )

            initialProperties.update({
                "runtimeWritable": True,
                "postgresqlNativeOutput": True,
                "incremental": True,
            })

        if runtimeReserved:
            initialProperties.update({
                "runtimeReserved": True,
                "provisionalOutputName": outputName,
                "reservationToken": reservationToken,
            })

        elif replaceRuntimeOutput:
            initialProperties.update({
                "runtimeReserved": False,
                "outputName": outputName,
                "finalOutputName": outputName,
            })

        storedPaths: List[str] = []
        rootTableProperties = {
            "source": "postgresql",
            "legacySetTable": True,
        }

        if nativeRuntimeOutput:
            rootTableProperties[
                "runtimeWritable"
            ] = True
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
                properties=rootTableProperties,
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

        eventRuntimeObjectId = runtimeObjectId if runtimeObjectId is not None else rootObjectId

        PostgresqlRuntimeEventPublisher.publish(
            db=self.db,
            projectId=projectId,
            eventType="set_updated",
            protocolDbId=protocolDbId,
            outputName=outputName,
            setId=setId,
            runtimeObjectId=eventRuntimeObjectId,
            itemsCount=itemsCount,
            maxItemId=maxItemId,
        )

        return {
            "setId": setId,
            "rootTableId": rootTableId,
            "rootObjectId": rootObjectId,
            "runtimeObjectId": runtimeObjectId,
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
            "properties": finalProperties,
            "reserved": bool(runtimeReserved),
        }

    def reserveRuntimeSet(
            self,
            projectId: int,
            protocolDbId: int,
            outputName: str,
            scipionSet: Any,
            reservationToken: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Reserve an empty PostgreSQL Set before a protocol starts
        appending items.

        No SQLite file is created and no Set iteration is attempted.
        """
        if not projectId:
            raise ValueError("projectId is required")

        if not protocolDbId:
            raise ValueError("protocolDbId is required")

        outputName = str(
            outputName or ""
        ).strip()

        if not outputName:
            raise ValueError("outputName is required")

        runtimeObjectId = self._getSourceObjId(
            scipionSet
        )

        if runtimeObjectId is None:
            raise ValueError(
                "Cannot reserve a PostgreSQL runtime Set "
                "without a Scipion object id."
            )

        protocolDbId = self._resolveProtocolDbId(
            projectId,
            protocolDbId,
        )

        setClassName = (
                self._getClassName(
                    scipionSet
                )
                or scipionSet.__class__.__name__
        )

        itemClassName = self._getItemClassName(
            item=None,
            itemSchema={},
            scipionSet=scipionSet,
        )

        if (
                not itemClassName
                or str(itemClassName).lower()
                == "unknown"
        ):
            raise ValueError(
                "Cannot reserve PostgreSQL Set %s "
                "without a declared ITEM_TYPE."
                % setClassName
            )

        self.registerObjectTypeFromObject(
            scipionSet,
            mapperKind="flat_set",
            includeProperties=False,
            classSchema={
                "storage": "flat_set",
                "runtimeWritable": True,
            },
        )

        timestamp = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        properties = self._getSetProperties(
            scipionSet
        )

        self._removePostgresqlRuntimeStorageProperties(
            properties
        )

        properties.update({
            "columnsCount": 0,
            "itemsCount": 0,
            "maxItemId": None,
            "incremental": True,
            "runtimeReserved": True,
            "runtimeWritable": True,
            "postgresqlNativeOutput": True,
            "provisionalOutputName": outputName,
            "reservationToken": reservationToken,
            "lastSyncAt": timestamp,
            "lastCheckedAt": timestamp,
            "nestedTablesVersion": (
                NESTED_LOGICAL_TABLES_VERSION
            ),
            "setPropertiesVersion": (
                SET_PROPERTIES_VERSION
            ),
        })

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
                setClassName=setClassName,
                itemClassName=str(
                    itemClassName
                ),
                properties=properties,
            )

            self._replaceStoredSetSnapshot(
                setId=setId
            )

            rootTableId = self._upsertSetTable(
                setId=setId,
                name="objects",
                alias=setClassName,
                tableKind="root",
                parentTableId=None,
                parentItemId=None,
                itemClassName=str(
                    itemClassName
                ),
                properties={
                    "source": "postgresql",
                    "legacySetTable": True,
                    "runtimeWritable": True,
                    "itemsCount": 0,
                    "maxItemId": None,
                    "incremental": True,
                },
            )

            self._updateSetProperties(
                setId=setId,
                properties=properties,
            )

            self._upsertSetProperties(
                setId=setId,
                properties=properties,
            )

        PostgresqlRuntimeEventPublisher.publish(
            db=self.db,
            projectId=projectId,
            eventType="set_updated",
            protocolDbId=protocolDbId,
            outputName=outputName,
            setId=setId,
            runtimeObjectId=runtimeObjectId,
            itemsCount=0,
            maxItemId=None,
        )

        return {
            "setId": int(setId),
            "rootTableId": int(
                rootTableId
            ),
            # Database id of the scipion_objects row.
            "objectId": int(
                rootObjectId
            ),
            # Canonical Scipion runtime id.
            "runtimeObjectId": int(
                runtimeObjectId
            ),
            "projectId": int(
                projectId
            ),
            "protocolDbId": int(
                protocolDbId
            ),
            "outputName": outputName,
            "className": setClassName,
            "setClassName": setClassName,
            "itemClassName": str(
                itemClassName
            ),
            "properties": properties,
            "reserved": True,
        }

    def finalizeRuntimeSetOutput(
            self,
            projectId: int,
            protocolDbId: int,
            outputName: str,
            scipionSet: Any,
    ) -> Dict[str, Any]:
        """
        Rename and finalize a previously reserved PostgreSQL runtime Set.

        This method never iterates the Set and never rebuilds its items.
        """
        outputName = str(
            outputName or ""
        ).strip()

        if not outputName:
            raise ValueError("outputName is required")

        runtimeObjectId = self._getSourceObjId(
            scipionSet
        )

        if runtimeObjectId is None:
            raise ValueError(
                "Cannot finalize a PostgreSQL Set "
                "without its runtime object id."
            )

        protocolDbId = self._resolveProtocolDbId(
            projectId,
            protocolDbId,
        )

        storedSet = self.db.fetchOne(
            """
            SELECT
                stored_set.id,
                stored_set."objectId",
                stored_set."outputName",
                stored_set."setClassName",
                stored_set."itemClassName",
                stored_set.properties
              FROM scipion_sets stored_set
              JOIN scipion_objects object_row
                ON object_row.id =
                   stored_set."objectId"
             WHERE stored_set."projectId" = %s
               AND stored_set."protocolDbId" = %s
               AND object_row."scipionObjId" = %s
             LIMIT 1
            """,
            (
                int(projectId),
                int(protocolDbId),
                int(runtimeObjectId),
            ),
        )

        if storedSet is None:
            raise RuntimeError(
                "PostgreSQL runtime Set %s was not reserved."
                % runtimeObjectId
            )

        setId = int(
            storedSet["id"]
        )

        objectId = int(
            storedSet["objectId"]
        )

        conflictingSet = self.db.fetchOne(
            """
            SELECT id
              FROM scipion_sets
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
               AND "outputName" = %s
               AND id <> %s
             LIMIT 1
            """,
            (
                int(projectId),
                int(protocolDbId),
                outputName,
                setId,
            ),
        )

        if conflictingSet is not None:
            raise RuntimeError(
                "Protocol output '%s' is already owned "
                "by PostgreSQL Set %s."
                % (
                    outputName,
                    conflictingSet["id"],
                )
            )

        existingProperties = self._normalizeProperties(
            storedSet.get(
                "properties"
            )
        )

        self._removePostgresqlRuntimeStorageProperties(
            existingProperties
        )

        currentProperties = self._getSetProperties(
            scipionSet
        )

        self._removePostgresqlRuntimeStorageProperties(
            currentProperties
        )

        finalProperties = dict(
            existingProperties
        )

        finalProperties.update(
            currentProperties
        )

        self._removePostgresqlRuntimeStorageProperties(
            finalProperties
        )

        finalProperties.update({
            "runtimeReserved": False,
            "runtimeWritable": True,
            "postgresqlNativeOutput": True,
            "outputName": outputName,
            "finalOutputName": outputName,
            "incremental": True,
            "lastCheckedAt": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "nestedTablesVersion": (
                NESTED_LOGICAL_TABLES_VERSION
            ),
            "setPropertiesVersion": (
                SET_PROPERTIES_VERSION
            ),
        })

        setClassName = (
                self._getClassName(
                    scipionSet
                )
                or storedSet[
                    "setClassName"
                ]
        )

        with self.db.transaction():
            self.db.execute(
                """
                UPDATE scipion_objects
                   SET name = %s,
                       path = %s,
                       "scipionObjId" = %s,
                       "className" = %s,
                       label = %s,
                       comment = %s,
                       creation = %s,
                       "updatedAt" = NOW()
                 WHERE id = %s
                   AND "projectId" = %s
                   AND "protocolDbId" = %s
                """,
                (
                    outputName,
                    outputName,
                    int(runtimeObjectId),
                    str(setClassName),
                    self._getObjectLabel(
                        scipionSet
                    ),
                    self._getObjectComment(
                        scipionSet
                    ),
                    self._getObjectCreation(
                        scipionSet
                    ),
                    objectId,
                    int(projectId),
                    int(protocolDbId),
                ),
                commit=False,
            )

            self.db.execute(
                """
                UPDATE scipion_sets
                   SET "outputName" = %s,
                       "setClassName" = %s,
                       properties = %s::jsonb,
                       "updatedAt" = NOW()
                 WHERE id = %s
                   AND "projectId" = %s
                   AND "protocolDbId" = %s
                """,
                (
                    outputName,
                    str(setClassName),
                    self._jsonParam(
                        finalProperties
                    ),
                    setId,
                    int(projectId),
                    int(protocolDbId),
                ),
                commit=False,
            )

            self._upsertSetProperties(
                setId=setId,
                properties=finalProperties,
            )

        itemsCount = self._toOptionalInt(
            finalProperties.get(
                "itemsCount"
            )
        )

        maxItemId = self._toOptionalInt(
            finalProperties.get(
                "maxItemId"
            )
        )

        PostgresqlRuntimeEventPublisher.publish(
            db=self.db,
            projectId=projectId,
            eventType="set_updated",
            protocolDbId=protocolDbId,
            outputName=outputName,
            setId=setId,
            runtimeObjectId=runtimeObjectId,
            itemsCount=itemsCount or 0,
            maxItemId=maxItemId,
        )

        return {
            "setId": setId,
            "rootTableId": self._resolveRootTableId(
                setId
            ),
            "objectId": objectId,
            "runtimeObjectId": int(
                runtimeObjectId
            ),
            "projectId": int(
                projectId
            ),
            "protocolDbId": int(
                protocolDbId
            ),
            "outputName": outputName,
            "className": str(
                setClassName
            ),
            "setClassName": str(
                setClassName
            ),
            "itemClassName": storedSet[
                "itemClassName"
            ],
            "properties": finalProperties,
            "reserved": False,
        }

    def discardReservedRuntimeSet(
            self,
            projectId: int,
            protocolDbId: int,
            runtimeObjectId: int,
    ) -> bool:
        protocolDbId = self._resolveProtocolDbId(
            projectId,
            protocolDbId,
        )

        storedSet = self.db.fetchOne(
            """
            SELECT
                stored_set.id,
                stored_set."objectId",
                stored_set.properties
              FROM scipion_sets stored_set
              JOIN scipion_objects object_row
                ON object_row.id =
                   stored_set."objectId"
             WHERE stored_set."projectId" = %s
               AND stored_set."protocolDbId" = %s
               AND object_row."scipionObjId" = %s
             LIMIT 1
            """,
            (
                int(projectId),
                int(protocolDbId),
                int(runtimeObjectId),
            ),
        )

        if storedSet is None:
            return False

        properties = self._normalizeProperties(
            storedSet.get(
                "properties"
            )
        )

        if not properties.get(
                "runtimeReserved"
        ):
            return False

        self.deleteStoredSetOutput(
            projectId=int(projectId),
            setId=int(
                storedSet["id"]
            ),
            objectId=int(
                storedSet["objectId"]
            ),
            runtimeObjectId=int(
                runtimeObjectId
            ),
        )

        return True

    def _resolveRootTableId(
            self,
            setId: int,
    ) -> Optional[int]:
        row = self.db.fetchOne(
            """
            SELECT id
              FROM scipion_set_tables
             WHERE "setId" = %s
               AND "tableKind" = 'root'
             LIMIT 1
            """,
            (
                int(setId),
            ),
        )

        return (
            int(row["id"])
            if row is not None
            else None
        )

    def _isPostgresqlRuntimeSet(
            self,
            scipionSet: Any,
    ) -> bool:
        checker = getattr(
            scipionSet,
            "isPostgresqlRuntimeOutput",
            None,
        )

        if not callable(checker):
            return False

        try:
            return bool(
                checker()
            )
        except Exception:
            return False

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

    def getStoredSetItemByRuntimeObjectId(
            self,
            projectId: int,
            runtimeObjectId: int,
            scipionItemId: int,
    ) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne(
            """
            SELECT
                item."scipionItemId",
                item.label,
                item.comment,
                item."values",
                stored_set."outputName",
                protocol."protocolId"
              FROM scipion_sets stored_set
              JOIN scipion_objects object_row
                ON object_row."projectId" = stored_set."projectId"
               AND object_row.id = stored_set."objectId"
              JOIN scipion_set_items item
                ON item."setId" = stored_set.id
              JOIN protocols protocol
                ON protocol."projectId" = stored_set."projectId"
               AND protocol.id = stored_set."protocolDbId"
             WHERE stored_set."projectId" = %s
               AND object_row."scipionObjId" = %s
               AND item."scipionItemId" = %s
             LIMIT 1
            """,
            (int(projectId), int(runtimeObjectId), int(scipionItemId)),
        )

        return dict(row) if row is not None else None

    def getStoredSetItemByProtocolOutput(
            self,
            projectId: int,
            protocolId: int,
            outputName: str,
            scipionItemId: int,
    ) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne(
            """
            SELECT
                item."scipionItemId",
                item.label,
                item.comment,
                item."values",
                stored_set."outputName",
                protocol."protocolId"
              FROM scipion_sets stored_set
              JOIN scipion_set_items item
                ON item."setId" = stored_set.id
              JOIN protocols protocol
                ON protocol."projectId" = stored_set."projectId"
               AND protocol.id = stored_set."protocolDbId"
             WHERE stored_set."projectId" = %s
               AND protocol."protocolId"::text = %s
               AND stored_set."outputName" = %s
               AND item."scipionItemId" = %s
             LIMIT 1
            """,
            (int(projectId), str(protocolId), str(outputName), int(scipionItemId)),
        )

        return dict(row) if row is not None else None

    def getStoredSetItemBySourceRelation(self, projectId: int, childSetId: int, scipionItemId: int) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne(
            """
            SELECT
                item."scipionItemId",
                item.label,
                item.comment,
                item."values",
                parent_set."outputName",
                parent_protocol."protocolId"
              FROM scipion_sets child_set
              JOIN scipion_objects child_object
                ON child_object."projectId" = child_set."projectId"
               AND child_object.id = child_set."objectId"
              JOIN scipion_relations source_relation
                ON source_relation."projectId" = child_set."projectId"
               AND source_relation.name = 'source'
               AND source_relation."childObjId" = child_object."scipionObjId"
              JOIN scipion_objects parent_object
                ON parent_object."projectId" = source_relation."projectId"
               AND parent_object."scipionObjId" = source_relation."parentObjId"
              JOIN scipion_sets parent_set
                ON parent_set."projectId" = parent_object."projectId"
               AND parent_set."objectId" = parent_object.id
              JOIN scipion_set_items item
                ON item."setId" = parent_set.id
              JOIN protocols parent_protocol
                ON parent_protocol."projectId" = parent_set."projectId"
               AND parent_protocol.id = parent_set."protocolDbId"
             WHERE child_set."projectId" = %s
               AND child_set.id = %s
               AND item."scipionItemId" = %s
               AND (
                     LOWER(COALESCE(parent_set."setClassName", '')) LIKE '%%micrograph%%'
                  OR LOWER(COALESCE(parent_set."itemClassName", '')) LIKE '%%micrograph%%'
               )
             ORDER BY source_relation.id ASC
             LIMIT 1
            """,
            (int(projectId), int(childSetId), int(scipionItemId)),
        )

        return dict(row) if row is not None else None

    def getStoredMicrographItemFromProtocolInputGraph(
            self,
            projectId: int,
            protocolDbId: int,
            scipionItemId: int,
    ) -> Optional[Dict[str, Any]]:
        protocolDbId = self._resolveProtocolDbId(projectId, protocolDbId)

        row = self.db.fetchOne(
            """
            WITH RECURSIVE input_graph(
                "projectId",
                "protocolDbId",
                "outputName",
                depth,
                protocol_path
            ) AS (
                SELECT
                    input_ref."projectId",
                    input_ref."parentProtocolDbId",
                    input_ref."parentOutputName",
                    1,
                    ARRAY[
                        input_ref."protocolDbId",
                        input_ref."parentProtocolDbId"
                    ]
                  FROM protocol_input_refs input_ref
                 WHERE input_ref."projectId" = %s
                   AND input_ref."protocolDbId" = %s
                   AND input_ref."parentProtocolDbId" IS NOT NULL
                   AND COALESCE(input_ref."parentOutputName", '') <> ''

                UNION ALL

                SELECT
                    input_ref."projectId",
                    input_ref."parentProtocolDbId",
                    input_ref."parentOutputName",
                    input_graph.depth + 1,
                    input_graph.protocol_path
                        || input_ref."parentProtocolDbId"
                  FROM input_graph
                  JOIN protocol_input_refs input_ref
                    ON input_ref."projectId" = input_graph."projectId"
                   AND input_ref."protocolDbId" = input_graph."protocolDbId"
                 WHERE input_ref."parentProtocolDbId" IS NOT NULL
                   AND COALESCE(input_ref."parentOutputName", '') <> ''
                   AND NOT input_ref."parentProtocolDbId"
                           = ANY(input_graph.protocol_path)
            )
            SELECT
                item."scipionItemId",
                item.label,
                item.comment,
                item."values",
                parent_set."outputName",
                parent_protocol."protocolId"
              FROM input_graph
              JOIN scipion_sets parent_set
                ON parent_set."projectId" = input_graph."projectId"
               AND parent_set."protocolDbId" = input_graph."protocolDbId"
               AND parent_set."outputName" = input_graph."outputName"
              JOIN scipion_set_items item
                ON item."setId" = parent_set.id
              JOIN protocols parent_protocol
                ON parent_protocol."projectId" = parent_set."projectId"
               AND parent_protocol.id = parent_set."protocolDbId"
             WHERE item."scipionItemId" = %s
               AND (
                     LOWER(COALESCE(parent_set."setClassName", ''))
                         LIKE '%%micrograph%%'
                  OR LOWER(COALESCE(parent_set."itemClassName", ''))
                         LIKE '%%micrograph%%'
               )
             ORDER BY
                input_graph.depth ASC,
                parent_set.id ASC
             LIMIT 1
            """,
            (int(projectId), int(protocolDbId), int(scipionItemId)),
        )

        return dict(row) if row is not None else None

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

    def listProtocolSetOutputRows(
            self,
            projectId: int,
            protocolDbId: int,
    ) -> List[Dict[str, Any]]:
        return self.db.fetchAll(
            """
            SELECT
                stored_set."outputName",
                stored_set."setClassName",
                stored_set."itemClassName",
                stored_set.properties,
                stored_set.id AS "setId",
                stored_set."objectId",
                root_object."scipionObjId"
              FROM scipion_sets stored_set
              LEFT JOIN scipion_objects root_object
                ON root_object.id = stored_set."objectId"
             WHERE stored_set."projectId" = %s
               AND stored_set."protocolDbId" = %s
               AND COALESCE(
                       stored_set.properties ->> 'runtimeReserved',
                       'false'
                   ) <> 'true'
             ORDER BY stored_set."outputName"
            """,
            (
                int(projectId),
                int(protocolDbId),
            ),
        ) or []

    def listProtocolSetOutputNameRows(
            self,
            projectId: int,
            protocolDbId: int,
    ) -> List[Dict[str, Any]]:
        return self.db.fetchAll(
            """
            SELECT "outputName"
              FROM scipion_sets
             WHERE "projectId" = %s
               AND "protocolDbId" = %s
            """,
            (int(projectId), int(protocolDbId)),
        ) or []

    def listProjectSetOutputRows(self, projectId: int) -> List[Dict[str, Any]]:
        query = """
            SELECT
                p.id AS "protocolDbId",
                p."protocolId",
                s.id,
                s."objectId",
                s."outputName",
                s."setClassName",
                s."itemClassName",
                s.properties,
                root_object.id AS "rootObjectDbId",
                root_object."projectId" AS "rootObjectProjectId",
                root_object."protocolDbId" AS "rootObjectProtocolDbId",
                root_object."parentObjectId" AS "rootObjectParentObjectId",
                root_object.name AS "rootObjectName",
                root_object.path AS "rootObjectPath",
                root_object."className" AS "rootObjectClassName",
                COALESCE(items_stats."itemsTableCount", 0) AS "itemsTableCount",
                items_stats."maxItemIdFromItems" AS "maxItemIdFromItems",
                items_stats."itemsIdSignature" AS "itemsIdSignature",
                items_stats."itemsValueSignature" AS "itemsValueSignature",
                COALESCE(columns_stats."setColumnsCount", 0) AS "setColumnsCount",
                columns_stats."setColumnsSignature" AS "setColumnsSignature",
                COALESCE(root_table_stats."rootTablesCount", 0) AS "rootTablesCount",
                root_table_stats."rootTableId" AS "rootTableId",
                COALESCE(root_table_stats."rootTableItemsCount", 0) AS "rootTableItemsCount",
                root_table_stats."rootTableMaxItemId" AS "rootTableMaxItemId",
                root_table_stats."rootTableItemsIdSignature" AS "rootTableItemsIdSignature",
                root_table_stats."rootTableItemsValueSignature" AS "rootTableItemsValueSignature",
                COALESCE(root_table_columns_stats."rootTableColumnsCount", 0) AS "rootTableColumnsCount",
                root_table_columns_stats."rootTableColumnsSignature" AS "rootTableColumnsSignature",
                COALESCE(properties_payload_stats."propertiesPayloadCount", 0) AS "propertiesPayloadCount",
                properties_payload_stats."propertiesPayloadSignature" AS "propertiesPayloadSignature",
                COALESCE(set_properties_stats."setPropertiesCount", 0) AS "setPropertiesCount",
                set_properties_stats."setPropertiesSignature" AS "setPropertiesSignature",
                s."createdAt",
                s."updatedAt"
              FROM scipion_sets s
              JOIN protocols p
                ON p.id = s."protocolDbId"
              LEFT JOIN scipion_objects root_object
                ON root_object.id = s."objectId"
              LEFT JOIN (
                  SELECT
                      "setId",
                      COUNT(*)::int AS "itemsTableCount",
                      MAX("scipionItemId")::int AS "maxItemIdFromItems",
                      md5(
                          string_agg(
                              "scipionItemId"::text,
                              ','
                              ORDER BY "scipionItemId"
                          )
                      ) AS "itemsIdSignature",
                      md5(
                          string_agg(
                              jsonb_build_object(
                                  'scipionItemId', "scipionItemId",
                                  'enabled', enabled,
                                  'label', label,
                                  'comment', comment,
                                  'creation', creation,
                                  'values', "values"
                              )::text,
                              ','
                              ORDER BY "scipionItemId"
                          )
                      ) AS "itemsValueSignature"
                    FROM scipion_set_items
                   GROUP BY "setId"
              ) items_stats
                ON items_stats."setId" = s.id
              LEFT JOIN (
                  SELECT
                      "setId",
                      COUNT(*)::int AS "setColumnsCount",
                      jsonb_agg(
                          jsonb_build_object(
                              'labelProperty', "labelProperty",
                              'columnName', "columnName",
                              'className', "className",
                              'valueType', "valueType",
                              'position', position,
                              'indexed', indexed
                          )
                          ORDER BY position ASC, "labelProperty" ASC
                      ) AS "setColumnsSignature"
                    FROM scipion_set_columns
                   GROUP BY "setId"
              ) columns_stats
                ON columns_stats."setId" = s.id
              LEFT JOIN (
                  SELECT
                      t."setId",
                      COUNT(DISTINCT t.id)::int AS "rootTablesCount",
                      MIN(t.id)::int AS "rootTableId",
                      COUNT(ti.id)::int AS "rootTableItemsCount",
                      MAX(ti."scipionItemId")::int AS "rootTableMaxItemId",
                      md5(
                          string_agg(
                              ti."scipionItemId"::text,
                              ','
                              ORDER BY ti."scipionItemId"
                          ) FILTER (WHERE ti.id IS NOT NULL)
                      ) AS "rootTableItemsIdSignature",
                      md5(
                          string_agg(
                              jsonb_build_object(
                                  'scipionItemId', ti."scipionItemId",
                                  'enabled', ti.enabled,
                                  'label', ti.label,
                                  'comment', ti.comment,
                                  'creation', ti.creation,
                                  'values', ti."values"
                              )::text,
                              ','
                              ORDER BY ti."scipionItemId"
                          ) FILTER (WHERE ti.id IS NOT NULL)
                      ) AS "rootTableItemsValueSignature"
                    FROM scipion_set_tables t
                    LEFT JOIN scipion_set_table_items ti
                      ON ti."tableId" = t.id
                   WHERE t."tableKind" = 'root'
                   GROUP BY t."setId"
              ) root_table_stats
                ON root_table_stats."setId" = s.id
              LEFT JOIN (
                  SELECT
                      t."setId",
                      COUNT(tc.id)::int AS "rootTableColumnsCount",
                      jsonb_agg(
                          jsonb_build_object(
                              'labelProperty', tc."labelProperty",
                              'columnName', tc."columnName",
                              'className', tc."className",
                              'valueType', tc."valueType",
                              'position', tc.position,
                              'indexed', tc.indexed
                          )
                          ORDER BY tc.position ASC, tc."labelProperty" ASC
                      ) FILTER (WHERE tc.id IS NOT NULL) AS "rootTableColumnsSignature"
                    FROM scipion_set_tables t
                    LEFT JOIN scipion_set_table_columns tc
                      ON tc."tableId" = t.id
                   WHERE t."tableKind" = 'root'
                   GROUP BY t."setId"
              ) root_table_columns_stats
                ON root_table_columns_stats."setId" = s.id
              LEFT JOIN (
                  SELECT
                      s2.id AS "setId",
                      COUNT(*)::int AS "propertiesPayloadCount",
                      jsonb_agg(
                          jsonb_build_object(
                              'key', stable_keys.key,
                              'value', s2.properties ->> stable_keys.key
                          )
                          ORDER BY stable_keys.key ASC
                      ) AS "propertiesPayloadSignature"
                    FROM scipion_sets s2
                    CROSS JOIN (
                        VALUES
                            ('columnsCount'),
                            ('itemsCount'),
                            ('nestedTablesVersion')
                    ) AS stable_keys(key)
                   WHERE s2.properties ? stable_keys.key
                   GROUP BY s2.id
              ) properties_payload_stats
                ON properties_payload_stats."setId" = s.id
              LEFT JOIN (
                  SELECT
                      "setId",
                      COUNT(*)::int AS "setPropertiesCount",
                      jsonb_agg(
                          jsonb_build_object(
                              'key', key,
                              'value', value
                          )
                          ORDER BY key ASC
                      ) AS "setPropertiesSignature"
                    FROM scipion_set_properties
                   WHERE key IN (
                       'columnsCount',
                       'itemsCount',
                       'nestedTablesVersion'
                   )
                   GROUP BY "setId"
              ) set_properties_stats
                ON set_properties_stats."setId" = s.id
             WHERE s."projectId" = %s
               AND COALESCE(
                       s.properties ->> 'runtimeReserved',
                       'false'
                   ) <> 'true'
             ORDER BY p."protocolId", s."outputName"
        """
        return self.db.fetchAll(query, (int(projectId),)) or []

    def listProjectSetOutputSummaryRows(self, projectId: int) -> List[Dict[str, Any]]:
        return self.db.fetchAll(
            """
            SELECT
                p."protocolId",
                s.id,
                s."objectId",
                s."outputName",
                s."setClassName",
                s."itemClassName",
                s.properties,
                s."createdAt",
                s."updatedAt"
              FROM scipion_sets s
              JOIN protocols p
                ON p.id = s."protocolDbId"
             WHERE s."projectId" = %s
               AND COALESCE(
                       s.properties ->> 'runtimeReserved',
                       'false'
                   ) <> 'true'
             ORDER BY p."protocolId", s."outputName"
            """,
            (int(projectId),),
        ) or []

    def listProjectTomogramCandidateItemRows(
            self,
            projectId: int,
    ) -> List[Dict[str, Any]]:
        return self.db.fetchAll(
            """
            SELECT
                s.id AS "setId",
                s."projectId",
                s."protocolDbId",
                s."outputName",
                s."setClassName",
                s."itemClassName",
                s.properties AS "setProperties",
                i.id AS "itemRowId",
                i."scipionItemId",
                i.enabled,
                i.label,
                i.comment,
                i.creation,
                i."values",
                i."createdAt",
                i."updatedAt"
              FROM scipion_sets s
              JOIN scipion_set_items i
                ON i."setId" = s.id
             WHERE s."projectId" = %s
               AND (
                     LOWER(COALESCE(s."setClassName", '')) LIKE '%%tomogram%%'
                  OR LOWER(COALESCE(s."itemClassName", '')) LIKE '%%tomogram%%'
                  OR LOWER(COALESCE(s."setClassName", '')) LIKE '%%volume%%'
                  OR LOWER(COALESCE(s."itemClassName", '')) LIKE '%%volume%%'
               )
             ORDER BY
                CASE
                    WHEN LOWER(COALESCE(s."itemClassName", '')) LIKE '%%tomogram%%' THEN 0
                    WHEN LOWER(COALESCE(s."setClassName", '')) LIKE '%%tomogram%%' THEN 1
                    ELSE 2
                END,
                s."protocolDbId" ASC,
                s."outputName" ASC,
                i."scipionItemId" ASC
            """,
            (int(projectId),),
        ) or []

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

    @staticmethod
    def _hasPostgresqlNativeOutputFlag(
            properties: Dict[str, Any],
    ) -> bool:
        value = (
            properties or {}
        ).get(
            "postgresqlNativeOutput"
        )

        if isinstance(value, bool):
            return value

        return str(
            value or ""
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def isPostgresqlNativeSetOutput(
            self,
            projectId: int,
            protocolDbId: int,
            outputName: str,
    ) -> bool:
        protocolDbId = self._resolveProtocolDbId(
            projectId,
            protocolDbId,
        )

        existingSet = self._getExistingSet(
            projectId,
            protocolDbId,
            outputName,
        )

        if existingSet is None:
            return False

        properties = self._normalizeProperties(
            existingSet.get(
                "properties"
            )
        )

        return (
            self
            ._hasPostgresqlNativeOutputFlag(
                properties
            )
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

    def ensureRuntimeNestedSetTable(
            self,
            setId: int,
            rootTableId: int,
            parentSet: Any,
            parentItemId: int,
            batchSize: int = 1000,
    ) -> Dict[str, Any]:
        """
        Create or refresh the PostgreSQL logical table owned by
        one nested runtime Set item.

        The caller must already own the PostgreSQL transaction.
        No commit or nested transaction is performed here.
        """
        if not isinstance(
                parentSet,
                ScipionSet,
        ):
            raise TypeError(
                "Runtime nested item must be a "
                "Scipion Set. className=%s"
                % parentSet.__class__.__name__
            )

        setId = int(
            setId
        )

        rootTableId = int(
            rootTableId
        )

        parentItemId = int(
            parentItemId
        )

        if batchSize <= 0:
            raise ValueError(
                "batchSize must be greater than zero"
            )

        tableId = (
            self
            ._upsertNestedLogicalTablesForItem(
                setId=setId,
                parentTableId=rootTableId,
                parentItem=parentSet,
                parentItemId=parentItemId,
                batchSize=batchSize,
                runtimeWritable=True,
            )
        )

        if tableId is None:
            raise RuntimeError(
                "Could not create PostgreSQL logical "
                "table for nested runtime Set. "
                "setId=%s parentItemId=%s className=%s"
                % (
                    setId,
                    parentItemId,
                    self._getClassName(
                        parentSet
                    ),
                )
            )

        tableId = int(
            tableId
        )

        counters = self.db.fetchOne(
            """
            SELECT
                COUNT(*) AS "itemsCount",
                MAX(
                    "scipionItemId"
                ) AS "maxItemId"
              FROM scipion_set_table_items
             WHERE "tableId" = %s
            """,
            (
                tableId,
            ),
        ) or {}

        itemsCount = int(
            counters.get(
                "itemsCount"
            )
            or 0
        )

        maxItemId = counters.get(
            "maxItemId"
        )

        maxItemId = (
            int(maxItemId)
            if maxItemId is not None
            else None
        )

        storedColumns = (
            self.getStoredSetTableColumns(
                tableId
            )
        )

        properties = {
            "source": "postgresql",
            "parentItemId": parentItemId,
            "parentClassName": (
                self._getClassName(
                    parentSet
                )
            ),
            "runtimeWritable": True,
            "incremental": True,
            "itemsCount": itemsCount,
            "maxItemId": maxItemId,
            "columnsCount": len(
                storedColumns
            ),
        }

        self.db.execute(
            """
            UPDATE scipion_set_tables
               SET properties = (
                       COALESCE(
                           properties,
                           '{}'::jsonb
                       )
                       || %s::jsonb
                   ),
                   "updatedAt" = NOW()
             WHERE id = %s
               AND "setId" = %s
               AND "parentTableId" = %s
               AND "parentItemId" = %s
               AND "tableKind" = 'child'
            """,
            (
                self._jsonParam(
                    properties
                ),
                tableId,
                setId,
                rootTableId,
                parentItemId,
            ),
            commit=False,
        )

        tableRow = self.db.fetchOne(
            """
            SELECT
                id,
                "setId",
                name,
                alias,
                "tableKind",
                "parentTableId",
                "parentItemId",
                "itemClassName",
                properties
              FROM scipion_set_tables
             WHERE id = %s
            """,
            (
                tableId,
            ),
        )

        if tableRow is None:
            raise RuntimeError(
                "PostgreSQL logical table %s "
                "disappeared after creation."
                % tableId
            )

        return {
            "setId": setId,
            "rootTableId": rootTableId,
            "tableId": tableId,
            "parentItemId": parentItemId,
            "itemClassName": (
                tableRow.get(
                    "itemClassName"
                )
            ),
            "columns": [
                dict(column)
                for column in storedColumns
            ],
            "columnsCount": len(
                storedColumns
            ),
            "itemsCount": itemsCount,
            "maxItemId": maxItemId,
            "properties": properties,
            "table": dict(
                tableRow
            ),
        }

    def _upsertNestedLogicalTablesForItem(
            self,
            setId: int,
            parentTableId: int,
            parentItem: Any,
            parentItemId: int,
            batchSize: int,
            runtimeWritable: bool = False,
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

        sourceMapper = getattr(
            parentItem,
            "_mapper",
            None,
        )

        if (
                runtimeWritable
                and sourceMapper is None
        ):
            # A newly-created TiltSeries/Class item has not
            # received its PostgreSQL logical mapper yet.
            #
            # It is empty at this point and its declared
            # ITEM_TYPE is enough to create the child table.
            childIterator = iter(())

        else:
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
            childSchema = self._getCompleteItemSchema(
                firstChild,
                scipionSet=parentItem,
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
                    int(parentItemId)
                ),
                "parentClassName": (
                    self._getClassName(
                        parentItem
                    )
                ),
                "runtimeWritable": bool(
                    runtimeWritable
                ),
                "incremental": bool(
                    runtimeWritable
                ),
                "itemsCount": 0,
                "maxItemId": None,
                "columnsCount": len(
                    childColumns
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
        if self._isPostgresqlRuntimeSet(
                scipionSet
        ):
            return None

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

        for path, pointerAttribute in self._iterPointerAttributes(item):
            schema[str(path)] = (
                self._getClassName(pointerAttribute),
                None,
            )

        return schema

    def _getCompleteItemSchema(
            self,
            item: Any,
            scipionSet: Optional[Any] = None,
            itemValues: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        schema = self._getItemSchema(
            item
        )

        if itemValues is None:
            itemValues = self._getItemValues(
                item,
                scipionSet=scipionSet,
            )

        self._completeScalarSchemaFromValues(
            schema=schema,
            values=itemValues,
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

        # A nested Set may temporarily point to a compatibility
        # SQLite snapshot under /tmp. PostgreSQL runtime storage
        # must never persist those transient paths.
        if self._isPostgresqlRuntimeSet(
                scipionSet
        ):
            self._removePostgresqlRuntimeStorageProperties(
                rawValues
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
        return super()._serializePointerReference(pointer)

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

    def _completeScalarSchemaFromValues(
            self,
            schema: Dict[str, Any],
            values: Dict[str, Any],
    ) -> None:
        for label, value in (values or {}).items():
            label = str(label)

            if (
                    label == SELF_LABEL
                    or label in schema
            ):
                continue

            className = self._getScalarSchemaClassName(
                value
            )

            if className is None:
                continue

            schema[label] = (
                className,
                None,
            )

    @staticmethod
    def _getScalarSchemaClassName(
            value: Any,
    ) -> Optional[str]:
        if isinstance(value, bool):
            return "Boolean"

        if isinstance(value, int):
            return "Integer"

        if isinstance(value, float):
            return "Float"

        if isinstance(value, str):
            return "String"

        return None

    def _addRelationIdentityValues(
            self,
            item: Any,
            values: Dict[str, Any],
    ) -> None:
        for fieldName, getterNames in RELATION_IDENTITY_FIELDS:
            if values.get(fieldName) not in (
                    None,
                    "",
            ):
                continue

            value = self._getFirstGetterValue(
                item,
                getterNames,
            )

            if value is None:
                continue

            values[fieldName] = self._toJsonValue(
                value
            )

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
        if className in ("Integer", "Long"):
            return "integer"

        if className == "Boolean":
            return "boolean"
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

    def _removePostgresqlRuntimeStorageProperties(
            self,
            properties: Dict[str, Any],
    ) -> None:
        """
        Remove SQLite-specific storage metadata from a
        PostgreSQL-native runtime Set.
        """
        if not isinstance(
                properties,
                dict,
        ):
            return

        for propertyName in (
                POSTGRESQL_RUNTIME_STORAGE_PROPERTY_KEYS
        ):
            properties.pop(
                propertyName,
                None,
            )

    def _getSetProperties(self, scipionSet: Any) -> Dict[str, Any]:
        properties: Dict[str, Any] = {
            "className": self._getClassName(scipionSet),
            "moduleName": self._getModuleName(scipionSet),
            "baseClassName": self._getBaseClassName(scipionSet),
            "scipionObjId": self._getSourceObjId(scipionSet),
        }

        isPostgresqlRuntimeSet = self._isPostgresqlRuntimeSet(
            scipionSet
        )

        if not isPostgresqlRuntimeSet:
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

            properties[attrPath] = self._toJsonValue(value)

        getSamplingRate = getattr(scipionSet, "getSamplingRate", None)

        if properties.get("_samplingRate") is None and callable(getSamplingRate):
            firstItem = self._callOptionalGetter(scipionSet, "getFirstItem")
            firstItemSamplingRate = self._callOptionalGetter(firstItem, "getSamplingRate")

            if firstItemSamplingRate is not None:
                properties["_samplingRate"] = self._toJsonValue(firstItemSamplingRate)

        if isPostgresqlRuntimeSet:
            self._removePostgresqlRuntimeStorageProperties(
                properties
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

    def _iterLinkedTomograms(
            self,
            scipionSet: Any,
    ) -> Iterable[Any]:
        """
        Return an iterator over tomograms linked to a Set.

        Some Sets, such as SetOfCoordinates3D, expose
        iterVolumes() before their precedents pointer has been
        assigned. In that state the method legally returns None.
        """
        for methodName in (
                "iterTomograms",
                "iterVolumes",
        ):
            iteratorGetter = getattr(
                scipionSet,
                methodName,
                None,
            )

            if not callable(
                    iteratorGetter
            ):
                continue

            try:
                linkedObjects = (
                    iteratorGetter()
                )

            except Exception:
                continue

            iterator = (
                self
                ._coerceLinkedTomogramIterator(
                    linkedObjects
                )
            )

            if iterator is not None:
                return iterator

        getTomograms = getattr(
            scipionSet,
            "getTomograms",
            None,
        )

        if callable(
                getTomograms
        ):
            try:
                linkedObjects = (
                    getTomograms()
                )

            except Exception:
                linkedObjects = None

            iterator = (
                self
                ._coerceLinkedTomogramIterator(
                    linkedObjects
                )
            )

            if iterator is not None:
                return iterator

        return iter(())

    @staticmethod
    def _coerceLinkedTomogramIterator(
            linkedObjects,
    ):
        """
        Normalize a linked Set, sequence or iterator.

        None means that the link has not been assigned yet.
        """
        if linkedObjects is None:
            return None

        iterItems = getattr(
            linkedObjects,
            "iterItems",
            None,
        )

        if callable(
                iterItems
        ):
            try:
                items = iterItems(
                    iterate=False
                )

            except TypeError:
                try:
                    items = iterItems()

                except Exception:
                    return None

            except Exception:
                return None

            if items is None:
                return None

            try:
                return iter(
                    items
                )

            except TypeError:
                return None

        try:
            return iter(
                linkedObjects
            )

        except TypeError:
            return None

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