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
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional

import pytest

from app.backend.mapper.scipion_object_mapper import (
    ScipionObjectPostgresqlMapper,
)
from app.backend.mapper.scipion_set_mapper import (
    NESTED_LOGICAL_TABLES_VERSION,
    SET_PROPERTIES_VERSION,
    ScipionSetPostgresqlMapper,
)


def _normalizeSql(query: str) -> str:
    return " ".join(str(query or "").split())


class FakeCursor:
    def __init__(self, rowcount: int = 0):
        self.rowcount = rowcount


class RecordingDb:
    """Small database fake for mapper unit tests."""

    def __init__(
            self,
            rowcounts: Optional[Dict[str, int]] = None,
    ):
        self.calls: List[Dict[str, Any]] = []
        self.transactionEvents: List[str] = []
        self.rowcounts = rowcounts or {}

    @contextmanager
    def transaction(self):
        self.transactionEvents.append("begin")

        try:
            yield
        except Exception:
            self.transactionEvents.append("rollback")
            raise
        else:
            self.transactionEvents.append("commit")

    def execute(
            self,
            query,
            params=None,
            commit=True,
    ):
        normalizedQuery = _normalizeSql(query)

        self.calls.append({
            "query": normalizedQuery,
            "params": params,
            "commit": commit,
        })

        rowcount = 0

        for queryFragment, configuredRowcount in self.rowcounts.items():
            if queryFragment in normalizedQuery:
                rowcount = configuredRowcount
                break

        return FakeCursor(rowcount=rowcount)


class FakeItem:
    def __init__(self, itemId: int):
        self.itemId = itemId

    def getObjId(self) -> int:
        return self.itemId


class FakeRelationIdentityItem:
    def getObjId(self):
        return 7

    def getObjDict(
            self,
            includeClass=False,
    ):
        if includeClass:
            return {
                "self": (
                    "TiltSeries",
                    None,
                ),
            }

        return {}

    def getTsId(self):
        return "TS_001"

    def getTomoId(self):
        return "TOMO_001"


class FakeSyntheticScalarItem:
    def getObjId(self):
        return 8

    def getObjDict(
            self,
            includeClass=False,
    ):
        if includeClass:
            return {
                "self": (
                    "SyntheticItem",
                    None,
                ),
            }

        return {
            "_micName": "mic_001",
            "_index": 3,
            "_samplingRate": 2.5,
            "_enabledFlag": True,
            "_matrix": [
                1,
                2,
                3,
            ],
        }


class FakeSet:
    pass


def test_RelationIdentityFieldsAreIncludedInItemSchema():
    mapper = ScipionSetPostgresqlMapper(
        RecordingDb()
    )

    item = FakeRelationIdentityItem()

    schema = mapper._getCompleteItemSchema(
        item
    )

    values = mapper._getItemValues(
        item
    )

    columns = {
        column["labelProperty"]: column
        for column in mapper._getSetColumns(
            schema
        )
    }

    assert schema["_tsId"] == (
        "String",
        None,
    )
    assert schema["_tomoId"] == (
        "String",
        None,
    )

    assert values["_tsId"] == "TS_001"
    assert values["_tomoId"] == "TOMO_001"

    assert columns["_tsId"]["valueType"] == "text"
    assert columns["_tomoId"]["valueType"] == "text"


def test_ArbitraryScalarValuesCompleteItemSchema():
    mapper = ScipionSetPostgresqlMapper(
        RecordingDb()
    )

    item = FakeSyntheticScalarItem()

    schema = mapper._getCompleteItemSchema(
        item
    )

    columns = {
        column["labelProperty"]: column
        for column in mapper._getSetColumns(
            schema
        )
    }

    assert schema["_micName"] == (
        "String",
        None,
    )

    assert schema["_index"] == (
        "Integer",
        None,
    )

    assert schema["_samplingRate"] == (
        "Float",
        None,
    )

    assert schema["_enabledFlag"] == (
        "Boolean",
        None,
    )

    assert "_matrix" not in schema

    assert columns["_micName"]["valueType"] == "text"
    assert columns["_index"]["valueType"] == "integer"
    assert columns["_samplingRate"]["valueType"] == "float"
    assert columns["_enabledFlag"]["valueType"] == "boolean"


