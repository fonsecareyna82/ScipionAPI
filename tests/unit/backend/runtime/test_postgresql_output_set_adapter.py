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
    Set,
)

from app.backend.runtime.postgresql_output_set_adapter import (
    RuntimePostgresqlOutputSetAdapter,
)


class ItemStub(Object):
    pass


class OutputSetStub(Set):
    ITEM_TYPE = ItemStub


class NestedItemStub(Set):
    ITEM_TYPE = ItemStub


class NestedOutputSetStub(Set):
    ITEM_TYPE = NestedItemStub


class ProtocolStub:
    def __init__(self):
        self.inserted = []
        self.nativeCreated = []

    def getObjId(self):
        return 17

    def _EMProtocol__createSet(
            self,
            SetClass,
            template,
            suffix,
            **kwargs,
    ):
        self.nativeCreated.append({
            "SetClass": SetClass,
            "template": template,
            "suffix": suffix,
            "kwargs": kwargs,
        })

        return SetClass()

    def _insertChild(
            self,
            key,
            child,
    ):
        self.inserted.append(
            (
                key,
                child,
            )
        )


class RuntimeMapperStub:
    def __init__(self):
        self.created = []
        self.finalized = []
        self.discarded = []

    def getPostgresqlOutputSetCapability(
            self,
            setClass,
    ):
        if setClass is NestedOutputSetStub:
            return {
                "supported": False,
                "reason": "nested_set_items",
            }

        return {
            "supported": True,
            "reason": None,
        }

    def createPostgresqlOutputSet(
            self,
            protocol,
            setClass,
            provisionalOutputName,
            constructorKwargs,
            reservationToken,
    ):
        runtimeSet = setClass()
        runtimeSet.setObjId(91)

        self.created.append({
            "protocol": protocol,
            "setClass": setClass,
            "provisionalOutputName": (
                provisionalOutputName
            ),
            "constructorKwargs": (
                constructorKwargs
            ),
            "reservationToken": (
                reservationToken
            ),
            "runtimeSet": runtimeSet,
        })

        return runtimeSet

    def finalizePostgresqlOutputSet(
            self,
            protocol,
            outputName,
            runtimeSet,
    ):
        self.finalized.append({
            "protocol": protocol,
            "outputName": outputName,
            "runtimeSet": runtimeSet,
        })

        return {
            "setId": 33,
            "outputName": outputName,
        }

    def discardPostgresqlOutputSet(
            self,
            protocol,
            runtimeSet,
    ):
        self.discarded.append(
            runtimeSet
        )

        return True


def test_SpaCreatorReturnsPostgresqlSetAndFinalizesOnInsertChild():
    protocol = ProtocolStub()
    runtimeMapper = RuntimeMapperStub()

    adapter = RuntimePostgresqlOutputSetAdapter(
        runtimeMapper=runtimeMapper,
        projectId=4,
        protocol=protocol,
    )

    adapter.install()

    outputSet = (
        protocol
        ._EMProtocol__createSet(
            OutputSetStub,
            "particles%s.sqlite",
            "",
            indexes=[
                "_classId",
            ],
        )
    )

    assert outputSet.getObjId() == 91

    assert protocol.nativeCreated == []

    assert len(
        runtimeMapper.created
    ) == 1

    protocol._insertChild(
        "outputParticles",
        outputSet,
    )

    assert (
        runtimeMapper.finalized[0][
            "outputName"
        ]
        == "outputParticles"
    )

    assert protocol.inserted == [
        (
            "outputParticles",
            outputSet,
        ),
    ]

    adapter.uninstall()

    assert runtimeMapper.discarded == []


def test_UnsupportedNestedSetUsesNativeCreator():
    protocol = ProtocolStub()
    runtimeMapper = RuntimeMapperStub()

    adapter = RuntimePostgresqlOutputSetAdapter(
        runtimeMapper=runtimeMapper,
        projectId=4,
        protocol=protocol,
    )

    adapter.install()

    outputSet = (
        protocol
        ._EMProtocol__createSet(
            NestedOutputSetStub,
            "classes%s.sqlite",
            "",
        )
    )

    assert isinstance(
        outputSet,
        NestedOutputSetStub,
    )

    assert len(
        protocol.nativeCreated
    ) == 1

    assert runtimeMapper.created == []

    adapter.uninstall()


def test_UnregisteredPostgresqlSetIsDiscarded():
    protocol = ProtocolStub()
    runtimeMapper = RuntimeMapperStub()

    adapter = RuntimePostgresqlOutputSetAdapter(
        runtimeMapper=runtimeMapper,
        projectId=4,
        protocol=protocol,
    )

    adapter.install()

    outputSet = (
        protocol
        ._EMProtocol__createSet(
            OutputSetStub,
            "particles%s.sqlite",
            "",
        )
    )

    adapter.uninstall()

    assert runtimeMapper.discarded == [
        outputSet,
    ]


def test_UninstallRestoresOriginalCreator():
    protocol = ProtocolStub()
    runtimeMapper = RuntimeMapperStub()

    adapter = RuntimePostgresqlOutputSetAdapter(
        runtimeMapper=runtimeMapper,
        projectId=4,
        protocol=protocol,
    )

    adapter.install()
    adapter.uninstall()

    protocol._EMProtocol__createSet(
        OutputSetStub,
        "particles%s.sqlite",
        "",
    )

    assert len(
        protocol.nativeCreated
    ) == 1