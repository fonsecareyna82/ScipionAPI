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
    Object,
    Set,
)

from app.backend.runtime.postgresql_output_set_adapter import (
    RuntimePostgresqlOutputSetAdapter,
)
from app.backend.mapper.postgresql_runtime_mapper import (
    PostgresqlRuntimeMapper,
)
from app.backend.runtime.postgresql_runtime_set_factory import (
    PostgresqlRuntimeSetFactory,
)
from app.backend.runtime.postgresql_runtime_set_sqlite_materializer import (
    PostgresqlRuntimeSetSqliteMaterializer,
)


def _buildRealCapabilityMapper():
    mapper = object.__new__(
        PostgresqlRuntimeMapper
    )

    mapper.runtimeSetFactory = (
        PostgresqlRuntimeSetFactory()
    )

    mapper.dictClasses = {
        "ItemStub": ItemStub,
        "NestedItemStub": NestedItemStub,
        "NestedOutputSetStub": (
            NestedOutputSetStub
        ),
        "DeepNestedItemStub": (
            DeepNestedItemStub
        ),
        "DeepNestedOutputSetStub": (
            DeepNestedOutputSetStub
        ),
    }

    return mapper

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


class DirectCreateUnsupportedOutputSetStub(DirectCreateBaseSet):
    ITEM_TYPE = None
    nativeCreateCalls = []


class NestedItemStub(Set):
    ITEM_TYPE = ItemStub


class NestedOutputSetStub(Set):
    ITEM_TYPE = NestedItemStub


class UnsupportedOutputSetStub(Set):
    ITEM_TYPE = None


class DeepNestedItemStub(Set):
    ITEM_TYPE = NestedItemStub


class DeepNestedOutputSetStub(Set):
    ITEM_TYPE = DeepNestedItemStub


class ProtocolStub:
    def __init__(self):
        self.inserted = []
        self.deleted = []
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

    def _deleteChild(
            self,
            key,
            child,
    ):
        self.deleted.append(
            (
                key,
                child,
            )
        )


class DeclaredOutputProtocolStub(
        ProtocolStub
):
    _possibleOutputs = {
        "outputClasses": NestedOutputSetStub,
    }


class DirectCreateProtocolStub(
    ProtocolStub
):
    _possibleOutputs = {
        "outputTomograms": (
            DirectCreateOutputSetStub
        ),
    }


class DirectCreateUnsupportedProtocolStub(ProtocolStub):
    _possibleOutputs = {
        "outputUnsupported": DirectCreateUnsupportedOutputSetStub,
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
        self.replaced = []
        self.bound = []

    def bindPostgresqlOutputSetAlias(
            self,
            protocol,
            runtimeSet,
            canonicalSet,
    ):
        runtimeSet.setObjId(canonicalSet.getObjId())

        self.bound.append({
            "protocol": protocol,
            "runtimeSet": runtimeSet,
            "canonicalSet": canonicalSet,
        })

        return runtimeSet

    def getPostgresqlOutputSetCapability(
            self,
            setClass,
    ):
        if setClass in {UnsupportedOutputSetStub, DirectCreateUnsupportedOutputSetStub}:
            return {
                "supported": False,
                "reason": (
                    "unresolved_item_class"
                ),
            }

        if setClass is DeepNestedOutputSetStub:
            return {
                "supported": False,
                "reason": (
                    "nested_set_depth_unsupported"
                ),
            }

        if setClass is NestedOutputSetStub:
            return {
                "supported": True,
                "reason": None,
                "storageKind": (
                    "nested_logical_tables"
                ),
                "nestedSetItems": True,
            }

        return {
            "supported": True,
            "reason": None,
            "storageKind": "flat_items",
            "nestedSetItems": False,
        }

    def createPostgresqlOutputSet(
            self,
            protocol,
            setClass,
            provisionalOutputName,
            constructorKwargs,
            reservationToken,
            runtimeSet=None,
    ):
        providedRuntimeSet = runtimeSet

        if runtimeSet is None:
            runtimeSet = setClass()

        runtimeSet.setObjId(91)
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
            "providedRuntimeSet": providedRuntimeSet,
        })

        return runtimeSet

    def finalizePostgresqlOutputSet(
            self,
            protocol,
            outputName,
            runtimeSet,
            metadataSource=None,
    ):
        call = {
            "protocol": protocol,
            "outputName": outputName,
            "runtimeSet": runtimeSet,
        }

        if metadataSource is not None:
            call["metadataSource"] = (
                metadataSource
            )

        self.finalized.append(
            call
        )

        return {
            "setId": 33,
            "outputName": outputName,
            "properties": {
                "itemsCount": (
                    metadataSource.getSize()
                    if metadataSource is not None
                    else runtimeSet.getSize()
                ),
            },
        }

    def replacePostgresqlOutputSetSnapshot(
            self,
            protocol,
            outputName,
            runtimeSet,
            sourceSet,
    ):
        self.replaced.append({
            "protocol": protocol,
            "outputName": outputName,
            "runtimeSet": runtimeSet,
            "sourceSet": sourceSet,
        })

        return runtimeSet

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


