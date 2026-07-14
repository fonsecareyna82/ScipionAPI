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
from pathlib import Path
from pyworkflow.object import (
    Float,
    Object,
    Set,
    String,
)

from app.backend.runtime.postgresql_runtime_set_factory import (
    PostgresqlRuntimeSetFactory,
)


class ExampleItem(Object):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._name = String()


class ExampleSet(Set):
    ITEM_TYPE = ExampleItem

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._samplingRate = Float()

    def getSamplingRate(self):
        return self._samplingRate.get()


class FakeParent(Object):
    def __init__(
            self,
            extraPath=None,
            **kwargs,
    ):
        super().__init__(
            **kwargs
        )

        self._extraPath = extraPath

    def getExtraPath(
            self,
            *paths,
    ):
        if self._extraPath is None:
            raise RuntimeError(
                "FakeParent does not have an extra path"
            )

        return str(
            Path(
                self._extraPath
            ).joinpath(
                *paths
            )
        )


class FakeDb:
    def __init__(self):
        self.itemRows = [
            {
                "id": 501,
                "setId": 31,
                "scipionItemId": 7,
                "enabled": True,
                "label": "item-7",
                "comment": "",
                "creation": None,
                "values": {
                    "_name": "particle-7",
                },
                "createdAt": None,
                "updatedAt": None,
            },
        ]

    def fetchAll(self, query, params=None):
        normalizedQuery = " ".join(
            str(query).split()
        )

        if "FROM scipion_set_columns" in normalizedQuery:
            return [
                {
                    "id": 1,
                    "setId": 31,
                    "labelProperty": "_name",
                    "columnName": "c00",
                    "className": "String",
                    "valueType": "text",
                    "position": 0,
                    "indexed": False,
                },
            ]

        if "FROM scipion_set_items" in normalizedQuery:
            return list(
                self.itemRows
            )

        return []

    def fetchOne(self, query, params=None):
        normalizedQuery = " ".join(
            str(query).split()
        )

        if "COUNT(*) AS count" in normalizedQuery:
            return {
                "count": len(self.itemRows),
            }

        if 'MAX("scipionItemId")' in normalizedQuery:
            return {
                "maxItemId": 7,
            }

        if (
                "FROM scipion_set_items" in normalizedQuery
                and '"scipionItemId" = %s' in normalizedQuery
        ):
            requestedId = int(
                params[1]
            )

            for row in self.itemRows:
                if row["scipionItemId"] == requestedId:
                    return dict(row)

        return None


