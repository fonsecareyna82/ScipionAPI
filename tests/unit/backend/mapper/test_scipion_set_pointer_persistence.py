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
    Object,
    Pointer,
    PointerList,
    String,
)

from app.backend.mapper.scipion_set_mapper import (
    ScipionSetPostgresqlMapper,
)


class ExampleTarget(Object):
    pass


class NestedMetadata(Object):
    def __init__(
            self,
            **kwargs,
    ):
        super().__init__(
            **kwargs
        )

        self._target = Pointer()


class ExampleItem(Object):
    def __init__(
            self,
            **kwargs,
    ):
        super().__init__(
            **kwargs
        )

        self._name = String()
        self._single = Pointer()
        self._many = PointerList()
        self._nested = NestedMetadata()


def buildTarget(
        objectId,
        parent,
):
    target = ExampleTarget()

    target.setObjId(
        objectId
    )

    target._objParent = parent
    target._objParentId = (
        parent.getObjId()
    )

    return target


def buildPointer(
        target,
        extended="",
):
    pointer = Pointer()

    pointer.set(
        target
    )

    if extended:
        pointer.setExtended(
            extended
        )

    return pointer


def buildItem():
    targetSet = Object()

    targetSet.setObjId(
        300
    )

    firstTarget = buildTarget(
        objectId=7,
        parent=targetSet,
    )

    secondTarget = buildTarget(
        objectId=8,
        parent=targetSet,
    )

    item = ExampleItem()

    item.setObjId(
        21
    )

    item._name.set(
        "item-21"
    )

    item._single.set(
        firstTarget
    )

    item._single.setExtended(
        "payload"
    )

    item._many.append(
        buildPointer(
            secondTarget,
            extended="child",
        )
    )

    item._nested._target.set(
        secondTarget
    )

    return (
        item,
        targetSet,
        firstTarget,
        secondTarget,
    )


def test_ItemSchemaIncludesPointerColumns():
    mapper = object.__new__(
        ScipionSetPostgresqlMapper
    )

    item, _, _, _ = buildItem()

    schema = mapper._getItemSchema(
        item
    )

    assert schema[
        "_single"
    ] == (
        "Pointer",
        None,
    )

    assert schema[
        "_many"
    ] == (
        "PointerList",
        None,
    )

    assert schema[
        "_nested._target"
    ] == (
        "Pointer",
        None,
    )

    assert not any(
        str(path).startswith(
            "__item__"
        )
        for path in schema
    )

    columns = mapper._getSetColumns(
        schema
    )

    columnsByPath = {
        column["labelProperty"]: column
        for column in columns
    }

    assert (
        columnsByPath[
            "_single"
        ][
            "valueType"
        ]
        == "pointer"
    )

    assert (
        columnsByPath[
            "_many"
        ][
            "valueType"
        ]
        == "pointer_list"
    )


def test_ItemValuesPersistStructuredPointerIdentity():
    mapper = object.__new__(
        ScipionSetPostgresqlMapper
    )

    (
        item,
        _,
        firstTarget,
        secondTarget,
    ) = buildItem()

    values = mapper._getItemValues(
        item
    )

    singlePointer = values[
        "_single"
    ]

    assert singlePointer == {
        "version": 1,
        "kind": "pointer",
        "targetObjectId": (
            firstTarget.getObjId()
        ),
        "targetClassName": (
            "ExampleTarget"
        ),
        "targetObjectName": None,
        "targetParentObjectId": 300,
        "targetParentClassName": (
            "Object"
        ),
        "extended": "payload",
        "uniqueId": "7.payload",
    }

    assert values[
        "_many"
    ] == [
        {
            "version": 1,
            "kind": "pointer",
            "targetObjectId": (
                secondTarget.getObjId()
            ),
            "targetClassName": (
                "ExampleTarget"
            ),
            "targetObjectName": None,
            "targetParentObjectId": 300,
            "targetParentClassName": (
                "Object"
            ),
            "extended": "child",
            "uniqueId": "8.child",
        }
    ]

    nestedPointer = values[
        "_nested._target"
    ]

    assert nestedPointer[
        "targetObjectId"
    ] == secondTarget.getObjId()

    assert nestedPointer[
        "targetParentObjectId"
    ] == 300

    assert nestedPointer[
        "extended"
    ] == ""

    assert not any(
        str(path).startswith(
            "__item__"
        )
        for path in values
    )


def test_EmptyPointersArePersistedWithoutInventingTargets():
    mapper = object.__new__(
        ScipionSetPostgresqlMapper
    )

    item = ExampleItem()

    values = mapper._getItemValues(
        item
    )

    assert values[
        "_single"
    ][
        "targetObjectId"
    ] is None

    assert values[
        "_single"
    ][
        "targetParentObjectId"
    ] is None

    assert values[
        "_many"
    ] == []

    assert values[
        "_nested._target"
    ][
        "targetObjectId"
    ] is None