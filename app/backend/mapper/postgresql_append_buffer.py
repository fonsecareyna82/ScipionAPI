"""Compact, worker-local pending writes; PostgreSQL remains authoritative."""

import io
import json
import pickle
import tempfile
import threading
from collections.abc import Mapping
from datetime import date, datetime
from itertools import islice

_PLAIN_METADATA_TYPES = frozenset((str, bool, int, float, date, datetime))
_READ_BATCH_SIZE = 256


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

    Only the native runtime factory opts into early JSON encoding. Custom
    serializers keep their existing deferred conversion and mutation contract.
    Pickle is read only from our own anonymous temporary file, never user input.
    """

    def __init__(self, maxMemoryBytes=8 * 1024 * 1024):
        self.maxMemoryBytes = maxMemoryBytes
        self._file = None
        self._end = 0
        self._count = 0
        self._fallbacks = {}
        self._lock = threading.RLock()
        self.spilled = False

    def __len__(self):
        return self._count

    def append(self, item):
        metadata = tuple(item.get(key, True if key == "enabled" else None)
                         for key in EncodedAppendItem.KEYS)
        normalMetadata = True
        for value in metadata:
            if value is not None and type(value) not in _PLAIN_METADATA_TYPES:
                normalMetadata = False
                break
        record = None
        if normalMetadata:
            try:
                # Unsupported values fall back without calling custom __str__.
                jsonValues = (item.jsonValues if isinstance(item, EncodedAppendItem)
                              else json.dumps(item.get("values") or {}, separators=(",", ":")))
                record = (metadata, jsonValues)
            except (TypeError, ValueError, OverflowError):
                pass
        data = pickle.dumps(record, protocol=4)
        with self._lock:
            if self._file is None:
                self._file = io.BytesIO()
                self._end = 0
            start = self._end
            if not self.spilled and start + len(data) > self.maxMemoryBytes:
                temporary = tempfile.TemporaryFile(mode="w+b")
                try:
                    self._file.seek(0)
                    oldData = self._file.read()
                    if temporary.write(oldData) != len(oldData):
                        raise OSError("Incomplete PostgreSQL append-buffer spill.")
                except Exception:
                    temporary.close()
                    raise
                self._file.close()
                self._file = temporary
                self.spilled = True
            try:
                # Readers move the shared position; records are only appended.
                self._file.seek(start)
                if self._file.write(data) != len(data):
                    raise OSError("Incomplete PostgreSQL append-buffer write.")
            except Exception:
                self._file.seek(start)
                self._file.truncate()
                raise
            self._end = start + len(data)
            if record is None:
                self._fallbacks[self._count] = item
            self._count += 1

    def iterPrefix(self, count):
        position = 0
        index = 0
        count = min(count, len(self))
        while index < count:
            batch = []
            # Decode a bounded run per seek; appends made meanwhile only add
            # records after this fixed prefix.
            with self._lock:
                self._file.seek(position)
                for recordIndex in range(index, min(count, index + _READ_BATCH_SIZE)):
                    start = position
                    record = pickle.load(self._file)
                    position = self._file.tell()
                    batch.append(self._fallbacks[recordIndex] if record is None
                                 else EncodedAppendItem(*record, encodedSize=position - start))
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
            if count == len(self):
                self.clear()
                return
            replacement = PostgresqlAppendBuffer(self.maxMemoryBytes)
            try:
                for item in islice(self, count, None):
                    replacement.append(item)
            except Exception:
                replacement.clear()
                raise
            self.clear()
            self._file, replacement._file = replacement._file, None
            self._end = replacement._end
            self._count = replacement._count
            self._fallbacks, replacement._fallbacks = replacement._fallbacks, {}
            self.spilled = replacement.spilled

    def clear(self):
        with self._lock:
            if self._file is not None:
                self._file.close()
            self._file = None
            self._end = 0
            self._count = 0
            self._fallbacks.clear()
            self.spilled = False

    def __del__(self):
        try:
            self.clear()
        except Exception:
            pass