def test_InsertChildAdoptsDirectlyConstructedOutputSet():
    class DirectConstructorProtocolStub(
            ProtocolStub
    ):
        _possibleOutputs = {
            "outputMicrographs": OutputSetStub,
        }

    protocol = DirectConstructorProtocolStub()
    runtimeMapper = RuntimeMapperStub()

    adapter = RuntimePostgresqlOutputSetAdapter(
        runtimeMapper=runtimeMapper,
        projectId=4,
        protocol=protocol,
    )

    adapter.install()

    outputSet = OutputSetStub()
    originalIdentity = id(outputSet)

    protocol._insertChild(
        "outputMicrographs",
        outputSet,
    )

    assert id(outputSet) == originalIdentity

    assert protocol.inserted == [
        (
            "outputMicrographs",
            outputSet,
        ),
    ]

    assert len(runtimeMapper.created) == 1
    assert runtimeMapper.created[0]["setClass"] is OutputSetStub
    assert runtimeMapper.created[0]["providedRuntimeSet"] is outputSet
    assert runtimeMapper.created[0]["runtimeSet"] is outputSet

    assert len(runtimeMapper.finalized) == 1
    assert runtimeMapper.finalized[0]["outputName"] == "outputMicrographs"
    assert runtimeMapper.finalized[0]["runtimeSet"] is outputSet

    adapter.uninstall()

    assert runtimeMapper.discarded == []


def test_InsertChildAdoptsPopulatedDirectOutputSet():
    class PopulatedOutputSetStub(
            OutputSetStub
    ):
        def isEmpty(self):
            return False

        def getSize(self):
            return 500

    class DirectConstructorProtocolStub(
            ProtocolStub
    ):
        _possibleOutputs = {
            "outputParticles": (
                PopulatedOutputSetStub
            ),
        }

    protocol = DirectConstructorProtocolStub()
    runtimeMapper = RuntimeMapperStub()

    adapter = RuntimePostgresqlOutputSetAdapter(
        runtimeMapper=runtimeMapper,
        projectId=4,
        protocol=protocol,
    )

    adapter.install()

    outputSet = PopulatedOutputSetStub()
    originalIdentity = id(outputSet)

    protocol._insertChild(
        "outputParticles",
        outputSet,
    )

    assert id(outputSet) == originalIdentity
    assert len(runtimeMapper.created) == 1
    assert len(runtimeMapper.finalized) == 1

    assert (
        adapter
        ._finalizedSetsByOutputName[
            "outputParticles"
        ]
        is outputSet
    )

    adapter.uninstall()

    assert runtimeMapper.discarded == []


