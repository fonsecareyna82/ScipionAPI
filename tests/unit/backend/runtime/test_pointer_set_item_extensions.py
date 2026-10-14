"""RED 62: native Scipion Set-member Pointer resolution and PostgreSQL refs.

The native Pointer extension stores the entire path from a protocol, e.g.
"outputVolumes.34", but PostgreSQL has one output named "outputVolumes".
The root is used for persisted-output lookup; the FULL extension must still
be saved in protocol_input_refs so Pointer.get() retrieves member ID 34.
"""

import pytest
from pyworkflow.object import Object, Pointer

import app.backend.runtime.pointer_resolver as pointer_module
from app.backend.runtime.pointer_resolver import RuntimePointerResolver


class FakeSet:
    """A keyed Scipion-like Set; IDs are not positional list indices."""

    def __init__(self):
        self.by_id = {
            34: Object(),
            91: Object(),
        }
        self.by_id[34].setObjId(34)
        self.by_id[91].setObjId(91)

    def __getitem__(self, persisted_item_id):
        return self.by_id[persisted_item_id]


class ParentProtocol(Object):
    def __init__(self):
        super().__init__()
        self.setObjId(2202)
        self.outputVolumes = FakeSet()


class IdentityStub:
    def __init__(self, mapper, projectId):
        assert projectId == 7

    def resolvePointerProtocolId(self, protocolId):
        assert str(protocolId) == "2202"
        return 2202

    def resolvePostgresqlProtocolDbIdFromScipionProtocolId(self, protocolId):
        assert str(protocolId) == "2202"
        return 31

    def resolvePostgresqlProtocolDbId(self, protocolId):
        raise AssertionError("Never resolve a known Scipion ID as a PostgreSQL PK")


def test_NativeScipionPointerResolvesSetMemberByPersistedItemId():
    """BASELINE: prove actual Pointer.get() semantics before modifying runtime."""
    parent = ParentProtocol()
    pointer = Pointer(parent, extended="outputVolumes.34")

    assert pointer.getObjValue() is parent
    assert pointer.getExtended() == "outputVolumes.34"
    assert pointer.getUniqueId() == "2202.outputVolumes.34"
    assert pointer.get() is parent.outputVolumes.by_id[34]
    assert pointer.get() is not parent.outputVolumes.by_id[91]


@pytest.mark.parametrize("item_id", [34, 91])
def test_ResolveSetMemberLooksUpOnlyRootOutputButRetainsFullExtension(
    monkeypatch, item_id
):
    """The persisted output is outputVolumes, NOT outputVolumes.<item-id>."""
    monkeypatch.setattr(pointer_module, "ProtocolIdentityResolver", IdentityStub)
    seen_outputs = []
    parent = ParentProtocol()

    def lookup(**kwargs):
        seen_outputs.append(kwargs["outputName"])
        return {"exists": kwargs["outputName"] == "outputVolumes", "source": "postgresql"}

    result = RuntimePointerResolver().resolvePointerTarget(
        mapper=object(),
        projectId=7,
        pointerValue="2202.outputVolumes.%d" % item_id,
        paramLabel="Input volume",
        getParentProtocolCallback=lambda **kwargs: (2202, parent),
        resolveParentOutputCallback=lookup,
    )

    assert seen_outputs == ["outputVolumes"]
    assert result["ok"] is True
    # Callers must construct a native Pointer using this COMPLETE extension.
    assert result["outputName"] == "outputVolumes.%d" % item_id
    assert result["parentProtocolDbId"] == 31
    assert Pointer(parent, extended=result["outputName"]).get() is parent.outputVolumes.by_id[item_id]


def test_ResolveSetMemberRejectsMissingRootEvenIfDottedNameAppearsAsOutput(monkeypatch):
    """Never accept a faux output named 'outputVolumes.34' in lieu of its root."""
    monkeypatch.setattr(pointer_module, "ProtocolIdentityResolver", IdentityStub)
    seen_outputs = []

    def lookup(**kwargs):
        seen_outputs.append(kwargs["outputName"])
        return {"exists": kwargs["outputName"] != "outputVolumes"}

    result = RuntimePointerResolver().resolvePointerTarget(
        mapper=object(),
        projectId=7,
        pointerValue="2202.outputVolumes.34",
        paramLabel="Input volume",
        getParentProtocolCallback=lambda **kwargs: (2202, ParentProtocol()),
        resolveParentOutputCallback=lookup,
    )

    assert seen_outputs == ["outputVolumes"]
    assert result["ok"] is False
    assert "outputVolumes" in result["error"]


def test_BuildInputRefsQueriesRootButPersistsFullScipionItemExtension(monkeypatch):
    """The existing refs schema can store the full extension unchanged."""
    monkeypatch.setattr(pointer_module, "ProtocolIdentityResolver", IdentityStub)
    seen_outputs = []

    class RepositoryStub:
        def getPersistedOutputInfoForInputRef(self, **kwargs):
            seen_outputs.append(kwargs["outputName"])
            return {
                "outputName": "outputVolumes",
                "className": "SetOfVolumes",
                "runtimeObjectId": "8100",
            }

    monkeypatch.setattr(pointer_module, "ProtocolGraphRepository", RepositoryStub)

    result = RuntimePointerResolver().buildInputRefsFromPointerParams(
        mapper=object(),
        projectId=7,
        protocolDbId=43,
        protocolId=2008,
        params={"inputVolume": "2202.outputVolumes.34"},
        getParamCallback=lambda name: type("PointerParamStub", (), {})(),
        isPointerParamCallback=lambda param: True,
    )

    assert seen_outputs == ["outputVolumes"]
    assert result["parentProtocolDbIds"] == [31]
    assert result["parentProtocolIds"] == [2202]
    assert len(result["inputRefs"]) == 1
    ref = result["inputRefs"][0]
    assert ref["parentOutputName"] == "outputVolumes.34"
    assert ref["objectClassName"] == "SetOfVolumes"
    assert ref["objectId"] == "8100"
    assert ref["itemIndex"] == 0


def test_BuildInputRefsCanonicalizesSetOutputNameWithoutDiscardingItemId(monkeypatch):
    """Case-insensitive persisted root resolution must preserve suffix .34."""
    monkeypatch.setattr(pointer_module, "ProtocolIdentityResolver", IdentityStub)
    seen_outputs = []

    class RepositoryStub:
        def getPersistedOutputInfoForInputRef(self, **kwargs):
            seen_outputs.append(kwargs["outputName"])
            return {
                "outputName": "outputVolumes",  # persisted canonical spelling
                "className": "SetOfVolumes",
                "runtimeObjectId": "8100",
            }

    monkeypatch.setattr(pointer_module, "ProtocolGraphRepository", RepositoryStub)

    result = RuntimePointerResolver().buildInputRefsFromPointerParams(
        mapper=object(),
        projectId=7,
        protocolDbId=43,
        protocolId=2008,
        params={"inputVolume": "2202.OutputVolumes.34"},
        getParamCallback=lambda name: type("PointerParamStub", (), {})(),
        isPointerParamCallback=lambda param: True,
    )

    assert seen_outputs == ["OutputVolumes"]
    assert result["inputRefs"][0]["parentOutputName"] == "outputVolumes.34"
    assert result["inputRefs"][0]["parentProtocolId"] == "2202"
