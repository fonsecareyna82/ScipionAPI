"""Pending rows stay retryable and bounded independently of their item class."""

import io
import json
from datetime import datetime, timezone

import pytest

from app.backend.mapper import postgresql_append_buffer as bufferModule
from app.backend.mapper.postgresql_append_buffer import EncodedAppendItem, PostgresqlAppendBuffer


def item(index):
    return dict(scipionItemId=index, enabled=False, label="étiquette\\N\t\n",
                comment=None, creation=datetime(2025, 1, 2, tzinfo=timezone.utc),
                values={"_score": 0.125, "_optional": None,
                        "_pointer": {"targetObjectId": 10, "extended": "outputParticles"},
                        "nested": [1, True, "unicode-é"], "tiny": 1e-200})


@pytest.mark.parametrize("limit", [1, 8 * 1024 * 1024])
def test_CompactRowsPreserveMetadataValuesAndIndependentIterations(limit):
    pending = PostgresqlAppendBuffer(limit)
    try:
        original = [item(index) for index in range(4)]
        for row in original:
            pending.append(row)
        assert pending.spilled == (limit == 1)
        assert pending == original
        first, second = iter(pending), iter(pending)
        assert dict(next(first)) == original[0]
        assert dict(next(second)) == original[0]
        assert list(first) == original[1:]
        assert list(second) == original[1:]
        assert dict(pending[-1]) == original[-1]
        assert pending[:2] == original[:2]
        with pytest.raises(IndexError):
            pending[4]
    finally:
        pending.clear()


def test_NormalizedRowsFreezeValuesWithoutRetainingTheirMutableDictionary():
    pending = PostgresqlAppendBuffer()
    original = item(1)
    pending.append(original)
    original["values"]["nested"].append("later mutation")
    record = pending[0]
    assert isinstance(record, EncodedAppendItem)
    assert record["values"]["nested"] == [1, True, "unicode-é"]
    assert json.loads(record.jsonValues) == record["values"]
    record["values"]["nested"].append("mutated decoded copy")
    assert pending[0]["values"]["nested"] == [1, True, "unicode-é"]
    pending.clear()


@pytest.mark.parametrize("limit", [1, 8 * 1024 * 1024])
def test_CompactJsonPreservesStringWhitespaceAndNumericPrecision(limit):
    pending = PostgresqlAppendBuffer(limit)
    row = item(1)
    row["values"].update({
        "text": '  é: a, b\n\t"quoted"\\N  ',
        "integer": 2 ** 100,
        "fraction": 1.2345678901234567,
        "negativeZero": -0.0,
    })
    try:
        pending.append(row)
        encoded = pending[0].jsonValues
        assert json.loads(encoded) == row["values"]
        assert len(encoded) < len(json.dumps(row["values"]))
        assert '"negativeZero":-0.0' in encoded
    finally:
        pending.clear()


def test_UnsupportedValuesKeepDeferredConversionAndReferences():
    calls = []

    class CustomValue:
        value = "before"

        def __str__(self):
            calls.append(self.value)
            return self.value

    opaque = CustomValue()
    row = item(1)
    row["values"] = {"custom": opaque}
    pending = PostgresqlAppendBuffer(1)
    pending.append(row)
    assert calls == []
    assert pending[0] is row
    opaque.value = "after"
    assert json.loads(json.dumps(pending[0]["values"], default=str)) == {"custom": "after"}
    assert calls == ["after"]
    pending.clear()


@pytest.mark.parametrize("kind", ["metadata", "cyclic"])
def test_NonNormalizedRecordsRetainTheOriginalDeferredRepresentation(kind):
    row = item(1)
    if kind == "metadata":
        row["creation"] = object()
    else:
        row["values"]["self"] = row["values"]
    pending = PostgresqlAppendBuffer(1)
    pending.append(row)
    assert pending[0] is row
    pending.clear()


@pytest.mark.parametrize("limit", [1, 8 * 1024 * 1024])
def test_PrefixFlushKeepsItemsAppendedDuringIteration(limit):
    pending = PostgresqlAppendBuffer(limit)
    pending.append(item(1))
    pending.append(item(2))
    snapshot = pending.iterPrefix(len(pending))
    assert next(snapshot) == item(1)
    pending.append(item(3))
    assert list(snapshot) == [item(2)]
    pending.discardPrefix(2)
    assert pending == [item(3)]
    pending.discardPrefix(1)
    assert pending == []


@pytest.mark.parametrize("failure", ["create", "write"])
def test_SpillFailurePreservesAllPreviouslyBufferedRows(monkeypatch, failure):
    pending = PostgresqlAppendBuffer()
    pending.append(item(1))
    originalFile = pending._file
    pending.maxMemoryBytes = 1

    class ShortFile(io.BytesIO):
        def write(self, data):
            return super().write(data[:1])

    shortFile = ShortFile()

    def temporary(**kwargs):
        if failure == "create":
            raise OSError("disk unavailable")
        return shortFile

    monkeypatch.setattr(bufferModule.tempfile, "TemporaryFile", temporary)
    with pytest.raises(OSError):
        pending.append(item(2))
    assert pending._file is originalFile
    assert not originalFile.closed
    assert pending == [item(1)]
    assert len(pending) == 1
    if failure == "write":
        assert shortFile.closed
    pending.clear()


def test_PartialRecordWriteIsRemovedBeforeRetry():
    pending = PostgresqlAppendBuffer()
    pending.append(item(1))
    originalFile = pending._file

    class BrokenWrite:
        def __getattr__(self, name):
            return getattr(originalFile, name)

        def write(self, data):
            originalFile.write(data[:3])
            raise OSError("partial write")

    pending._file = BrokenWrite()
    with pytest.raises(OSError, match="partial"):
        pending.append(item(2))
    assert pending == [item(1)]
    pending._file = originalFile
    pending.append(item(2))
    assert pending == [item(1), item(2)]
    pending.clear()


def test_ClearClosesSpillAndAllowsReuse():
    pending = PostgresqlAppendBuffer(1)
    pending.append(item(1))
    file = pending._file
    pending.clear()
    assert file.closed
    assert pending == []
    pending.append(item(2))
    assert pending == [item(2)]
    pending.clear()


def test_MissingEnabledPreservesDefaultTrue():
    row = item(1)
    row.pop("enabled")
    pending = PostgresqlAppendBuffer()
    pending.append(row)
    assert pending[0]["enabled"] is True
    pending.clear()


def test_PartialFlushRetainsOpaqueFallbackRecords():
    pending = PostgresqlAppendBuffer(1)
    pending.append(item(1))
    custom = item(2)
    custom["creation"] = object()
    pending.append(custom)
    pending.discardPrefix(1)
    assert len(pending) == 1
    assert pending[0] is custom
    pending.clear()
