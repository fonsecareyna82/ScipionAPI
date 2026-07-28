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


class DirectCreateBaseSet(Set):
    nativeCreateCalls = []

    @classmethod
    def create(
            cls,
            outputPath,
            prefix=None,
            suffix=None,
            ext=None,
            **kwargs,
    ):
        cls.nativeCreateCalls.append({
            "outputPath": outputPath,
            "prefix": prefix,
            "suffix": suffix,
            "ext": ext,
            "kwargs": kwargs,
        })

        return cls()


class DirectCreateOutputSetStub(
        DirectCreateBaseSet
):
    ITEM_TYPE = ItemStub
    nativeCreateCalls = []


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


class DirectCreateProtocolStub(
    ProtocolStub
):
    _possibleOutputs = {
        "outputTomograms": (
            DirectCreateOutputSetStub
        ),
    }



class TomoProtocolStub:
    def __init__(self):
        self.inserted = []
        self.nativeCreated = []

    def getObjId(self):
        return 18

    def _createSet(
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


def test_TomoCreatorReturnsPostgresqlSetWithoutClassIdentityCheck():
    protocol = TomoProtocolStub()

    runtimeMapper = (
        RuntimeMapperStub()
    )

    adapter = (
        RuntimePostgresqlOutputSetAdapter(
            runtimeMapper=runtimeMapper,
            projectId=4,
            protocol=protocol,
        )
    )

    adapter.install()

    outputSet = protocol._createSet(
        OutputSetStub,
        "tomograms%s.sqlite",
        "",
    )

    assert outputSet.getObjId() == 91

    # The native SQLite creator must not run.
    assert protocol.nativeCreated == []

    assert len(
        runtimeMapper.created
    ) == 1

    assert (
        runtimeMapper.created[0][
            "setClass"
        ]
        is OutputSetStub
    )

    protocol._insertChild(
        "outputTomograms",
        outputSet,
    )

    assert len(
        runtimeMapper.finalized
    ) == 1

    assert (
        runtimeMapper.finalized[0][
            "outputName"
        ]
        == "outputTomograms"
    )

    assert protocol.inserted == [
        (
            "outputTomograms",
            outputSet,
        ),
    ]

    adapter.uninstall()

    assert (
        runtimeMapper.discarded
        == []
    )


def test_IncompatibleCreateSetMethodIsNotPatched():
    class IncompatibleProtocolStub(
            ProtocolStub
    ):
        def _createSet(
                self,
                value,
        ):
            return value

    protocol = (
        IncompatibleProtocolStub()
    )

    originalCreator = (
        protocol._createSet
    )

    adapter = (
        RuntimePostgresqlOutputSetAdapter(
            runtimeMapper=(
                RuntimeMapperStub()
            ),
            projectId=4,
            protocol=protocol,
        )
    )

    adapter.install()

    assert (
        protocol._createSet(7)
        == 7
    )

    assert (
        "_createSet"
        not in adapter._patches
    )

    adapter.uninstall()

    assert (
        protocol._createSet(8)
        == 8
    )


def test_DeclaredOutputClassCreateUsesPostgresqlAndRemovesLegacyFile(
        tmp_path,
):
    DirectCreateOutputSetStub.nativeCreateCalls.clear()

    protocol = (
        DirectCreateProtocolStub()
    )

    runtimeMapper = (
        RuntimeMapperStub()
    )

    legacyPath = (
        tmp_path
        / "tomograms.sqlite"
    )

    legacyPath.write_text(
        "old SQLite",
        encoding="utf-8",
    )

    assert legacyPath.exists()

    assert (
        "create"
        not in
        DirectCreateOutputSetStub
        .__dict__
    )

    adapter = (
        RuntimePostgresqlOutputSetAdapter(
            runtimeMapper=runtimeMapper,
            projectId=4,
            protocol=protocol,
        )
    )

    adapter.install()

    assert (
        "create"
        in
        DirectCreateOutputSetStub
        .__dict__
    )

    outputSet = (
        DirectCreateOutputSetStub
        .create(
            str(tmp_path),
            prefix="tomograms",
            template=(
                "tomograms%s.sqlite"
            ),
            indexes=[
                "_tsId",
            ],
        )
    )

    assert (
        legacyPath.exists()
        is False
    )

    assert outputSet.getObjId() == 91

    assert (
        DirectCreateOutputSetStub
        .nativeCreateCalls
        == []
    )

    assert len(
        runtimeMapper.created
    ) == 1

    assert (
        runtimeMapper.created[0][
            "setClass"
        ]
        is DirectCreateOutputSetStub
    )

    assert (
        runtimeMapper.created[0][
            "constructorKwargs"
        ]
        == {
            "template": (
                "tomograms%s.sqlite"
            ),
            "indexes": [
                "_tsId",
            ],
        }
    )

    protocol._insertChild(
        "outputTomograms",
        outputSet,
    )

    assert (
        runtimeMapper.finalized[0][
            "outputName"
        ]
        == "outputTomograms"
    )

    adapter.uninstall()

    # The subclass originally inherited create().
    # Uninstall must remove the temporary override.
    assert (
        "create"
        not in
        DirectCreateOutputSetStub
        .__dict__
    )

    DirectCreateOutputSetStub.create(
        str(tmp_path),
        prefix="tomograms",
    )

    assert len(
        DirectCreateOutputSetStub
        .nativeCreateCalls
    ) == 1


