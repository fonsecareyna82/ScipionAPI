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

from pyworkflow.object import (
    Integer,
    Object,
    Pointer,
    PointerList,
    String,
)

from app.backend.mapper.postgresql_scipion_item_hydrator import (
    PostgresqlScipionItemHydrator,
)


class NestedMetadata(Object):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._score = Integer()


class ExampleItem(Object):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._name = String()
        self._nested = None


class ExamplePointerItem(Object):
    def __init__(
            self,
            **kwargs,
    ):
        super().__init__(
            **kwargs
        )

        self._single = Pointer()
        self._many = PointerList()


def buildHydrator(parent=None):
    return PostgresqlScipionItemHydrator(
        itemClassName="ExampleItem",
        columns=[
            {
                "labelProperty": "_name",
                "className": "String",
            },
            {
                "labelProperty": "_nested",
                "className": "NestedMetadata",
            },
            {
                "labelProperty": "_nested._score",
                "className": "Integer",
            },
        ],
        parent=parent,
        classes={
            "ExampleItem": ExampleItem,
            "NestedMetadata": NestedMetadata,
        },
    )


def test_BuildReturnsNativeScipionItem():
    item = buildHydrator().build({
        "scipionItemId": 17,
        "enabled": True,
        "label": "item-17",
        "comment": "hydrated",
        "values": {
            "_name": "particle-17",
            "_nested": None,
            "_nested._score": 42,
        },
    })

    assert isinstance(item, ExampleItem)
    assert item.getObjId() == 17
    assert item.getObjLabel() == "item-17"
    assert item.getObjComment() == "hydrated"
    assert item.isEnabled() is True
    assert item._name.get() == "particle-17"
    assert isinstance(item._nested, NestedMetadata)
    assert item._nested._score.get() == 42


def test_BuildAttachesParentRuntimeSet():
    parent = Object()
    parent.setObjId(9)

    item = buildHydrator(
        parent=parent,
    ).build({
        "scipionItemId": 17,
        "values": {},
    })

    assert item._objParent is parent
    assert item.getObjParentId() == 9


def test_BuildKeepsUnmappedPostgresqlValues():
    item = buildHydrator().build({
        "scipionItemId": 17,
        "values": {
            "_name": "particle-17",
            "bottomLeftX": 12.5,
        },
    })

    assert item._name.get() == "particle-17"
    assert item._postgresqlRuntimeValues["bottomLeftX"] == 12.5
    assert not hasattr(item, "bottomLeftX")


def test_UnknownItemClassFailsExplicitly():
    with pytest.raises(
            ValueError,
            match="UnknownItem",
    ):
        PostgresqlScipionItemHydrator(
            itemClassName="UnknownItem",
            columns=[],
            classes={},
        )


def test_BuildHydratesNativePointerAttributes():
    firstTarget = Object()
    firstTarget.setObjId(
        7
    )

    secondTarget = Object()
    secondTarget.setObjId(
        8
    )

    targets = {
        7: firstTarget,
        8: secondTarget,
    }

    resolvedReferences = []

    def resolvePointer(
            reference,
    ):
        resolvedReferences.append(
            dict(reference)
        )

        return targets.get(
            reference.get(
                "targetObjectId"
            )
        )

    hydrator = (
        PostgresqlScipionItemHydrator(
            itemClassName=(
                "ExamplePointerItem"
            ),
            columns=[
                {
                    "labelProperty": (
                        "_single"
                    ),
                    "className": "Pointer",
                },
                {
                    "labelProperty": (
                        "_many"
                    ),
                    "className": (
                        "PointerList"
                    ),
                },
            ],
            classes={
                "ExamplePointerItem": (
                    ExamplePointerItem
                ),
            },
            pointerResolver=resolvePointer,
        )
    )

    item = hydrator.build({
        "scipionItemId": 21,
        "values": {
            "_single": {
                "version": 1,
                "kind": "pointer",
                "targetObjectId": 7,
                "targetParentObjectId": 300,
                "extended": "payload",
            },
            "_many": [
                {
                    "version": 1,
                    "kind": "pointer",
                    "targetObjectId": 7,
                    "targetParentObjectId": 300,
                    "extended": "",
                },
                {
                    "version": 1,
                    "kind": "pointer",
                    "targetObjectId": 8,
                    "targetParentObjectId": 300,
                    "extended": "child",
                },
            ],
        },
    })

    assert isinstance(
        item._single,
        Pointer,
    )

    assert (
        item._single.getObjValue()
        is firstTarget
    )

    assert (
        item._single.getExtended()
        == "payload"
    )

    assert isinstance(
        item._many,
        PointerList,
    )

    assert len(
        item._many
    ) == 2

    assert (
        item._many[0].getObjValue()
        is firstTarget
    )

    assert (
        item._many[1].getObjValue()
        is secondTarget
    )

    assert (
        item._many[1].getExtended()
        == "child"
    )

    assert len(
        resolvedReferences
    ) == 3


def test_BuildPreservesUnresolvedPointerReference():
    hydrator = (
        PostgresqlScipionItemHydrator(
            itemClassName=(
                "ExamplePointerItem"
            ),
            columns=[
                {
                    "labelProperty": (
                        "_single"
                    ),
                    "className": "Pointer",
                },
            ],
            classes={
                "ExamplePointerItem": (
                    ExamplePointerItem
                ),
            },
            pointerResolver=(
                lambda reference: None
            ),
        )
    )

    reference = {
        "version": 1,
        "kind": "pointer",
        "targetObjectId": 17,
        "targetParentObjectId": 999,
        "targetClassName": "Particle",
        "targetParentClassName": (
            "SetOfParticles"
        ),
        "extended": "",
    }

    item = hydrator.build({
        "scipionItemId": 21,
        "values": {
            "_single": reference,
        },
    })

    assert isinstance(
        item._single,
        Pointer,
    )

    assert (
        item._single.getObjValue()
        is None
    )

    assert (
        item._single
        ._postgresqlRuntimeReference
        == reference
    )