class FakeNestedSetDb:
    ROOT_SET_ID = 41
    ROOT_TABLE_ID = 90
    CHILD_TABLE_ID = 91

    ROOT_ITEM_ID = 7
    CHILD_ITEM_ID = 3

    def __init__(self):
        self.queries = []

        self.rootItemRows = [
            {
                "id": 601,
                "setId": self.ROOT_SET_ID,
                "scipionItemId": self.ROOT_ITEM_ID,
                "parentItemId": None,
                "enabled": True,
                "label": "series-7",
                "comment": "",
                "creation": None,
                "values": {
                    "_name": "series-7",
                },
                "createdAt": None,
                "updatedAt": None,
            },
        ]

        self.childItemRows = [
            {
                "id": 701,
                "tableId": self.CHILD_TABLE_ID,
                "scipionItemId": self.CHILD_ITEM_ID,
                "parentItemId": self.ROOT_ITEM_ID,
                "enabled": True,
                "label": "child-3",
                "comment": "",
                "creation": None,
                "values": {
                    "_value": "child-3",
                },
                "createdAt": None,
                "updatedAt": None,
            },
        ]

        self.logicalTables = [
            {
                "id": self.ROOT_TABLE_ID,
                "setId": self.ROOT_SET_ID,
                "name": "objects",
                "alias": "ExampleParentSet",
                "tableKind": "root",
                "parentTableId": None,
                "parentItemId": None,
                "itemClassName": "ExampleNestedSet",
                "properties": {
                    "source": "postgresql",
                    "legacySetTable": True,
                },
                "createdAt": None,
                "updatedAt": None,
            },
            {
                "id": self.CHILD_TABLE_ID,
                "setId": self.ROOT_SET_ID,
                "name": "series_7_Objects",
                "alias": "series_7_ExampleChildItem",
                "tableKind": "child",
                "parentTableId": self.ROOT_TABLE_ID,
                "parentItemId": self.ROOT_ITEM_ID,
                "itemClassName": "ExampleChildItem",
                "properties": {
                    "source": "postgresql",
                    "parentItemId": self.ROOT_ITEM_ID,
                    "parentClassName": "ExampleNestedSet",
                },
                "createdAt": None,
                "updatedAt": None,
            },
        ]

    def fetchAll(self, query, params=None):
        normalizedQuery = self._normalizeQuery(
            query
        )

        self.queries.append(
            (
                normalizedQuery,
                params,
            )
        )

        if (
                "FROM scipion_set_table_columns"
                in normalizedQuery
        ):
            tableId = int(
                params[0]
            )

            if tableId != self.CHILD_TABLE_ID:
                return []

            return [
                {
                    "id": 201,
                    "tableId": self.CHILD_TABLE_ID,
                    "labelProperty": "_value",
                    "columnName": "c00",
                    "className": "String",
                    "valueType": "text",
                    "position": 0,
                    "indexed": False,
                    "properties": {},
                },
            ]

        if (
                "FROM scipion_set_columns"
                in normalizedQuery
        ):
            setId = int(
                params[0]
            )

            if setId != self.ROOT_SET_ID:
                return []

            return [
                {
                    "id": 101,
                    "setId": self.ROOT_SET_ID,
                    "labelProperty": "_name",
                    "columnName": "c00",
                    "className": "String",
                    "valueType": "text",
                    "position": 0,
                    "indexed": False,
                },
            ]

        if (
                "FROM scipion_set_tables"
                in normalizedQuery
        ):
            setId = int(
                params[0]
            )

            if setId != self.ROOT_SET_ID:
                return []

            return [
                dict(table)
                for table in self.logicalTables
            ]

        if (
                "FROM scipion_set_table_items"
                in normalizedQuery
        ):
            tableId = int(
                params[0]
            )

            if tableId != self.CHILD_TABLE_ID:
                return []

            return [
                dict(row)
                for row in self.childItemRows
            ]

        if (
                "FROM scipion_set_items"
                in normalizedQuery
        ):
            setId = int(
                params[0]
            )

            if setId != self.ROOT_SET_ID:
                return []

            return [
                dict(row)
                for row in self.rootItemRows
            ]

        return []

    def fetchOne(self, query, params=None):
        normalizedQuery = self._normalizeQuery(
            query
        )

        self.queries.append(
            (
                normalizedQuery,
                params,
            )
        )

        if (
                "SELECT properties"
                in normalizedQuery
                and "FROM scipion_set_tables"
                in normalizedQuery
        ):
            tableId = int(
                params[0]
            )

            table = self._findLogicalTable(
                tableId
            )

            if table is None:
                return None

            return {
                "properties": dict(
                    table.get("properties")
                    or {}
                ),
            }

        if "COUNT(*) AS count" in normalizedQuery:
            rows = self._rowsForQuery(
                normalizedQuery,
                params,
            )

            return {
                "count": len(rows),
            }

        if (
                'MAX("scipionItemId") AS "maxItemId"'
                in normalizedQuery
        ):
            rows = self._rowsForQuery(
                normalizedQuery,
                params,
            )

            itemIds = [
                int(row["scipionItemId"])
                for row in rows
            ]

            return {
                "maxItemId": (
                    max(itemIds)
                    if itemIds
                    else None
                ),
            }

        if (
                "FROM scipion_set_table_items"
                in normalizedQuery
        ):
            rows = self._filterRowsByItemId(
                rows=self.childItemRows,
                params=params,
            )

            return (
                dict(rows[0])
                if rows
                else None
            )

        if (
                "FROM scipion_set_items"
                in normalizedQuery
        ):
            rows = self._filterRowsByItemId(
                rows=self.rootItemRows,
                params=params,
            )

            return (
                dict(rows[0])
                if rows
                else None
            )

        return None

    def _rowsForQuery(
            self,
            normalizedQuery,
            params,
    ):
        if (
                "FROM scipion_set_table_items"
                in normalizedQuery
        ):
            tableId = int(
                params[0]
            )

            if tableId == self.CHILD_TABLE_ID:
                return self.childItemRows

            return []

        if (
                "FROM scipion_set_items"
                in normalizedQuery
        ):
            setId = int(
                params[0]
            )

            if setId == self.ROOT_SET_ID:
                return self.rootItemRows

        return []

    def _filterRowsByItemId(
            self,
            rows,
            params,
    ):
        if not params or len(params) < 2:
            return list(
                rows
            )

        requestedItemId = int(
            params[1]
        )

        return [
            row
            for row in rows
            if int(
                row["scipionItemId"]
            ) == requestedItemId
        ]

    def _findLogicalTable(
            self,
            tableId,
    ):
        for table in self.logicalTables:
            if int(table["id"]) == int(tableId):
                return table

        return None

    @staticmethod
    def _normalizeQuery(query):
        return " ".join(
            str(query).split()
        )