def test_NestedSetUsesPostgresqlCreator():
    protocol = ProtocolStub()
    runtimeMapper = RuntimeMapperStub()

    adapter = (
        RuntimePostgresqlOutputSetAdapter(
            runtimeMapper=runtimeMapper,
            projectId=4,
            protocol=protocol,
        )
    )

    adapter.install()

    outputSet = (
        protocol
        ._EMProtocol__createSet(
            NestedOutputSetStub,
            "tiltseries%s.sqlite",
            "",
        )
    )

    assert isinstance(
        outputSet,
        NestedOutputSetStub,
    )

    assert outputSet.getObjId() == 91

    assert protocol.nativeCreated == []

    assert len(
        runtimeMapper.created
    ) == 1

    assert (
        runtimeMapper.created[0][
            "setClass"
        ]
        is NestedOutputSetStub
    )

    protocol._insertChild(
        "outputTiltSeries",
        outputSet,
    )

    assert len(
        runtimeMapper.finalized
    ) == 1

    assert (
        runtimeMapper.finalized[0][
            "outputName"
        ]
        == "outputTiltSeries"
    )

    adapter.uninstall()

    assert runtimeMapper.discarded == []


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
    assert RuntimePostgresqlOutputSetAdapter.DELETE_CHILD_ATTRIBUTE not in adapter._patches

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


def test_UnsupportedDeclaredOutputClassCreateDoesNotFallbackToNativeCreator(tmp_path):
    DirectCreateUnsupportedOutputSetStub.nativeCreateCalls.clear()

    protocol = DirectCreateUnsupportedProtocolStub()
    runtimeMapper = RuntimeMapperStub()
    adapter = RuntimePostgresqlOutputSetAdapter(runtimeMapper=runtimeMapper, projectId=4, protocol=protocol)

    adapter.install()

    assert "create" in DirectCreateUnsupportedOutputSetStub.__dict__

    with pytest.raises(
            NotImplementedError,
            match="Declared output Set cannot be stored natively in PostgreSQL",
    ):
        DirectCreateUnsupportedOutputSetStub.create(str(tmp_path), prefix="unsupported")

    assert DirectCreateUnsupportedOutputSetStub.nativeCreateCalls == []
    assert runtimeMapper.created == []

    adapter.uninstall()

    assert "create" not in DirectCreateUnsupportedOutputSetStub.__dict__


def test_UnsupportedSetDoesNotFallbackToNativeCreator():
    protocol = ProtocolStub()
    runtimeMapper = RuntimeMapperStub()
    adapter = RuntimePostgresqlOutputSetAdapter(runtimeMapper=runtimeMapper, projectId=4, protocol=protocol)

    adapter.install()

    with pytest.raises(
            NotImplementedError,
            match="Declared output Set cannot be stored natively in PostgreSQL",
    ):
        protocol._EMProtocol__createSet(UnsupportedOutputSetStub, "unsupported%s.sqlite", "")

    assert protocol.nativeCreated == []
    assert runtimeMapper.created == []

    adapter.uninstall()


def test_RealCapabilitySupportsNestedLogicalTables():
    mapper = (
        _buildRealCapabilityMapper()
    )

    capability = (
        mapper
        .getPostgresqlOutputSetCapability(
            NestedOutputSetStub
        )
    )

    assert capability == {
        "supported": True,
        "reason": None,
        "storageKind": (
            "nested_logical_tables"
        ),
        "nestedSetItems": True,
        "itemClassName": (
            "NestedItemStub"
        ),
        "childItemClassName": (
            "ItemStub"
        ),
    }


def test_RealCapabilityRejectsDeeperNestedSets():
    mapper = (
        _buildRealCapabilityMapper()
    )

    capability = (
        mapper
        .getPostgresqlOutputSetCapability(
            DeepNestedOutputSetStub
        )
    )

    assert (
        capability["supported"]
        is False
    )

    assert (
        capability["reason"]
        == "nested_set_depth_unsupported"
    )


def test_RealCapabilitySupportsFlatItems():
    mapper = (
        _buildRealCapabilityMapper()
    )

    capability = (
        mapper
        .getPostgresqlOutputSetCapability(
            OutputSetStub
        )
    )

    assert capability == {
        "supported": True,
        "reason": None,
        "storageKind": "flat_items",
        "nestedSetItems": False,
        "itemClassName": "ItemStub",
    }


