"""RED 66: duplication must not silently persist a dangling Set-member Pointer.

The native Scipion Pointer.get() follows the output name and then calls the
Set's __getitem__(scipionItemId) for numeric extensions. IDs are sparse.
These tests protect validation *before* writing a duplicated protocol.
"""

from pyworkflow.object import Object, Pointer, PointerList

from app.backend.runtime.protocol_duplicate_service import (
    RuntimeProtocolDuplicateService,
)


class _Member(Object):
    def __init__(self, item_id):
        super().__init__()
        self.setObjId(item_id)


class _SparseSet(Object):
    """Set-like object supporting native Pointer numeric item access."""

    def __init__(self, members, *, missing_raises=False, substituted=None):
        super().__init__()
        self.setObjId(440)
        self.members = dict(members)
        self.missing_raises = missing_raises
        self.substituted = substituted
        self.lookups = []

    def __getitem__(self, item_id):
        self.lookups.append(item_id)
        if self.substituted is not None:
            return self.substituted
        if item_id not in self.members and self.missing_raises:
            raise KeyError("item %s was deleted" % item_id)
        return self.members.get(item_id)


def _parent(output_set=None):
    parent = Object()
    parent.setObjId(2202)
    if output_set is not None:
        parent.outputVolumes = output_set
    return parent


def _protocol(*, single=None, multi=None):
    protocol = Object()
    protocol.setObjId(3203)
    if single is not None:
        protocol.inputVolume = single
    if multi is not None:
        pointers = PointerList()
        for pointer in multi:
            pointers.append(pointer)
        protocol.inputVolumes = pointers
    return protocol


def _validate(protocol):
    return RuntimeProtocolDuplicateService().validateProtocolPointerTargetsForPersistence(
        protocol=protocol,
    )


def _assert_rejected(report, input_name):
    assert report["valid"] is False
    assert report["errors"]
    assert any(input_name in str(error.get("path", "")) for error in report["errors"])


class TestDuplicateSetItemPointerValidation_RED66:
    def test_DirectOutputAndValidSparseMemberRemainValid_baseline(self):
        # The original direct output and a valid Set member must remain valid.
        item = _Member(34)
        output_set = _SparseSet({34: item, 90: _Member(90)})
        parent = _parent(output_set)
        protocol = _protocol(
            single=Pointer(parent, extended="outputVolumes.34"),
            multi=[Pointer(parent, extended="outputVolumes")],
        )

        assert protocol.inputVolume.get() is item
        assert protocol.inputVolumes[0].get() is output_set
        assert _validate(protocol) == {"valid": True, "errors": []}

    def test_DeletedMemberReturningNoneCannotBeDuplicated(self):
        parent = _parent(_SparseSet({90: _Member(90)}))
        protocol = _protocol(single=Pointer(parent, extended="outputVolumes.34"))
        assert protocol.inputVolume.get() is None

        report = _validate(protocol)
        _assert_rejected(report, "inputVolume")
        assert any("34" in str(error) for error in report["errors"])

    def test_DeletedMemberRaisingKeyErrorCannotBeDuplicated(self):
        parent = _parent(_SparseSet({90: _Member(90)}, missing_raises=True))
        protocol = _protocol(single=Pointer(parent, extended="outputVolumes.34"))

        # It must record a validation error, not propagate the item lookup
        # exception and not mark the dangling pointer as valid.
        report = _validate(protocol)
        _assert_rejected(report, "inputVolume")
        assert any("34" in str(error) for error in report["errors"])

    def test_IncorrectMemberIdentityCannotBeDuplicated(self):
        wrong = _Member(90)
        parent = _parent(_SparseSet({34: _Member(34), 90: wrong}, substituted=wrong))
        protocol = _protocol(single=Pointer(parent, extended="outputVolumes.34"))
        assert protocol.inputVolume.get() is wrong

        report = _validate(protocol)
        _assert_rejected(report, "inputVolume")
        assert any("34" in str(error) and "90" in str(error) for error in report["errors"])

    def test_UnavailableProducerOutputCannotValidateNestedMember(self):
        parent = _parent()  # Valid Scipion protocol but missing outputVolumes.
        protocol = _protocol(single=Pointer(parent, extended="outputVolumes.34"))
        assert protocol.inputVolume.get() is None

        report = _validate(protocol)
        _assert_rejected(report, "inputVolume")
        assert any("outputVolumes" in str(error) for error in report["errors"])

    def test_MultipointerListRejectsOneInvalidSetMember(self):
        parent = _parent(_SparseSet({34: _Member(34), 90: _Member(90)}))
        protocol = _protocol(multi=[
            Pointer(parent, extended="outputVolumes.34"),
            Pointer(parent, extended="outputVolumes.99"),
        ])
        assert protocol.inputVolumes[0].get().getObjId() == 34
        assert protocol.inputVolumes[1].get() is None

        report = _validate(protocol)
        _assert_rejected(report, "inputVolumes")
        assert any("99" in str(error) for error in report["errors"])