class ExampleChildItem(Object):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._value = String()


class ExampleNestedSet(Set):
    ITEM_TYPE = ExampleChildItem

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._name = String()


def buildNestedRuntimeSet(
        extraPath=None,
):
    parent = FakeParent(
        extraPath=extraPath
    )
    parent.setObjId(5)

    db = FakeNestedSetDb()

    runtimeSet = PostgresqlRuntimeSetFactory().build(
        db=db,
        parent=parent,
        outputName="outputTiltSeries",
        outputInfo={
            "setId": 41,
            "objectId": 901,
            "runtimeObjectId": 45,
            "className": "ExampleParentSet",
            "itemClassName": "ExampleNestedSet",
            "itemsCount": 1,
            "properties": {
                "_streamState": Set.STREAM_CLOSED,
            },
        },
        classes={
            "ExampleParentSet": ExampleParentSet,
            "ExampleNestedSet": ExampleNestedSet,
            "ExampleChildItem": ExampleChildItem,
        },
    )

    return parent, runtimeSet


class ExampleParentSet(Set):
    ITEM_TYPE = ExampleNestedSet


def buildRuntimeSet(
        extraPath=None,
):
    parent = FakeParent(
        extraPath=extraPath
    )
    parent.setObjId(5)

    runtimeSet = PostgresqlRuntimeSetFactory().build(
        db=FakeDb(),
        parent=parent,
        outputName="outputParticles",
        outputInfo={
            "setId": 31,
            "objectId": 900,
            "runtimeObjectId": 44,
            "className": "ExampleSet",
            "itemClassName": "ExampleItem",
            "itemsCount": 1,
            "properties": {
                "_samplingRate": 1.5,
                "_streamState": Set.STREAM_CLOSED,
                "_mapperPath": [
                    "/legacy/output.sqlite",
                    "",
                ],
                "fileName": "/legacy/output.sqlite",
            },
        },
        classes={
            "ExampleSet": ExampleSet,
            "ExampleItem": ExampleItem,
        },
    )

    return parent, runtimeSet


def test_BuildReturnsNativeScipionSet():
    parent, runtimeSet = buildRuntimeSet()

    assert isinstance(
        runtimeSet,
        ExampleSet,
    )

    assert runtimeSet.getClassName() == "ExampleSet"
    assert runtimeSet.getObjId() == 44
    assert runtimeSet.getObjParentId() == 5
    assert runtimeSet._objParent is parent

    assert runtimeSet.getSamplingRate() == 1.5
    assert runtimeSet.getStreamState() == Set.STREAM_CLOSED
    assert runtimeSet.getSize() == 1
    assert runtimeSet.getObjName() == "outputParticles"