class SnapshotSetMapper(ScipionSetPostgresqlMapper):
    """Harness that records storeSet orchestration without PostgreSQL."""

    def __init__(
            self,
            itemIds: Iterable[int],
            existingSet: Optional[Dict[str, Any]] = None,
            staleObjectsDeleted: int = 0,
    ):
        super().__init__(RecordingDb())

        self.items = [
            FakeItem(itemId)
            for itemId in itemIds
        ]
        self.existingSet = existingSet
        self.staleObjectsDeleted = staleObjectsDeleted

        self.events: List[Dict[str, Any]] = []
        self.deleteStaleTreeArgs = None

    def _record(
            self,
            name: str,
            **payload,
    ) -> None:
        self.events.append({
            "name": name,
            **payload,
        })

    @staticmethod
    def _nextOrNone(iterator):
        return next(iterator, None)

    def _resolveProtocolDbId(
            self,
            projectId: int,
            protocolDbId: int,
    ) -> int:
        return int(protocolDbId)

    def _getSetItemsCountHint(
            self,
            scipionSet,
    ) -> Optional[int]:
        return len(self.items)

    def _getSetMaxItemIdHint(
            self,
            scipionSet,
    ) -> Optional[int]:
        if not self.items:
            return None

        return max(
            item.getObjId()
            for item in self.items
        )

    def _getSetSourceMTime(
            self,
            scipionSet,
    ) -> Optional[float]:
        return None

    def _getExistingSet(
            self,
            projectId: int,
            protocolDbId: int,
            outputName: str,
    ) -> Optional[Dict[str, Any]]:
        return self.existingSet

    def hasStoredSetTables(
            self,
            setId: int,
    ) -> bool:
        return False

    def registerObjectTypeFromObject(
            self,
            *args,
            **kwargs,
    ):
        self._record("register_type")
        return {}

    def _iterSetItems(
            self,
            scipionSet,
    ):
        return iter(self.items)

    def _getItemSchema(
            self,
            item,
    ) -> Dict[str, Any]:
        return {
            "_objId": {
                "className": "Integer",
            },
        }

    def _getItemClassName(
            self,
            firstItem,
            itemSchema,
            scipionSet=None,
    ) -> str:
        return "Particle"

    def _getSetColumns(
            self,
            itemSchema,
    ) -> List[Dict[str, Any]]:
        return [
            {
                "labelProperty": "_objId",
                "columnName": "id",
                "className": "Integer",
                "valueType": "integer",
                "position": 0,
                "indexed": True,
            },
        ]

    def _getSetProperties(
            self,
            scipionSet,
    ) -> Dict[str, Any]:
        return {
            "samplingRate": 1.5,
        }

    def _storeObjectNode(
            self,
            projectId: int,
            protocolDbId: int,
            scipionObj,
            name: str,
            path: str,
            parentObjectId,
            storedPaths: List[str],
            includeNestedProperties: bool,
            visited,
    ) -> int:
        self._record(
            "store_root_object",
            path=path,
        )
        storedPaths.append(path)
        return 101

    def _upsertSet(
            self,
            **kwargs,
    ) -> int:
        self._record(
            "upsert_set",
            kwargs=kwargs,
        )
        return 202

    def _deleteStaleObjectTreePaths(
            self,
            **kwargs,
    ) -> int:
        self.deleteStaleTreeArgs = kwargs

        self._record(
            "delete_stale_tree_paths",
            kwargs=kwargs,
        )

        return self.staleObjectsDeleted

    def _replaceStoredSetSnapshot(
            self,
            setId: int,
    ) -> None:
        self._record(
            "replace_set_snapshot",
            setId=setId,
        )

    def _upsertSetColumns(
            self,
            setId: int,
            columns: List[Dict[str, Any]],
    ) -> None:
        self._record(
            "write_set_columns",
            setId=setId,
            columns=columns,
        )

    def _upsertSetTable(
            self,
            **kwargs,
    ) -> int:
        self._record(
            "write_root_table",
            kwargs=kwargs,
        )
        return 303

    def _upsertSetTableColumns(
            self,
            tableId: int,
            columns: List[Dict[str, Any]],
    ) -> None:
        self._record(
            "write_root_table_columns",
            tableId=tableId,
            columns=columns,
        )

    def _upsertSetItems(
            self,
            setId: int,
            tableId: Optional[int],
            firstItem,
            remainingItems,
            batchSize: int,
            scipionSet=None,
    ):
        currentItems = [
            firstItem,
            *list(remainingItems),
        ]

        itemIds = [
            item.getObjId()
            for item in currentItems
        ]

        self._record(
            "write_set_items",
            setId=setId,
            tableId=tableId,
            itemIds=itemIds,
        )

        return (
            len(itemIds),
            max(itemIds) if itemIds else None,
        )

    def _updateSetProperties(
            self,
            setId: int,
            properties: Dict[str, Any],
    ) -> None:
        self._record(
            "update_set_properties",
            setId=setId,
            properties=properties,
        )

    def _upsertSetProperties(
            self,
            setId: int,
            properties: Dict[str, Any],
    ) -> None:
        self._record(
            "write_set_properties",
            setId=setId,
            properties=properties,
        )

    def _getClassName(
            self,
            obj,
    ) -> str:
        return "SetOfParticles"


