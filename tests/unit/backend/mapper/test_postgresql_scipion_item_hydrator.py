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
    Set,
    String,
)

from app.backend.mapper.postgresql_scipion_item_hydrator import (
    PostgresqlScipionItemHydrator,
)
from pwem.objects import (
    Acquisition,
    CTFModel,
    Particle,
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


class ExampleSet(Set):
    ITEM_TYPE = ExampleItem


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


def buildParticleHydrator():
    return PostgresqlScipionItemHydrator(
        itemClassName="Particle",
        columns=[
            {
                "labelProperty": "_ctfModel",
                "className": "CTFModel",
            },
            {
                "labelProperty": (
                    "_ctfModel._defocusU"
                ),
                "className": "Float",
            },
            {
                "labelProperty": (
                    "_ctfModel._defocusV"
                ),
                "className": "Float",
            },
            {
                "labelProperty": (
                    "_ctfModel._defocusAngle"
                ),
                "className": "Float",
            },
            {
                "labelProperty": "_acquisition",
                "className": "Acquisition",
            },
            {
                "labelProperty": (
                    "_acquisition._magnification"
                ),
                "className": "Float",
            },
            {
                "labelProperty": (
                    "_acquisition._voltage"
                ),
                "className": "Float",
            },
            {
                "labelProperty": (
                    "_acquisition"
                    "._sphericalAberration"
                ),
                "className": "Float",
            },
            {
                "labelProperty": (
                    "_acquisition"
                    "._amplitudeContrast"
                ),
                "className": "Float",
            },
        ],
        classes={
            "Particle": Particle,
            "CTFModel": CTFModel,
            "Acquisition": Acquisition,
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


def test_BuildKeepsRuntimeParentOutOfScipionObjectGraph():
    parent = Object()
    parent.setObjId(
        9
    )

    item = buildHydrator(
        parent=parent,
    ).build({
        "scipionItemId": 17,
        "values": {},
    })

    assert item._objParent is None
    assert item.getObjParentId() == 9

    assert (
        item
        ._postgresqlRuntimeParentRef()
        is parent
    )

    clonedItem = item.clone()

    assert clonedItem._objParent is None

    assert not hasattr(
        clonedItem,
        "_postgresqlRuntimeParentRef",
    )

    assert all(
        not str(path).startswith(
            "_objParent"
        )
        for path in clonedItem.getObjDict(
            includeClass=True
        )
    )


def test_HydratedItemCloneDoesNotPersistRuntimeParentGraph(
        tmp_path,
):
    runtimeProtocol = Object()

    runtimeProtocol._prerequisites = (
        String("10")
    )

    runtimeSet = Object()
    runtimeSet.setObjId(
        9
    )

    runtimeSet._objParent = (
        runtimeProtocol
    )

    item = buildHydrator(
        parent=runtimeSet,
    ).build({
        "scipionItemId": 17,
        "values": {
            "_name": "item-17",
        },
    })

    clonedItem = item.clone()

    itemSchema = clonedItem.getObjDict(
        includeClass=True
    )

    assert all(
        "_objParent"
        not in str(path)
        for path in itemSchema
    )

    assert all(
        "_prerequisites"
        not in str(path)
        for path in itemSchema
    )

    outputSet = ExampleSet(
        filename=str(
            tmp_path
            / "output.sqlite"
        ),
        classesDict={
            "ExampleItem": ExampleItem,
            "ExampleSet": ExampleSet,
            "NestedMetadata": NestedMetadata,
            "Integer": Integer,
            "String": String,
        },
    )

    try:
        outputSet.append(
            clonedItem
        )

        outputSet.write()
        outputSet.close()

        # Force the same schema reconstruction
        # performed by getFirstItem() in IMOD.
        outputSet.load()

        storedItem = (
            outputSet.getFirstItem()
        )

        assert storedItem is not None
        assert storedItem.getObjId() == 17

        assert storedItem._name.get() == (
            "item-17"
        )

    finally:
        outputSet.close()


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


def test_BuildKeepsMissingOptionalObjectAsNone():
    item = buildHydrator().build({
        "scipionItemId": 17,
        "values": {
            "_name": "item-17",
        },
    })

    assert item._nested is None


def test_BuildConstructsOptionalParentFromChildPath():
    item = buildHydrator().build({
        "scipionItemId": 17,
        "values": {
            "_name": "item-17",
            "_nested._score": 42,
        },
    })

    assert isinstance(
        item._nested,
        NestedMetadata,
    )

    assert item._nested._score.get() == 42


def test_BuildHydratesParticleOptionalObjectsPerRow():
    hydrator = buildParticleHydrator()

    particleWithMetadata = hydrator.build({
        "scipionItemId": 1,
        "values": {
            "_ctfModel": None,
            "_ctfModel._defocusU": 15000.0,
            "_ctfModel._defocusV": 14000.0,
            "_ctfModel._defocusAngle": 25.0,

            "_acquisition": None,
            "_acquisition._magnification": (
                100000.0
            ),
            "_acquisition._voltage": 300.0,
            "_acquisition"
            "._sphericalAberration": 2.7,
            "_acquisition"
            "._amplitudeContrast": 0.1,
        },
    })

    particleWithoutMetadata = hydrator.build({
        "scipionItemId": 2,
        "values": {},
    })

    assert particleWithMetadata.hasCTF()
    assert (
        particleWithMetadata
        .getCTF()
        .getDefocusU()
        == 15000.0
    )
    assert (
        particleWithMetadata
        .getCTF()
        .getDefocusV()
        == 14000.0
    )
    assert (
        particleWithMetadata
        .getCTF()
        .getDefocusAngle()
        == 25.0
    )

    assert particleWithMetadata.hasAcquisition()
    assert (
        particleWithMetadata
        .getAcquisition()
        .getVoltage()
        == 300.0
    )
    assert (
        particleWithMetadata
        .getAcquisition()
        .getMagnification()
        == 100000.0
    )

    # Both rows share the same Set schema, but the second
    # Particle does not contain either optional Object.
    assert not particleWithoutMetadata.hasCTF()
    assert (
        particleWithoutMetadata.getCTF()
        is None
    )
    assert (
        particleWithoutMetadata.getAcquisition()
        is None
    )