def test_RepeatedOutputDefinitionRefreshesExistingPostgresqlSet():
    class RepeatedOutputSetStub(
            OutputSetStub
    ):
        def isEmpty(self):
            return False

        def getSize(self):
            return 10

    class RepeatedOutputProtocolStub(
            ProtocolStub
    ):
        _possibleOutputs = {
            "outputParticles": (
                RepeatedOutputSetStub
            ),
        }

    protocol = (
        RepeatedOutputProtocolStub()
    )

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

    firstSnapshot = (
        RepeatedOutputSetStub()
    )

    protocol._insertChild(
        "outputParticles",
        firstSnapshot,
    )

    assert (
        adapter
        ._finalizedSetsByOutputName[
            "outputParticles"
        ]
        is firstSnapshot
    )

    secondSnapshot = (
        RepeatedOutputSetStub()
    )

    # Reproduce Protocol._defineOutputs():
    # delete the previous child first and then insert
    # the newly generated output snapshot.
    protocol._deleteChild(
        "outputParticles",
        secondSnapshot,
    )

    protocol._insertChild(
        "outputParticles",
        secondSnapshot,
    )

    assert protocol.deleted == []

    assert len(
        runtimeMapper.created
    ) == 1

    assert len(
        runtimeMapper.finalized
    ) == 1

    assert runtimeMapper.replaced == [{
        "protocol": protocol,
        "outputName": "outputParticles",
        "runtimeSet": firstSnapshot,
        "sourceSet": secondSnapshot,
    }]

    assert protocol.inserted == [
        (
            "outputParticles",
            firstSnapshot,
        ),
        (
            "outputParticles",
            firstSnapshot,
        ),
    ]

    assert (
        adapter
        ._finalizedSetsByOutputName[
            "outputParticles"
        ]
        is firstSnapshot
    )

    assert (
        adapter
        ._pendingOutputSetReplacements
        == {}
    )

    adapter.uninstall()

    assert runtimeMapper.discarded == []
    assert adapter._createdSets == {}
    assert adapter._finalizedSetsByOutputName == {}
    assert adapter._pendingOutputSetReplacements == {}


def test_DeleteChildDelegatesForUnregisteredNativeSet():
    protocol = ProtocolStub()
    runtimeMapper = RuntimeMapperStub()

    adapter = RuntimePostgresqlOutputSetAdapter(
        runtimeMapper=runtimeMapper,
        projectId=4,
        protocol=protocol,
    )

    adapter.install()

    workingSet = OutputSetStub()

    protocol._deleteChild(
        "workingSet",
        workingSet,
    )

    assert protocol.deleted == [
        (
            "workingSet",
            workingSet,
        ),
    ]

    assert (
        adapter
        ._pendingOutputSetReplacements
        == {}
    )

    adapter.uninstall()


def test_InsertChildPassesThroughNonSetProtocolMetadata():
    protocol = ProtocolStub()
    runtimeMapper = RuntimeMapperStub()

    adapter = RuntimePostgresqlOutputSetAdapter(
        runtimeMapper=runtimeMapper,
        projectId=4,
        protocol=protocol,
    )

    adapter.install()

    outputsMetadata = Object()

    protocol._insertChild(
        "_outputs",
        outputsMetadata,
    )

    assert protocol.inserted == [
        (
            "_outputs",
            outputsMetadata,
        ),
    ]

    assert runtimeMapper.created == []
    assert runtimeMapper.finalized == []
    assert runtimeMapper.replaced == []
    assert runtimeMapper.bound == []

    adapter.uninstall()

    assert runtimeMapper.discarded == []


