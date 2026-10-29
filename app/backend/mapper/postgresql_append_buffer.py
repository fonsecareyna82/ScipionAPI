"""Compact, worker-local pending writes; PostgreSQL remains authoritative."""

import bisect
import json
import pickle
import tempfile
import threading
from collections.abc import Mapping
from datetime import date, datetime
from itertools import islice

_PLAIN_METADATA_TYPES = frozenset((str, bool, int, float, date, datetime))
_READ_BATCH_SIZE = 256
# Rows written to the spill file per pickled block
_SPILL_BLOCK_ROWS = 1024
# Approximate memory of a row besides its JSON text
_ROW_OVERHEAD_BYTES = 64


class EncodedAppendItem(Mapping):
    KEYS = ("scipionItemId", "enabled", "label", "comment", "creation")

    def __init__(self, metadata, jsonValues, encodedSize=0):
        self.metadata = dict(zip(self.KEYS, metadata))
        self.jsonValues = jsonValues
        self.encodedSize = encodedSize

    def __getitem__(self, key):
        if key == "values":
            return json.loads(self.jsonValues)
        return self.metadata[key]

    def __iter__(self):
        return iter(self.KEYS + ("values",))

    def __len__(self):
        return 6


class PostgresqlAppendBuffer:
    """Freeze normalized rows, spilling above 8 MiB without committing them.

    A row is frozen as its JSON text and immutable metadata, kept in memory
    while the rows fit and written in pickled blocks to an anonymous temporary
    file beyond that. Only the native runtime factory opts into early JSON
    encoding. Custom serializers keep their existing deferred conversion and
    mutation contract. Pickle is read only from our own file, never user input.
    """

    def __init__(self, maxMemoryBytes=8 * 1024 * 1024):
        self.maxMemoryBytes = maxMemoryBytes
        # Rows not spilled yet: (metadata, jsonValues, size), or None for a row kept as given
        self._records = []
        self._memoryBytes = 0
        self._file = None
        self._end = 0
        # Spilled blocks: first row index, offset and length in the file
        self._blockStarts = []
        self._blocks = []
        self._spilledCount = 0
        self._count = 0
        self._fallbacks = {}
        self._lock = threading.RLock()
        self.spilled = False

    def __len__(self):
        return self._count

    def append(self, item):
        get = item.get
        # EncodedAppendItem.KEYS, a missing "enabled" being True
        metadata = (get("scipionItemId"), get("enabled", True), get("label"), get("comment"), get("creation"))
        normalMetadata = True
        size = _ROW_OVERHEAD_BYTES
        for value in metadata:
            valueType = type(value)
            if valueType is str:
                size += len(value)
            elif value is not None and valueType not in _PLAIN_METADATA_TYPES:
                normalMetadata = False
                break
        record = None
        if normalMetadata:
            try:
                # Unsupported values fall back without calling custom __str__.
                jsonValues = (item.jsonValues if isinstance(item, EncodedAppendItem)
                              else json.dumps(get("values") or {}, separators=(",", ":")))
                record = (metadata, jsonValues, size + len(jsonValues))
            except (TypeError, ValueError, OverflowError):
                pass
        self._appendRecord(record, item)

    def _appendRecord(self, record, item):
        with self._lock:
            index = self._count
            self._records.append(record)
            size = record[2] if record is not None else _ROW_OVERHEAD_BYTES
            self._memoryBytes += size
            if record is None:
                self._fallbacks[index] = item
            self._count += 1
            if self._memoryBytes > self.maxMemoryBytes:
                try:
                    self._spill()
                except Exception:
                    # The failed row is not kept: a retry appends it again
                    self._records.pop()
                    self._memoryBytes -= size
                    self._fallbacks.pop(index, None)
                    self._count -= 1
                    raise

    def _spill(self):
        """Write the rows held in memory to the spill file, or leave everything as it was."""
        created = self._file is None
        file = tempfile.TemporaryFile(mode="w+b") if created else self._file
        start = self._end
        position = start
        blocks = []
        try:
            for offset in range(0, len(self._records), _SPILL_BLOCK_ROWS):
                data = pickle.dumps(self._records[offset:offset + _SPILL_BLOCK_ROWS], protocol=4)
                # Readers move the shared position; blocks are only appended.
                file.seek(position)
                if file.write(data) != len(data):
                    raise OSError("Incomplete PostgreSQL append-buffer write.")
                blocks.append((self._spilledCount + offset, position, len(data)))
                position += len(data)
        except Exception:
            if created:
                file.close()
            else:
                file.seek(start)
                file.truncate()
            raise
        self._file = file
        self._end = position
        for firstIndex, blockOffset, length in blocks:
            self._blockStarts.append(firstIndex)
            self._blocks.append((blockOffset, length))
        self._spilledCount += len(self._records)
        self._records = []
        self._memoryBytes = 0
        self.spilled = True

    def _readRecords(self, start, stop, cache):
        """Rows start..stop-1, decoding each spilled block once per reader (cache)."""
        rows = []
        index = start
        while index < stop:
            if index >= self._spilledCount:
                first = index - self._spilledCount
                rows.extend(self._records[first:first + (stop - index)])
                break
            block = bisect.bisect_right(self._blockStarts, index) - 1
            if cache.get("block") != block:
                offset, length = self._blocks[block]
                self._file.seek(offset)
                cache["block"] = block
                cache["records"] = pickle.loads(self._file.read(length))
            blockStart = self._blockStarts[block]
            records = cache["records"]
            taken = records[index - blockStart:index - blockStart + (stop - index)]
            rows.extend(taken)
            index += len(taken)
        return rows

    def iterPrefix(self, count):
        index = 0
        count = min(count, len(self))
        cache = {}
        while index < count:
            stop = min(count, index + _READ_BATCH_SIZE)
            # Rows appended meanwhile only come after this fixed prefix.
            with self._lock:
                records = self._readRecords(index, stop, cache)
                batch = [self._fallbacks[index + offset] if record is None
                         else EncodedAppendItem(record[0], record[1], encodedSize=record[2])
                         for offset, record in enumerate(records)]
            index += len(batch)
            yield from batch

    def __iter__(self):
        return self.iterPrefix(len(self))

    def __getitem__(self, index):
        if isinstance(index, slice):
            return list(self)[index]
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError(index)
        return next(islice(self, index, index + 1))

    def __eq__(self, other):
        if isinstance(other, (list, PostgresqlAppendBuffer)):
            return list(self) == list(other)
        return NotImplemented

    def discardPrefix(self, count):
        with self._lock:
            if count >= len(self):
                self.clear()
                return
            replacement = PostgresqlAppendBuffer(self.maxMemoryBytes)
            try:
                cache = {}
                for index in range(count, len(self), _READ_BATCH_SIZE):
                    stop = min(len(self), index + _READ_BATCH_SIZE)
                    for offset, record in enumerate(self._readRecords(index, stop, cache)):
                        replacement._appendRecord(record, self._fallbacks.get(index + offset))
            except Exception:
                replacement.clear()
                raise
            self.clear()
            for name in ("_records", "_memoryBytes", "_file", "_end", "_blockStarts", "_blocks",
                         "_spilledCount", "_count", "_fallbacks", "spilled"):
                setattr(self, name, getattr(replacement, name))
            replacement._file = None

    def clear(self):
        with self._lock:
            if self._file is not None:
                self._file.close()
            self._file = None
            self._end = 0
            self._records = []
            self._memoryBytes = 0
            self._blockStarts = []
            self._blocks = []
            self._spilledCount = 0
            self._count = 0
            self._fallbacks = {}
            self.spilled = False

    def __del__(self):
        try:
            self.clear()
        except Exception:
            pass