def test_CompleteItemSchemaKeepsLegacyOverrideSignature():
    mapper = SnapshotSetMapper(
        itemIds=[
            1,
        ]
    )

    item = FakeItem(
        itemId=1
    )

    schema = mapper._getCompleteItemSchema(
        item,
        scipionSet=FakeSet(),
    )

    assert schema == {
        "_objId": {
            "className": "Integer",
        },
    }


class SnapshotObjectMapper(ScipionObjectPostgresqlMapper):
    """Harness that records storeObjectTree snapshot orchestration."""

    def __init__(
            self,
            currentPaths: Iterable[str],
            conflictingSetsDeleted: int = 0,
            staleObjectsDeleted: int = 0,
    ):
        super().__init__(RecordingDb())

        self.currentPaths = list(currentPaths)
        self.conflictingSetsDeleted = conflictingSetsDeleted
        self.staleObjectsDeleted = staleObjectsDeleted

        self.events: List[Dict[str, Any]] = []
        self.deleteStaleTreeArgs = None
        self.deleteConflictingSetArgs = None

    def _record(
            self,
            name: str,
            **payload,
    ) -> None:
        self.events.append({
            "name": name,
            **payload,
        })

    def registerObjectTypeFromObject(
            self,
            *args,
            **kwargs,
    ):
        self._record("register_type")
        return {}

    def _deleteStoredSetForOutput(
            self,
            **kwargs,
    ) -> int:
        self.deleteConflictingSetArgs = kwargs

        self._record(
            "delete_conflicting_set",
            kwargs=kwargs,
        )

        return self.conflictingSetsDeleted

    def _storeObjectNode(
            self,
            projectId: int,
            protocolDbId: int,
            scipionObj,
            name: str,
            path: str,
            parentObjectId,
            storedPaths: List[str],
            includeNestedProperties: bool,
            visited,
    ) -> int:
        self._record(
            "store_object_tree",
            rootPath=path,
        )

        storedPaths.extend(
            self.currentPaths
        )

        return 404

    def _deleteStaleObjectTreePaths(
            self,
            **kwargs,
    ) -> int:
        self.deleteStaleTreeArgs = kwargs

        self._record(
            "delete_stale_tree_paths",
            kwargs=kwargs,
        )

        return self.staleObjectsDeleted


def _eventNames(events: List[Dict[str, Any]]) -> List[str]:
    return [
        event["name"]
        for event in events
    ]


def test_ReplaceStoredSetSnapshotClearsDependentRows():
    mapper = object.__new__(
        ScipionSetPostgresqlMapper
    )
    mapper.db = RecordingDb()

    mapper._replaceStoredSetSnapshot(
        setId=17,
    )

    assert mapper.db.transactionEvents == []

    assert [
        call["query"]
        for call in mapper.db.calls
    ] == [
        'DELETE FROM scipion_set_tables WHERE "setId" = %s',
        'DELETE FROM scipion_set_items WHERE "setId" = %s',
        'DELETE FROM scipion_set_columns WHERE "setId" = %s',
        'DELETE FROM scipion_set_properties WHERE "setId" = %s',
    ]

    assert all(
        call["params"] == (17,)
        for call in mapper.db.calls
    )

    assert all(
        call["commit"] is False
        for call in mapper.db.calls
    )


def test_MergeStoredObjectMetadataUpdatesSelectedRoot():
    database = RecordingDb(
        rowcounts={
            "UPDATE scipion_objects": 1,
        }
    )

    mapper = ScipionObjectPostgresqlMapper(
        database
    )

    updated = mapper.mergeStoredObjectMetadata(
        projectId=7,
        protocolDbId=31,
        objectDbId=81,
        metadata={
            "artifactMissing": True,
        },
    )

    assert updated == 1

    assert database.transactionEvents == [
        "begin",
        "commit",
    ]

    assert len(database.calls) == 1

    call = database.calls[0]

    assert "UPDATE scipion_objects" in call["query"]
    assert "COALESCE( metadata, '{}'::jsonb )" in call["query"]
    assert "|| %s::jsonb" in call["query"]
    assert '"updatedAt" = NOW()' in call["query"]
    assert "WHERE id = %s" in call["query"]
    assert 'AND "projectId" = %s' in call["query"]
    assert 'AND "protocolDbId" = %s' in call["query"]

    assert call["params"] == (
        '{"artifactMissing": true}',
        81,
        7,
        31,
    )

    assert call["commit"] is False