def test_DirectFilenameSetReusesPostgresqlStorageWithoutCreatingSqlite(
        tmp_path,
):
    class DirectLoadProtocolStub(
            ProtocolStub
    ):
        def getWorkingDir(self):
            return str(
                tmp_path
            )

    protocol = DirectLoadProtocolStub()
    runtimeMapper = RuntimeMapperStub()

    adapter = RuntimePostgresqlOutputSetAdapter(
        runtimeMapper=runtimeMapper,
        projectId=4,
        protocol=protocol,
    )

    storagePath = (
        tmp_path
        / "particles.sqlite"
    )

    adapter.install()

    try:
        firstAlias = OutputSetStub(
            filename=str(storagePath)
        )

        assert storagePath.exists() is False
        assert len(runtimeMapper.created) == 1
        assert len(runtimeMapper.bound) == 1

        canonicalSet = (
            runtimeMapper.created[0][
                "runtimeSet"
            ]
        )

        assert firstAlias is not canonicalSet
        assert (
            firstAlias.getObjId()
            == canonicalSet.getObjId()
        )

        protocol._insertChild(
            "outputParticles",
            firstAlias,
        )

        assert len(
            runtimeMapper.finalized
        ) == 1

        assert (
            runtimeMapper.finalized[0][
                "runtimeSet"
            ]
            is canonicalSet
        )

        assert (
            runtimeMapper.finalized[0][
                "metadataSource"
            ]
            is firstAlias
        )

        secondAlias = OutputSetStub(
            filename=str(storagePath)
        )

        assert storagePath.exists() is False
        assert len(runtimeMapper.created) == 1
        assert len(runtimeMapper.bound) == 2

        protocol._deleteChild(
            "outputParticles",
            secondAlias,
        )

        protocol._insertChild(
            "outputParticles",
            secondAlias,
        )

        assert protocol.deleted == []

        assert len(
            runtimeMapper.finalized
        ) == 2

        assert (
            runtimeMapper.finalized[1][
                "runtimeSet"
            ]
            is canonicalSet
        )

        assert (
            runtimeMapper.finalized[1][
                "metadataSource"
            ]
            is secondAlias
        )

        assert runtimeMapper.replaced == []

        assert protocol.inserted == [
            (
                "outputParticles",
                canonicalSet,
            ),
            (
                "outputParticles",
                canonicalSet,
            ),
        ]

    finally:
        adapter.uninstall()



def test_ManagedCompatibilitySqliteRefreshesBeforeNativeLoad(
        tmp_path,
        monkeypatch,
):
    class CompatibilityInputProtocolStub(
            ProtocolStub
    ):
        def getWorkingDir(self):
            return str(
                tmp_path
                / "Runs"
                / "protocol"
            )

    protocol = CompatibilityInputProtocolStub()
    runtimeMapper = RuntimeMapperStub()

    adapter = RuntimePostgresqlOutputSetAdapter(
        runtimeMapper=runtimeMapper,
        projectId=4,
        protocol=protocol,
    )

    compatibilityPath = (
        tmp_path
        / "postgresql-runtime-sets"
        / "input.sqlite"
    )

    compatibilityPath.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    refreshCalls = []

    def refreshManagedPath(
            cls,
            path,
    ):
        refreshCalls.append(
            str(
                compatibilityPath.resolve()
            )
        )

        assert (
            str(
                compatibilityPath.resolve()
            )
            == str(
                Path(path).resolve()
            )
        )

        return True

    monkeypatch.setattr(
        PostgresqlRuntimeSetSqliteMaterializer,
        "refreshManagedPath",
        classmethod(refreshManagedPath),
    )

    adapter.install()

    inputSet = None

    try:
        inputSet = OutputSetStub(
            filename=str(
                compatibilityPath
            )
        )

        assert refreshCalls == [
            str(
                compatibilityPath.resolve()
            ),
        ]

        assert runtimeMapper.created == []
        assert runtimeMapper.bound == []
        assert runtimeMapper.finalized == []

        internalSet = OutputSetStub()

        internalSet._mapperPath.set(
            "%s, "
            % compatibilityPath
        )

        setattr(
            internalSet,
            PostgresqlRuntimeSetSqliteMaterializer.COMPATIBILITY_BUILD_ATTRIBUTE,
            True,
        )

        result = adapter._loadDirectPostgresqlSet(
            originalLoad=lambda runtimeSet: runtimeSet,
            runtimeSet=internalSet,
        )

        assert result is internalSet

        # Internal materialization must not trigger another refresh.
        assert refreshCalls == [
            str(
                compatibilityPath.resolve()
            ),
        ]

    finally:
        if inputSet is not None:
            inputSet.close()

        adapter.uninstall()








