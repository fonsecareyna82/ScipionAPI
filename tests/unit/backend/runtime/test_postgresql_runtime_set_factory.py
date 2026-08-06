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
import pytest
from pathlib import Path
from pyworkflow.object import (
    Boolean,
    Float,
    Object,
    Pointer,
    Set,
    String,
)
from app.backend.mapper.scipion_set_mapper import (
    ScipionSetPostgresqlMapper,
)
from app.backend.runtime.postgresql_runtime_set_factory import (
    PostgresqlRuntimeSetFactory,
    PostgresqlRuntimeSetMixin,
)
from app.backend.mapper.postgresql_scipion_item_hydrator import (
    getPostgresqlRuntimeParent,
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

    def hasAlignment(self):
        return False


class ExampleAppendItem(Object):
    def __init__(
            self,
            dim=(64, 64, 1),
            samplingRate=None,
            hasTransform=True,
            hasOddEven=True,
            **kwargs,
    ):
        super().__init__(
            **kwargs
        )
        self._dim = dim
        self._samplingRate = samplingRate
        self._acquisition = None
        self._tsId = None
        self._hasTransformValue = hasTransform
        self._hasOddEvenValue = hasOddEven

    def getDim(self):
        return self._dim

    def getSamplingRate(self):
        return self._samplingRate

    def setSamplingRate(self, value):
        self._samplingRate = value

    def hasAcquisition(self):
        return self._acquisition is not None

    def setAcquisition(self, value):
        self._acquisition = value

    def getAcquisition(self):
        return self._acquisition

    def setTsId(self, value):
        self._tsId = value

    def getTsId(self):
        return self._tsId

    def hasTransform(self):
        return self._hasTransformValue

    def hasOddEven(self):
        return self._hasOddEvenValue


class ExampleAppendSet(Set):
    ITEM_TYPE = ExampleAppendItem

    def __init__(self, **kwargs):
        super().__init__(
            **kwargs
        )
        self._dim = None
        self._samplingRateValue = 2.5
        self._tsIdValue = "TS_001"
        self._acquisitionValue = object()
        self._hasAlignment = Boolean(False)
        self._hasOddEven = Boolean(False)

    def getDim(self):
        return self._dim

    def setDim(self, value):
        self._dim = value

    def getSamplingRate(self):
        return self._samplingRateValue

    def getTsId(self):
        return self._tsIdValue

    def hasAcquisition(self):
        return True

    def getAcquisition(self):
        return self._acquisitionValue

class ExampleLinkedSet(Set):
    ITEM_TYPE = ExampleItem

    def __init__(
            self,
            **kwargs,
    ):
        super().__init__(
            **kwargs
        )

        self._linkedSetPointer = Pointer()

    def getLinkedSet(self):
        return self._linkedSetPointer.get()

    def setLinkedSet(
            self,
            linkedSet,
    ):
        self._linkedSetPointer.set(
            linkedSet
        )



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

        if (
                "FROM scipion_set_tables"
                in normalizedQuery
        ):
            return [
                {
                    "id": 71,
                    "setId": 31,
                    "name": "objects",
                    "alias": "ExampleSet",
                    "tableKind": "root",
                    "parentTableId": None,
                    "parentItemId": None,
                    "itemClassName": (
                        "ExampleItem"
                    ),
                    "properties": {
                        "source": "postgresql",
                        "legacySetTable": True,
                    },
                    "createdAt": None,
                    "updatedAt": None,
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

    def clone(
            self,
            ignoreAttrs=(),
    ):
        clone = self.getClass()()

        clone.copy(
            self,
            ignoreAttrs=ignoreAttrs,
        )

        return clone


def buildNestedRuntimeSet(
        extraPath=None,
        db=None,
):
    parent = FakeParent(
        extraPath=extraPath
    )
    parent.setObjId(5)

    db = (
        db
        if db is not None
        else FakeNestedSetDb()
    )

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

    assert (
        runtimeSet.getClassName()
        == "ExampleSet"
    )

    assert runtimeSet.getObjId() == 44
    assert runtimeSet.getObjParentId() == 5

    assert runtimeSet._objParent is None

    assert (
        runtimeSet
        ._postgresqlRuntimeParentRef()
        is parent
    )

    assert (
        getPostgresqlRuntimeParent(
            runtimeSet
        )
        is parent
    )

    assert runtimeSet.getSamplingRate() == 1.5

    assert (
        runtimeSet.getStreamState()
        == Set.STREAM_CLOSED
    )

    assert runtimeSet.getSize() == 1

    assert (
        runtimeSet.getObjName()
        == "outputParticles"
    )


def test_RuntimeSetExposesNativeClassForSetConstruction():
    _, runtimeSet = buildRuntimeSet()

    setClass = runtimeSet.getClass()
    newSet = setClass()

    assert isinstance(runtimeSet, PostgresqlRuntimeSetMixin)
    assert runtimeSet.__class__ is not ExampleSet
    assert setClass is ExampleSet
    assert type(newSet) is ExampleSet
    assert not isinstance(newSet, PostgresqlRuntimeSetMixin)


def test_RuntimeSetAppendPreservesNativeImageMetadataHooks():
    class FakeWritableMapper:
        def __init__(self):
            self.items = []
            self.snapshots = []

        def isWritable(self):
            return True

        def appendItem(self, item):
            if not item.hasObjId():
                item.setObjId(
                    len(self.items) + 1
                )

            self.snapshots.append({
                "tsId": item.getTsId(),
                "samplingRate": item.getSamplingRate(),
                "acquisition": item.getAcquisition(),
            })
            self.items.append(
                item
            )

            return item.getObjId()

        def count(self):
            return len(
                self.items
            )

    runtimeClass = type(
        "ExampleRuntimeAppendSet",
        (
            PostgresqlRuntimeSetMixin,
            ExampleAppendSet,
        ),
        {
            "__module__": __name__,
        },
    )

    runtimeSet = runtimeClass()
    mapper = FakeWritableMapper()

    runtimeSet._mapper = mapper
    runtimeSet._postgresqlWritable = True
    runtimeSet._postgresqlSupportsNativeWrite = True

    item = ExampleAppendItem(
        dim=(128, 96, 1),
        samplingRate=None,
        hasTransform=True,
        hasOddEven=True,
    )

    runtimeSet.append(
        item
    )

    assert mapper.snapshots == [
        {
            "tsId": "TS_001",
            "samplingRate": 2.5,
            "acquisition": runtimeSet.getAcquisition(),
        }
    ]
    assert item.getObjId() == 1
    assert runtimeSet.getSize() == 1
    assert runtimeSet.getDim() == (
        128,
        96,
        1,
    )
    assert runtimeSet._hasAlignment.get() is True
    assert runtimeSet._hasOddEven.get() is True


def test_RefreshRuntimePropertiesSkipsCallableAliases():
    _, runtimeSet = buildRuntimeSet()

    class FakePropertyMapper:
        def getPropertyKeys(self):
            return [
                "_samplingRate",
                "hasAlignment",
            ]

        def getProperty(self, propertyName):
            return {
                "_samplingRate": 2.5,
                "hasAlignment": True,
            }[propertyName]

    runtimeSet._refreshPostgresqlRuntimeProperties(
        FakePropertyMapper()
    )

    assert runtimeSet.getSamplingRate() == 2.5
    assert runtimeSet.hasAlignment() is False
    assert runtimeSet.getPostgresqlRuntimeProperties() == {
        "_samplingRate": 2.5,
        "_streamState": Set.STREAM_CLOSED,
        "_mapperPath": [
            "/legacy/output.sqlite",
            "",
        ],
        "fileName": "/legacy/output.sqlite",
        "hasAlignment": True,
    }


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

    assert items[0]._objParent is None

    assert (
            items[0]
            ._postgresqlRuntimeParentRef()
            is runtimeSet
    )

    assert items[0]._name.get() == (
        "particle-7"
    )


def test_RuntimeSetCanReloadMapperAfterClose():
    _, runtimeSet = buildRuntimeSet()

    runtimeSet.close()

    assert runtimeSet._mapper is None

    item = runtimeSet.getFirstItem()

    assert (
            runtimeSet.isPostgresqlWritable()
            is False
    )

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
    assert nestedSet._objParent is None

    assert (
        nestedSet
        ._postgresqlRuntimeParentRef()
        is runtimeSet
    )

    children = list(
        nestedSet.iterItems()
    )

    assert (
            nestedSet.isPostgresqlWritable()
            is False
    )

    assert len(children) == 1
    assert isinstance(
        children[0],
        ExampleChildItem,
    )

    assert children[0].getObjParentId() == (
        nestedSet.getObjId()
    )

    assert children[0]._objParent is None

    assert (
        children[0]
        ._postgresqlRuntimeParentRef()
        is nestedSet
    )

    assert children[0]._value.get() == (
        "child-3"
    )
    assert (
        nestedSet
        .supportsPostgresqlNativeWrite()
    )

    assert (
            nestedSet.isPostgresqlWritable()
            is False
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


def test_PointerResolverBuildsExternalSetWithoutMutatingParentOutput():
    targetItem = ExampleItem()

    targetItem.setObjId(
        7
    )

    class FakeExternalSetMapper:
        def __init__(
                self,
        ):
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

    class FakeExternalSet(ExampleSet):
        def __init__(
                self,
        ):
            super().__init__()

            self.mapper = (
                FakeExternalSetMapper()
            )

        def _getMapper(
                self,
        ):
            return self.mapper

        def isPostgresqlRuntimeOutput(
                self,
        ):
            return True

    class FakeRuntimeProtocol(Object):
        def __init__(
                self,
                mapper,
                protocolId,
        ):
            super().__init__()

            self.runtimeMapper = mapper

            self.setObjId(
                protocolId
            )

        def getMapper(
                self,
        ):
            return self.runtimeMapper

    class FakeRuntimeMapper:
        def __init__(
                self,
        ):
            self.projectId = 4
            self.db = object()
            self.selectedProtocolIds = []
            self.targetProtocol = None

        def selectById(
                self,
                protocolId,
        ):
            self.selectedProtocolIds.append(
                protocolId
            )

            if protocolId == 200:
                return self.targetProtocol

            return None

    class FakeProtocolGraphRepository:
        def __init__(
                self,
        ):
            self.calls = []

        def getPersistedSetOutputRowByRuntimeObjectId(
                self,
                mapper,
                projectId,
                runtimeObjectId,
        ):
            self.calls.append({
                "mapper": mapper,
                "projectId": projectId,
                "runtimeObjectId": (
                    runtimeObjectId
                ),
            })

            if runtimeObjectId != 999:
                return None

            return {
                "setId": 32,
                "projectId": 4,
                "protocolDbId": 20,
                "protocolId": "200",
                "objectId": 402,
                "runtimeObjectId": 999,
                "outputName": (
                    "outputTargets"
                ),
                "className": "ExampleSet",
                "itemClassName": (
                    "ExampleItem"
                ),
                "properties": {},
            }

    runtimeMapper = FakeRuntimeMapper()

    sourceProtocol = FakeRuntimeProtocol(
        mapper=runtimeMapper,
        protocolId=100,
    )

    targetProtocol = FakeRuntimeProtocol(
        mapper=runtimeMapper,
        protocolId=200,
    )

    runtimeMapper.targetProtocol = (
        targetProtocol
    )

    originalParentOutput = object()
    targetProtocol.outputTargets = originalParentOutput

    sourceSet = ExampleSet()

    sourceSet.setObjId(
        300
    )

    sourceSet._objParent = sourceProtocol

    sourceSet._postgresqlRuntimeInfo = {
        "projectId": 4,
        "runtimeObjectId": 300,
    }

    externalSet = FakeExternalSet()

    externalSet.setObjId(
        999
    )

    externalSet._objParent = targetProtocol

    externalSet._postgresqlRuntimeInfo = {
        "projectId": 4,
        "runtimeObjectId": 999,
    }

    targetItem._objParent = externalSet
    targetItem._objParentId = 999

    factory = (
        PostgresqlRuntimeSetFactory()
    )

    repository = (
        FakeProtocolGraphRepository()
    )

    factory.protocolGraphRepository = (
        repository
    )

    buildCalls = []

    def buildExternalSet(
            **kwargs,
    ):
        buildCalls.append(
            dict(kwargs)
        )

        return externalSet

    factory.build = buildExternalSet

    resolver = (
        factory._buildPointerResolver(
            db=runtimeMapper.db,
            runtimeSet=sourceSet,
            classRegistry={
                "ExampleSet": ExampleSet,
                "ExampleItem": ExampleItem,
            },
        )
    )

    reference = {
        "targetObjectId": 7,
        "targetParentObjectId": 999,
    }

    assert resolver(
        reference
    ) is targetItem

    # All expensive operations must be cached.
    assert resolver(
        reference
    ) is targetItem

    assert len(
        repository.calls
    ) == 1

    assert (
        repository.calls[0][
            "projectId"
        ]
        == 4
    )

    assert (
        repository.calls[0][
            "runtimeObjectId"
        ]
        == 999
    )

    assert (
        runtimeMapper.selectedProtocolIds
        == [200]
    )

    assert len(
        buildCalls
    ) == 1

    assert (
        buildCalls[0]["parent"]
        is targetProtocol
    )

    assert (
        buildCalls[0]["outputName"]
        == "outputTargets"
    )

    assert targetProtocol.outputTargets is originalParentOutput
    assert externalSet._objParent is targetProtocol

    assert (
        externalSet.mapper.selectedIds
        == [7]
    )

    assert (
        targetItem._objParent
        is externalSet
    )

def test_ClearCachesClosesSetsOnceAndReleasesRuntimeObjects():
    class FakeRuntimeSet:
        def __init__(self):
            self.closeCalls = 0

        def close(self):
            self.closeCalls += 1

    firstSet = FakeRuntimeSet()
    secondSet = FakeRuntimeSet()

    factory = PostgresqlRuntimeSetFactory()

    factory._runtimeSetsByIdentity = {
        (4, 300): firstSet,
        (4, 301): secondSet,
        (4, 302): firstSet,
    }

    factory._runtimeProtocolsByIdentity = {
        (4, 100): object(),
    }

    factory._resolvedPointerTargets = {
        (4, 300, 7): object(),
    }

    factory._resolvingPointerTargets = {
        (4, 301, 8),
    }

    factory.clearCaches()

    assert firstSet.closeCalls == 1
    assert secondSet.closeCalls == 1

    assert factory._runtimeSetsByIdentity == {}
    assert factory._runtimeProtocolsByIdentity == {}
    assert factory._resolvedPointerTargets == {}
    assert factory._resolvingPointerTargets == set()

    # Closing an already cleared factory is safe.
    factory.clearCaches()

    assert firstSet.closeCalls == 1
    assert secondSet.closeCalls == 1


def test_EvictRuntimeSetOnlyReleasesTargetIdentity():
    class FakeRuntimeSet:
        def __init__(self):
            self.closeCalls = 0

        def close(self):
            self.closeCalls += 1

    targetSet = FakeRuntimeSet()
    otherSet = FakeRuntimeSet()

    factory = PostgresqlRuntimeSetFactory()

    factory._runtimeSetsByIdentity = {
        (4, 300): targetSet,
        (4, 301): otherSet,
        (4, 999): targetSet,
    }

    protocol = object()

    factory._runtimeProtocolsByIdentity = {
        (4, 100): protocol,
    }

    targetPointer = object()
    otherPointer = object()
    otherProjectPointer = object()

    factory._resolvedPointerTargets = {
        (4, 300, 7): targetPointer,
        (4, 301, 8): otherPointer,
        (5, 300, 9): otherProjectPointer,
    }

    factory._resolvingPointerTargets = {
        (4, 300, 10),
        (4, 301, 11),
    }

    result = factory.evictRuntimeSet(
        projectId=4,
        runtimeObjectId=300,
        runtimeSet=targetSet,
    )

    assert result is targetSet

    assert targetSet.closeCalls == 1
    assert otherSet.closeCalls == 0

    assert factory._runtimeSetsByIdentity == {
        (4, 301): otherSet,
    }

    assert factory._runtimeProtocolsByIdentity == {
        (4, 100): protocol,
    }

    assert factory._resolvedPointerTargets == {
        (4, 301, 8): otherPointer,
        (5, 300, 9): otherProjectPointer,
    }

    assert factory._resolvingPointerTargets == {
        (4, 301, 11),
    }


def test_BuildCanRefreshExistingRuntimeSetWithoutCaching():
    parent = FakeParent()

    parent.setObjId(
        5
    )

    db = FakeDb()

    factory = PostgresqlRuntimeSetFactory()

    outputInfo = {
        "setId": 31,
        "projectId": 4,
        "objectId": 900,
        "runtimeObjectId": 44,
        "className": "ExampleSet",
        "itemClassName": "ExampleItem",
        "itemsCount": 1,
        "properties": {
            "_samplingRate": 1.5,
            "_streamState": (
                Set.STREAM_CLOSED
            ),
        },
    }

    runtimeSet = factory.build(
        db=db,
        parent=parent,
        outputName="outputParticles",
        outputInfo=outputInfo,
        classes={
            "ExampleSet": ExampleSet,
            "ExampleItem": ExampleItem,
        },
        cache=False,
    )

    assert (
        factory._getCachedRuntimeSet(
            projectId=4,
            runtimeObjectId=44,
        )
        is None
    )

    runtimeSet._samplingRate.set(
        9.5
    )

    outputInfo["properties"][
        "_samplingRate"
    ] = 2.5

    refreshedSet = factory.build(
        db=db,
        parent=parent,
        outputName="outputParticles",
        outputInfo=outputInfo,
        classes={
            "ExampleSet": ExampleSet,
            "ExampleItem": ExampleItem,
        },
        runtimeSet=runtimeSet,
        cache=False,
    )

    assert refreshedSet is runtimeSet
    assert runtimeSet.getSamplingRate() == 2.5

    assert (
        factory._getCachedRuntimeSet(
            projectId=4,
            runtimeObjectId=44,
        )
        is None
    )


def test_ClearRuntimeSetPointerCacheKeepsOtherSets():
    factory = PostgresqlRuntimeSetFactory()

    firstPointerKey = (
        4,
        44,
        7,
    )

    secondPointerKey = (
        4,
        55,
        8,
    )

    factory._resolvedPointerTargets[
        firstPointerKey
    ] = object()

    secondTarget = object()

    factory._resolvedPointerTargets[
        secondPointerKey
    ] = secondTarget

    factory._resolvingPointerTargets.add(
        firstPointerKey
    )

    factory._resolvingPointerTargets.add(
        secondPointerKey
    )

    factory.clearRuntimeSetPointerCache(
        projectId=4,
        runtimeObjectId=44,
    )

    assert firstPointerKey not in (
        factory._resolvedPointerTargets
    )

    assert firstPointerKey not in (
        factory._resolvingPointerTargets
    )

    assert (
        factory._resolvedPointerTargets[
            secondPointerKey
        ]
        is secondTarget
    )

    assert secondPointerKey in (
        factory._resolvingPointerTargets
    )


def test_GetSetPropertiesSerializesRootSetPointer():
    parent = FakeParent()
    parent.setObjId(5)

    targetSet = ExampleSet()
    targetSet.setObjId(
        3_000_000_050
    )
    targetSet.setName(
        "5.outputTiltSeries"
    )
    targetSet._objParent = parent
    targetSet._objParentId = 5

    linkedSet = ExampleLinkedSet()
    linkedSet.setObjId(
        3_000_000_051
    )
    linkedSet.setLinkedSet(
        targetSet
    )

    mapper = (
        ScipionSetPostgresqlMapper(
            db=object()
        )
    )

    properties = mapper._getSetProperties(
        linkedSet
    )

    reference = properties[
        "_linkedSetPointer"
    ]

    assert reference["kind"] == "pointer"

    assert reference[
        "targetObjectId"
    ] == 3_000_000_050

    assert reference[
        "targetParentObjectId"
    ] == 5

    assert reference[
        "targetObjectName"
    ] == "5.outputTiltSeries"

    assert reference[
        "targetClassName"
    ] == "ExampleSet"


def test_BuildHydratesRootSetPointerUsingProtocolOutputIdentity():
    class FakeRuntimeMapper:
        def __init__(self):
            self.projectId = 4
            self.db = FakeDb()

        def selectById(
                self,
                protocolId,
        ):
            return None

    class FakeRuntimeParent(FakeParent):
        def __init__(
                self,
                mapper,
        ):
            super().__init__()

            self.mapper = mapper

        def getMapper(self):
            return self.mapper

    class FakePointerRepository:
        def __init__(self):
            self.runtimeIdCalls = []
            self.protocolOutputCalls = []

        def getPersistedSetOutputRowByRuntimeObjectId(
                self,
                mapper,
                projectId,
                runtimeObjectId,
        ):
            self.runtimeIdCalls.append(
                runtimeObjectId
            )

            return None

        def getPersistedSetOutputRowByProtocolOutput(
                self,
                mapper,
                projectId,
                protocolId,
                outputName,
        ):
            self.protocolOutputCalls.append({
                "projectId": projectId,
                "protocolId": protocolId,
                "outputName": outputName,
            })

            return {
                "setId": 32,
                "projectId": 4,
                "protocolDbId": 20,
                "protocolId": "5",
                "objectId": 402,
                "runtimeObjectId": 999,
                "outputName": (
                    "outputTiltSeries"
                ),
                "className": "ExampleSet",
                "itemClassName": (
                    "ExampleItem"
                ),
                "properties": {},
            }

    runtimeMapper = FakeRuntimeMapper()

    sourceParent = FakeRuntimeParent(
        runtimeMapper
    )

    sourceParent.setObjId(
        6
    )

    targetParent = FakeRuntimeParent(
        runtimeMapper
    )

    targetParent.setObjId(
        5
    )

    targetSet = ExampleSet()
    targetSet.setObjId(
        999
    )
    targetSet._objParent = (
        targetParent
    )
    targetSet._objParentId = 5
    targetSet._postgresqlRuntimeInfo = {
        "projectId": 4,
        "runtimeObjectId": 999,
    }

    factory = (
        PostgresqlRuntimeSetFactory()
    )

    repository = FakePointerRepository()

    factory.protocolGraphRepository = (
        repository
    )

    factory._runtimeSetsByIdentity[
        (
            4,
            999,
        )
    ] = targetSet

    runtimeSet = factory.build(
        db=runtimeMapper.db,
        parent=sourceParent,
        outputName="outputCtfSeries",
        outputInfo={
            "setId": 31,
            "projectId": 4,
            "objectId": 401,
            "runtimeObjectId": 998,
            "className": (
                "ExampleLinkedSet"
            ),
            "itemClassName": (
                "ExampleItem"
            ),
            "properties": {
                "_linkedSetPointer": {
                    "version": 1,
                    "kind": "pointer",
                    "targetObjectId": (
                        3_000_000_050
                    ),
                    "targetParentObjectId": 5,
                    "targetObjectName": (
                        "5.outputTiltSeries"
                    ),
                    "targetClassName": (
                        "ExampleSet"
                    ),
                    "extended": "",
                },
            },
        },
        classes={
            "ExampleLinkedSet": (
                ExampleLinkedSet
            ),
            "ExampleSet": ExampleSet,
            "ExampleItem": ExampleItem,
        },
    )

    assert (
        runtimeSet.getLinkedSet()
        is targetSet
    )

    assert repository.runtimeIdCalls == [
        3_000_000_050,
    ]

    assert repository.protocolOutputCalls == [{
        "projectId": 4,
        "protocolId": 5,
        "outputName": (
            "outputTiltSeries"
        ),
    }]


def test_NestedRuntimeSetResolvesProtocolThroughRuntimeParent():
    parent, runtimeSet = (
        buildNestedRuntimeSet()
    )

    runtimeSet._postgresqlRuntimeInfo[
        "projectId"
    ] = 4

    nestedSet = (
        runtimeSet.getFirstItem()
    )

    factory = (
        PostgresqlRuntimeSetFactory()
    )

    assert (
        factory._findProtocolParent(
            nestedSet
        )
        is parent
    )

    assert (
        factory._getRuntimeProjectId(
            nestedSet
        )
        == 4
    )

def test_NestedSetReloadsLogicalTablesAddedAfterRuntimeBuild():
    db = FakeNestedSetDb()

    childTable = db.logicalTables.pop()

    _, runtimeSet = buildNestedRuntimeSet(
        db=db
    )

    db.logicalTables.append(
        childTable
    )

    nestedSet = runtimeSet.getFirstItem()

    assert isinstance(
        nestedSet,
        ExampleNestedSet,
    )

    children = list(
        nestedSet.iterItems()
    )

    assert len(children) == 1
    assert isinstance(
        children[0],
        ExampleChildItem,
    )

    assert children[0]._value.get() == (
        "child-3"
    )

    assert (
        nestedSet
        .getPostgresqlRuntimeInfo()[
            "tableId"
        ]
        == FakeNestedSetDb.CHILD_TABLE_ID
    )


def test_NestedSetWithoutLogicalTableFailsExplicitly():
    db = FakeNestedSetDb()

    db.rootItemRows.append({
        "id": 602,
        "setId": db.ROOT_SET_ID,
        "scipionItemId": 8,
        "parentItemId": None,
        "enabled": True,
        "label": "series-8",
        "comment": "",
        "creation": None,
        "values": {
            "_name": "series-8",
        },
        "createdAt": None,
        "updatedAt": None,
    })

    _, runtimeSet = buildNestedRuntimeSet(
        db=db
    )

    with pytest.raises(
            RuntimeError,
            match=(
                "PostgreSQL nested set "
                "snapshot is incomplete"
            ),
    ):
        list(
            runtimeSet.iterItems()
        )


def test_RuntimeSetClonePreservesPostgresqlRuntimeState():
    parent, runtimeSet = buildRuntimeSet()
    runtimeSet._postgresqlRuntimeProperties[
        "materializedFileName"
    ] = "/tmp/stale-compatibility.sqlite"

    exposedProperties = (
        runtimeSet.getPostgresqlRuntimeProperties()
    )

    assert (
        "materializedFileName"
        not in exposedProperties
    )

    assert (
        runtimeSet._postgresqlRuntimeProperties[
            "materializedFileName"
        ]
        == "/tmp/stale-compatibility.sqlite"
    )

    runtimeClone = runtimeSet.clone()

    assert (
        runtimeSet._postgresqlRuntimeProperties[
            "materializedFileName"
        ]
        == "/tmp/stale-compatibility.sqlite"
    )

    assert (
        "materializedFileName"
        not in runtimeClone._postgresqlRuntimeProperties
    )

    assert (
        runtimeClone._postgresqlMaterializedFileName
        is None
    )

    assert (
        runtimeClone._postgresqlMaterializedRevision
        is None
    )
    assert runtimeClone is not runtimeSet
    assert isinstance(runtimeClone, PostgresqlRuntimeSetMixin)
    assert runtimeClone.getClass() is ExampleSet
    assert runtimeClone._mapper is None

    assert callable(
        runtimeClone._postgresqlMapperFactory
    )

    assert (
        runtimeClone
        ._postgresqlSqliteMaterializer
        is runtimeSet
        ._postgresqlSqliteMaterializer
    )

    assert (
        runtimeClone
        .getPostgresqlRuntimeInfo()
        == runtimeSet
        .getPostgresqlRuntimeInfo()
    )

    assert (
        runtimeClone
        ._postgresqlRuntimeParentRef()
        is parent
    )

    item = runtimeClone.getFirstItem()

    assert item is not None
    assert item.getObjId() == 7

    assert (
        item
        ._postgresqlRuntimeParentRef()
        is runtimeClone
    )


def test_NestedRuntimeSetCloneCanIterateChildren():
    _, runtimeSet = buildNestedRuntimeSet()

    nestedSet = runtimeSet.getFirstItem()
    nestedClone = nestedSet.clone()

    assert nestedClone is not nestedSet
    assert isinstance(nestedClone, PostgresqlRuntimeSetMixin)
    assert nestedClone.getClass() is ExampleNestedSet
    assert nestedClone._mapper is None

    assert callable(
        nestedClone._postgresqlMapperFactory
    )

    assert (
        nestedClone
        ._postgresqlSqliteMaterializer
        is nestedSet
        ._postgresqlSqliteMaterializer
    )

    children = list(
        nestedClone.iterItems()
    )

    assert len(children) == 1

    assert children[0]._value.get() == (
        "child-3"
    )

    assert (
        children[0]
        ._postgresqlRuntimeParentRef()
        is nestedClone
    )


def test_NestedRuntimeSetCloneCanEnableAppend():
    _, runtimeSet = buildNestedRuntimeSet()

    nestedSet = runtimeSet.getFirstItem()
    nestedClone = nestedSet.clone()

    assert nestedClone is not nestedSet
    assert nestedClone.supportsPostgresqlNativeWrite() is True
    assert nestedClone.isPostgresqlWritable() is False
    assert nestedSet.isPostgresqlWritable() is False

    nestedClone.enableAppend()

    assert nestedClone.isPostgresqlWritable() is True
    assert nestedClone._mapper.isWritable() is True
    assert nestedClone._mapper.tableId == FakeNestedSetDb.CHILD_TABLE_ID

    # Promoting the clone must not change the source object.
    assert nestedSet.isPostgresqlWritable() is False


def test_RuntimeRootSetCanEnablePostgresqlWrite():
    _, runtimeSet = buildRuntimeSet()

    assert (
        runtimeSet
        .supportsPostgresqlNativeWrite()
        is True
    )

    assert (
        runtimeSet
        .isPostgresqlWritable()
        is False
    )

    runtimeInfo = (
        runtimeSet
        .getPostgresqlRuntimeInfo()
    )

    assert (
        runtimeInfo[
            "rootTableId"
        ]
        == 71
    )

    result = (
        runtimeSet
        .enablePostgresqlWrite()
    )

    assert result is runtimeSet

    assert (
        runtimeSet
        .isPostgresqlWritable()
        is True
    )

    assert (
        runtimeSet
        ._mapper
        .isWritable()
        is True
    )

    assert (
        runtimeSet
        ._mapper
        .rootTableId
        == 71
    )

    assert runtimeSet.getSize() == 1
    assert runtimeSet._idCount == 7


def test_NestedRuntimeRootCanEnablePostgresqlWrite():
    _, runtimeSet = (
        buildNestedRuntimeSet()
    )

    # The factory is technically ready to write the
    # root Set and synchronize its nested logical tables.
    assert (
        runtimeSet
        .supportsPostgresqlNativeWrite()
        is True
    )

    # Loading an existing output remains read-only
    # until writing is requested explicitly.
    assert (
        runtimeSet
        .isPostgresqlWritable()
        is False
    )

    result = (
        runtimeSet
        .enablePostgresqlWrite()
    )

    assert result is runtimeSet

    assert (
        runtimeSet
        .isPostgresqlWritable()
        is True
    )

    assert (
        runtimeSet
        ._mapper
        .isWritable()
        is True
    )

    assert (
        runtimeSet
        ._mapper
        .rootTableId
        == FakeNestedSetDb
        .ROOT_TABLE_ID
    )


def test_PromoteNestedSetKeepsSameObjectIdentity():
    factory = (
        PostgresqlRuntimeSetFactory()
    )

    nestedSet = (
        ExampleNestedSet()
    )

    originalIdentity = id(
        nestedSet
    )

    promotedSet = (
        factory
        ._promoteRuntimeSetInstance(
            runtimeSet=nestedSet,
            nativeSetClass=(
                ExampleNestedSet
            ),
        )
    )

    assert promotedSet is nestedSet

    assert id(
        promotedSet
    ) == originalIdentity

    assert isinstance(
        promotedSet,
        ExampleNestedSet,
    )

    assert callable(
        getattr(
            promotedSet,
            "enablePostgresqlWrite",
            None,
        )
    )


def test_AttachLogicalTableMapperCanEnableWrites():
    db = FakeNestedSetDb()

    factory = (
        PostgresqlRuntimeSetFactory()
    )

    setMapper = (
        ScipionSetPostgresqlMapper(
            db=db
        )
    )

    nestedSet = (
        ExampleNestedSet()
    )

    nestedSet.setObjId(
        FakeNestedSetDb.ROOT_ITEM_ID
    )

    factory._promoteRuntimeSetInstance(
        runtimeSet=nestedSet,
        nativeSetClass=(
            ExampleNestedSet
        ),
    )

    factory._configureRuntimeSetCompatibility(
        runtimeSet=nestedSet,
        nativeSetClass=(
            ExampleNestedSet
        ),
        runtimeInfo={
            "setId": (
                FakeNestedSetDb
                .ROOT_SET_ID
            ),
            "tableId": (
                FakeNestedSetDb
                .CHILD_TABLE_ID
            ),
            "parentItemId": (
                FakeNestedSetDb
                .ROOT_ITEM_ID
            ),
            "className": (
                "ExampleNestedSet"
            ),
            "itemClassName": (
                "ExampleChildItem"
            ),
        },
        runtimeProperties={},
        classRegistry={
            "ExampleNestedSet": (
                ExampleNestedSet
            ),
            "ExampleChildItem": (
                ExampleChildItem
            ),
            "String": String,
        },
    )

    factory._attachLogicalTableMapper(
        db=db,
        setMapper=setMapper,
        item=nestedSet,
        row={
            "scipionItemId": (
                FakeNestedSetDb
                .ROOT_ITEM_ID
            ),
        },
        logicalTablesByParentId={
            (
                FakeNestedSetDb
                .ROOT_ITEM_ID
            ): dict(
                db.logicalTables[1]
            ),
        },
        classRegistry={
            "ExampleNestedSet": (
                ExampleNestedSet
            ),
            "ExampleChildItem": (
                ExampleChildItem
            ),
            "String": String,
        },
        writable=True,
    )

    assert (
        nestedSet
        .supportsPostgresqlNativeWrite()
    )

    assert (
        nestedSet
        .isPostgresqlWritable()
    )

    assert (
        nestedSet._mapper.tableId
        == FakeNestedSetDb
        .CHILD_TABLE_ID
    )

    assert (
        nestedSet._mapper.parentItemId
        == FakeNestedSetDb
        .ROOT_ITEM_ID
    )

    assert (
        nestedSet
        .getPostgresqlRuntimeInfo()[
            "tableId"
        ]
        == FakeNestedSetDb
        .CHILD_TABLE_ID
    )


def test_RuntimeNestedItemSerializationRemovesTemporaryMapperPath():
    _, runtimeRootSet = (
        buildNestedRuntimeSet()
    )

    nestedSet = (
        ExampleNestedSet()
    )

    nestedSet.setObjId(
        8
    )

    nestedSet._name.set(
        "series-8"
    )

    nestedSet._mapperPath.set(
        "/tmp/postgresql-runtime-sets/"
        "worker-123/SetOfTiltSeries.sqlite,"
        "series-8"
    )

    serialized = (
        ScipionSetPostgresqlMapper(
            db=object()
        )
        .serializeRuntimeItem(
            item=nestedSet,
            scipionSet=(
                runtimeRootSet
            ),
        )
    )

    values = serialized[
        "values"
    ]

    assert (
        "_mapperPath"
        not in values
    )

    assert (
        values["_name"]
        == "series-8"
    )


def test_WritableRuntimeSetReloadsWritableMapperAfterClose():
    _, runtimeSet = (
        buildNestedRuntimeSet()
    )

    runtimeSet.enablePostgresqlWrite()

    assert (
        runtimeSet.isPostgresqlWritable()
        is True
    )

    runtimeSet.close()

    assert runtimeSet._mapper is None

    # Closing releases the mapper but preserves
    # the canonical output's writable intent.
    assert (
        runtimeSet._postgresqlWritable
        is True
    )

    runtimeSet.load()

    assert (
        runtimeSet.isPostgresqlWritable()
        is True
    )

    assert (
        runtimeSet._mapper.isWritable()
        is True
    )

    assert (
        runtimeSet._mapper.rootTableId
        == FakeNestedSetDb.ROOT_TABLE_ID
    )


def test_WriteReopensWritableMapperAfterStreamingClose(
        monkeypatch,
):
    _, runtimeSet = (
        buildNestedRuntimeSet()
    )

    runtimeSet.enablePostgresqlWrite()
    runtimeSet.close()

    nativeWriteCalls = []
    expectedResult = object()

    def nativeWrite(
            self,
            properties=True,
    ):
        nativeWriteCalls.append(
            properties
        )

        return expectedResult

    monkeypatch.setattr(
        ExampleParentSet,
        "write",
        nativeWrite,
    )

    result = runtimeSet.write()

    assert result is expectedResult

    assert nativeWriteCalls == [
        True,
    ]

    assert (
        runtimeSet.isPostgresqlWritable()
        is True
    )

    assert (
        runtimeSet._mapper.isWritable()
        is True
    )

class RuntimePropertiesMapperStub:
    def __init__(self, events=None):
        self.events = events
        self.properties = {
            "_streamState": Set.STREAM_OPEN,
            "_linkedSetPointer": "91.outputSet",
        }

    def refreshProperties(self):
        pass

    def count(self):
        return 3

    def maxId(self):
        return 3

    def getPropertyKeys(self):
        return list(self.properties)

    def getProperty(self, key, defaultValue=None):
        return self.properties.get(key, defaultValue)

    def close(self):
        if self.events is not None:
            self.events.append("close")


class ForbiddenCloseMaterializer:
    def __getattr__(self, attributeName):
        raise AssertionError(
            "SQLite materializer must not be accessed during PostgreSQL runtime Set close(). "
            "attributeName=%s"
            % attributeName
        )

def test_RefreshPostgresqlRuntimeStatePreservesHydratedPointer():
    factory = PostgresqlRuntimeSetFactory()
    runtimeSetClass = factory._getRuntimeSetClass(ExampleLinkedSet)
    runtimeSet = runtimeSetClass()

    linkedSet = ExampleSet()
    linkedSet.setObjId(91)

    runtimeSet.setLinkedSet(linkedSet)

    mapper = RuntimePropertiesMapperStub()
    runtimeSet._mapper = mapper
    runtimeSet._postgresqlMapperFactory = lambda writable=False: mapper
    runtimeSet._postgresqlRuntimeProperties = {}

    runtimeSet.refreshPostgresqlRuntimeState()

    assert runtimeSet.getSize() == 3
    assert runtimeSet._idCount == 3
    assert runtimeSet.isStreamOpen()
    assert runtimeSet.getLinkedSet() is linkedSet
    assert runtimeSet._postgresqlRuntimeProperties["_linkedSetPointer"] == "91.outputSet"

    compatibilitySet = ExampleLinkedSet()
    compatibilitySet.copy(
        runtimeSet,
        copyId=True,
        ignoreAttrs=["_mapperPath", "_size", "_objParent"],
    )

    assert compatibilitySet.getLinkedSet() is linkedSet


def test_CloseDoesNotRefreshExistingCompatibilitySnapshot():
    events = []
    mapper = RuntimePropertiesMapperStub(events=events)

    factory = PostgresqlRuntimeSetFactory()
    runtimeSetClass = factory._getRuntimeSetClass(ExampleLinkedSet)
    runtimeSet = runtimeSetClass()

    runtimeSet._mapper = mapper
    runtimeSet._postgresqlMaterializedFileName = "/tmp/postgresql-input.sqlite"
    runtimeSet._postgresqlSqliteMaterializer = ForbiddenCloseMaterializer()

    runtimeSet.close()

    assert events == ["close"]
    assert runtimeSet._mapper is None
    assert runtimeSet._postgresqlMaterializedFileName == "/tmp/postgresql-input.sqlite"


def test_RuntimeSetCloseWithoutMapperDoesNotAccessMaterializer():
    factory = PostgresqlRuntimeSetFactory()
    runtimeSetClass = factory._getRuntimeSetClass(ExampleLinkedSet)
    runtimeSet = runtimeSetClass()

    runtimeSet._mapper = None
    runtimeSet._postgresqlMaterializedFileName = "/tmp/compatibility.sqlite"
    runtimeSet._postgresqlSqliteMaterializer = ForbiddenCloseMaterializer()

    runtimeSet.close()

    assert runtimeSet._mapper is None


def test_RuntimeSetLoadHydratesPersistedSetProperties():
    class RuntimeSetStub(
            PostgresqlRuntimeSetMixin,
            Set,
    ):
        ITEM_TYPE = Object

        def __init__(self):
            super().__init__()

            self._samplingRate = Float()

    class RuntimeMapperStub:
        def __init__(self):
            self.properties = {}
            self.closeCalls = 0

        def count(self):
            return 2000

        def maxId(self):
            return 2000

        def getPropertyKeys(self):
            return list(
                self.properties
            )

        def getProperty(
                self,
                propertyName,
                defaultValue=None,
        ):
            return self.properties.get(
                propertyName,
                defaultValue,
            )

        def close(self):
            self.closeCalls += 1

    mapper = RuntimeMapperStub()
    runtimeSet = RuntimeSetStub()

    runtimeSet._postgresqlRuntimeProperties = {
        "_samplingRate": 1.5,
    }

    runtimeSet._postgresqlMapperFactory = (
        lambda: mapper
    )

    runtimeSet._postgresqlWritable = False

    runtimeSet.load()

    assert runtimeSet.getSize() == 2000
    assert runtimeSet._idCount == 2000
    assert runtimeSet._samplingRate.get() == 1.5

    mapper.properties[
        "_samplingRate"
    ] = 2.25

    runtimeSet.close()
    runtimeSet.load()

    assert mapper.closeCalls == 1
    assert runtimeSet._samplingRate.get() == 2.25


def test_RuntimeSetLoadUsesFirstItemSamplingWhenSetPropertyIsMissing():
    class RuntimeItemStub(Object):
        def __init__(self):
            super().__init__()
            self._samplingRate = Float(7.08)

        def getSamplingRate(self):
            return self._samplingRate.get()

    class RuntimeSetStub(
            PostgresqlRuntimeSetMixin,
            Set,
    ):
        ITEM_TYPE = RuntimeItemStub

        def __init__(self):
            super().__init__()
            self._samplingRate = Float()

        def getSamplingRate(self):
            return self._samplingRate.get()

    class RuntimeMapperStub:
        def __init__(self):
            self.firstItem = RuntimeItemStub()

        def count(self):
            return 2000

        def maxId(self):
            return 2000

        def getPropertyKeys(self):
            return [
                "_samplingRate",
            ]

        def getProperty(
                self,
                propertyName,
                defaultValue=None,
        ):
            if propertyName == "_samplingRate":
                return None

            return defaultValue

        def selectFirst(self):
            return self.firstItem

        def close(self):
            pass

    mapper = RuntimeMapperStub()
    runtimeSet = RuntimeSetStub()

    runtimeSet._postgresqlRuntimeProperties = {
        "_samplingRate": None,
    }
    runtimeSet._postgresqlMapperFactory = lambda: mapper
    runtimeSet._postgresqlWritable = False

    runtimeSet.load()

    assert runtimeSet.getSize() == 2000
    assert runtimeSet._idCount == 2000
    assert runtimeSet.getSamplingRate() == 7.08