def test_StoreSetRebuildsSnapshotBeforeWritingCurrentItems():
    mapper = SnapshotSetMapper(
        itemIds=[1, 2, 3],
        existingSet={
            "id": 202,
            "objectId": 101,
            "setClassName": "SetOfParticles",
            "itemClassName": "Particle",
            "properties": {
                "incremental": True,
                "nestedTablesVersion": (
                    NESTED_LOGICAL_TABLES_VERSION
                ),
                "itemsCount": 4,
                "maxItemId": 4,
            },
        },
        staleObjectsDeleted=2,
    )

    result = mapper.storeSet(
        projectId=1,
        protocolDbId=10,
        outputName="outputParticles",
        scipionSet=FakeSet(),
        registerType=False,
    )

    eventNames = _eventNames(
        mapper.events
    )

    assert (
        eventNames.index(
            "delete_stale_tree_paths"
        )
        < eventNames.index(
            "replace_set_snapshot"
        )
        < eventNames.index(
            "write_set_columns"
        )
        < eventNames.index(
            "write_set_items"
        )
        < eventNames.index(
            "write_set_properties"
        )
    )

    assert result["itemsCount"] == 3
    assert result["maxItemId"] == 3
    assert result["snapshotReplaced"] is True
    assert result["staleObjectsDeleted"] == 2
    assert result["skipped"] is False


def test_StoreEmptySetClearsPreviouslyPersistedItems():
    mapper = SnapshotSetMapper(
        itemIds=[],
        existingSet={
            "id": 202,
            "objectId": 101,
            "setClassName": "SetOfParticles",
            "itemClassName": "Particle",
            "properties": {
                "incremental": True,
                "nestedTablesVersion": (
                    NESTED_LOGICAL_TABLES_VERSION
                ),
                "itemsCount": 2,
                "maxItemId": 2,
            },
        },
    )

    result = mapper.storeSet(
        projectId=1,
        protocolDbId=10,
        outputName="outputParticles",
        scipionSet=FakeSet(),
        registerType=False,
    )

    eventNames = _eventNames(
        mapper.events
    )

    assert "replace_set_snapshot" in eventNames
    assert "write_set_items" not in eventNames

    assert result["itemsCount"] == 0
    assert result["maxItemId"] is None
    assert result["snapshotReplaced"] is True
    assert result["skipped"] is False


def test_StoreSetRemovesStaleTreeChildrenBeforeWritingFlatSet():
    mapper = SnapshotSetMapper(
        itemIds=[7],
        existingSet=None,
        staleObjectsDeleted=4,
    )

    result = mapper.storeSet(
        projectId=2,
        protocolDbId=20,
        outputName="outputResult",
        scipionSet=FakeSet(),
        registerType=False,
    )

    eventNames = _eventNames(
        mapper.events
    )

    assert (
        eventNames.index(
            "store_root_object"
        )
        < eventNames.index(
            "delete_stale_tree_paths"
        )
        < eventNames.index(
            "replace_set_snapshot"
        )
    )

    assert mapper.deleteStaleTreeArgs == {
        "projectId": 2,
        "protocolDbId": 20,
        "outputName": "outputResult",
        "storedPaths": [
            "outputResult",
        ],
    }

    assert result["snapshotReplaced"] is False
    assert result["staleObjectsDeleted"] == 4


def test_DeleteStoredSetForOutputUsesOutputIdentity():
    mapper = object.__new__(
        ScipionObjectPostgresqlMapper
    )
    mapper.db = RecordingDb(
        rowcounts={
            "DELETE FROM scipion_sets": 1,
        },
    )

    deleted = mapper._deleteStoredSetForOutput(
        projectId=3,
        protocolDbId=30,
        outputName="outputResult",
    )

    assert deleted == 1
    assert len(mapper.db.calls) == 1

    call = mapper.db.calls[0]

    assert (
        call["query"]
        == (
            'DELETE FROM scipion_sets '
            'WHERE "projectId" = %s '
            'AND "protocolDbId" = %s '
            'AND "outputName" = %s'
        )
    )

    assert call["params"] == (
        3,
        30,
        "outputResult",
    )
    assert call["commit"] is False