def test_IterItemsReturnsNativeScipionItems():
    _, runtimeSet = buildRuntimeSet()

    items = list(
        runtimeSet.iterItems()
    )

    assert len(items) == 1
    assert isinstance(
        items[0],
        ExampleItem,
    )

    assert items[0].getObjId() == 7
    assert items[0].getObjParentId() == 44
    assert items[0]._objParent is runtimeSet
    assert items[0]._name.get() == "particle-7"


def test_RuntimeSetCanReloadMapperAfterClose():
    _, runtimeSet = buildRuntimeSet()

    runtimeSet.close()

    assert runtimeSet._mapper is None

    item = runtimeSet.getFirstItem()

    assert isinstance(
        item,
        ExampleItem,
    )

    assert item.getObjId() == 7


def test_RuntimeSetPreservesPostgresqlIdentity():
    _, runtimeSet = buildRuntimeSet()

    info = runtimeSet.getPostgresqlRuntimeInfo()

    assert info["objectId"] == 900
    assert info["runtimeObjectId"] == 44
    assert runtimeSet.isPostgresqlRuntimeOutput() is True


def test_NestedSetItemsUseLogicalTableMapper():
    _, runtimeSet = buildNestedRuntimeSet()

    nestedSet = runtimeSet.getFirstItem()

    assert isinstance(
        nestedSet,
        ExampleNestedSet,
    )

    assert nestedSet._mapper is None
    assert nestedSet.isPostgresqlRuntimeOutput()

    children = list(
        nestedSet.iterItems()
    )

    assert len(children) == 1
    assert isinstance(
        children[0],
        ExampleChildItem,
    )

    assert children[0].getObjParentId() == (
        nestedSet.getObjId()
    )

    assert children[0]._value.get() == (
        "child-3"
    )

def test_NestedSetCanReloadLogicalMapper():
    _, runtimeSet = buildNestedRuntimeSet()

    nestedSet = runtimeSet.getFirstItem()

    list(
        nestedSet.iterItems()
    )

    nestedSet.close()

    assert nestedSet._mapper is None

    child = nestedSet.getFirstItem()

    assert isinstance(
        child,
        ExampleChildItem,
    )


def test_BuildFallsBackToItemTypeWhenItemClassNameIsMissing():
    parent = FakeParent()
    parent.setObjId(5)

    runtimeSet = PostgresqlRuntimeSetFactory().build(
        db=FakeDb(),
        parent=parent,
        outputName="outputParticles",
        outputInfo={
            "setId": 31,
            "objectId": 900,
            "runtimeObjectId": 44,
            "className": "ExampleSet",
            "itemsCount": 1,
            "properties": {},
        },
        classes={
            "ExampleSet": ExampleSet,
            "ExampleItem": ExampleItem,
        },
    )

    item = runtimeSet.getFirstItem()

    assert isinstance(
        item,
        ExampleItem,
    )

def test_LocalPointerResolverSelectsItemFromRuntimeSet():
    targetItem = ExampleItem()

    targetItem.setObjId(
        7
    )

    class FakeTargetMapper:
        def __init__(self):
            self.selectedIds = []

        def selectById(
                self,
                itemId,
        ):
            self.selectedIds.append(
                itemId
            )

            if itemId == 7:
                return targetItem

            return None

    class FakePointerRuntimeSet:
        def __init__(self):
            self.mapper = (
                FakeTargetMapper()
            )

        def getObjId(self):
            return 300

        def _getMapper(self):
            return self.mapper

    runtimeSet = FakePointerRuntimeSet()

    resolver = (
        PostgresqlRuntimeSetFactory()
        ._buildLocalPointerResolver(
            runtimeSet
        )
    )

    reference = {
        "targetObjectId": 7,
        "targetParentObjectId": 300,
    }

    assert resolver(
        reference
    ) is targetItem

    # The second resolution uses the cache.
    assert resolver(
        reference
    ) is targetItem

    assert (
        runtimeSet.mapper.selectedIds
        == [7]
    )

    # A pointer owned by another set is not
    # resolved by the local resolver.
    assert resolver({
        "targetObjectId": 7,
        "targetParentObjectId": 999,
    }) is None

    assert (
        runtimeSet.mapper.selectedIds
        == [7]
    )