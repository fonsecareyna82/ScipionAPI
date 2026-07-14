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
    pass


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


def buildRuntimeSet():
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


def test_RuntimeSetDoesNotExposeLegacySqlite():
    _, runtimeSet = buildRuntimeSet()

    assert runtimeSet.getFileName() is None

    assert (
        runtimeSet.getLegacyFileName()
        == "/legacy/output.sqlite"
    )

    assert runtimeSet.getLegacyMapperPath() == [
        "/legacy/output.sqlite",
        "",
    ]

    assert runtimeSet._mapperPath.isEmpty()


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