def test_DeleteStaleObjectTreePathsKeepsOnlyCurrentSnapshot():
    mapper = object.__new__(
        ScipionObjectPostgresqlMapper
    )
    mapper.db = RecordingDb(
        rowcounts={
            "DELETE FROM scipion_objects": 2,
        },
    )

    deleted = mapper._deleteStaleObjectTreePaths(
        projectId=4,
        protocolDbId=40,
        outputName="outputVolume",
        storedPaths=[
            "outputVolume",
            "outputVolume._filename",
            "outputVolume._samplingRate",
        ],
    )

    assert deleted == 2
    assert len(mapper.db.calls) == 1

    call = mapper.db.calls[0]

    assert (
        "DELETE FROM scipion_objects"
        in call["query"]
    )
    assert (
        '"projectId" = %s'
        in call["query"]
    )
    assert (
        '"protocolDbId" = %s'
        in call["query"]
    )
    assert (
        "path = ANY(%s)"
        in call["query"]
    )

    assert call["params"] == (
        4,
        40,
        "outputVolume",
        "outputVolume",
        "outputVolume",
        [
            "outputVolume",
            "outputVolume._filename",
            "outputVolume._samplingRate",
        ],
    )
    assert call["commit"] is False


def test_StoreObjectTreeDeletesPathsMissingFromCurrentSnapshot():
    mapper = SnapshotObjectMapper(
        currentPaths=[
            "outputVolume",
            "outputVolume._filename",
            "outputVolume._samplingRate",
        ],
        staleObjectsDeleted=2,
    )

    result = mapper.storeObjectTree(
        projectId=5,
        protocolDbId=50,
        outputName="outputVolume",
        scipionObj=object(),
        registerType=False,
        includeNestedProperties=True,
    )

    eventNames = _eventNames(
        mapper.events
    )

    assert (
        eventNames.index(
            "store_object_tree"
        )
        < eventNames.index(
            "delete_stale_tree_paths"
        )
    )

    assert mapper.deleteStaleTreeArgs == {
        "projectId": 5,
        "protocolDbId": 50,
        "outputName": "outputVolume",
        "storedPaths": [
            "outputVolume",
            "outputVolume._filename",
            "outputVolume._samplingRate",
        ],
    }

    assert result["storedObjectsCount"] == 3
    assert result["staleObjectsDeleted"] == 2


def test_StoreObjectTreeDeletesConflictingFlatSetBeforeWriting():
    mapper = SnapshotObjectMapper(
        currentPaths=[
            "outputResult",
            "outputResult.value",
        ],
        conflictingSetsDeleted=1,
    )

    result = mapper.storeObjectTree(
        projectId=6,
        protocolDbId=60,
        outputName="outputResult",
        scipionObj=object(),
        registerType=False,
        includeNestedProperties=True,
    )

    eventNames = _eventNames(
        mapper.events
    )

    assert (
        eventNames.index(
            "delete_conflicting_set"
        )
        < eventNames.index(
            "store_object_tree"
        )
    )

    assert mapper.deleteConflictingSetArgs == {
        "projectId": 6,
        "protocolDbId": 60,
        "outputName": "outputResult",
    }

    assert result["conflictingSetsDeleted"] == 1


def test_SetSyncIsNotSkippedWithoutSourceMTime():
    mapper = object.__new__(
        ScipionSetPostgresqlMapper
    )

    assert mapper._shouldSkipSetSync(
        existingProperties={
            "incremental": True,
            "nestedTablesVersion": (
                NESTED_LOGICAL_TABLES_VERSION
            ),
            "setPropertiesVersion": (
                SET_PROPERTIES_VERSION
            ),
            "itemsCount": 3,
            "maxItemId": 3,
        },
        itemsCountHint=3,
        maxItemIdHint=3,
        sourceMTime=None,
    ) is False


@pytest.mark.parametrize(
    (
        "storedSourceMTime",
        "currentSourceMTime",
        "expected",
    ),
    [
        (100.0, 100.0, True),
        (100.0, 101.0, False),
        (None, 100.0, False),
    ],
)
def test_SetSyncUsesSourceMTimeAsStableSkipSignal(
        storedSourceMTime,
        currentSourceMTime,
        expected,
):
    mapper = object.__new__(
        ScipionSetPostgresqlMapper
    )

    assert mapper._shouldSkipSetSync(
        existingProperties={
            "incremental": True,
            "nestedTablesVersion": (
                NESTED_LOGICAL_TABLES_VERSION
            ),
            "setPropertiesVersion": (
                SET_PROPERTIES_VERSION
            ),
            "itemsCount": 3,
            "maxItemId": 3,
            "sourceMTime": storedSourceMTime,
        },
        itemsCountHint=3,
        maxItemIdHint=3,
        sourceMTime=currentSourceMTime,
    ) is expected