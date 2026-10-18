"""A tomogram (or any volume) reduced for a viewer that cuts its slices itself.

Display only: the stored volume never changes. The volume is reduced by block
averaging (the same factor on every axis, never below one voxel) until it has
at most maxVoxels voxels, and sent as 8 bits over mean +/- QUANTIZED_SIGMAS
standard deviations measured without outliers, like the tilt series stacks.
One window for the whole volume: browsing its slices never changes the
contrast.
"""
from __future__ import annotations

import json
import math
import struct
import threading
from collections import OrderedDict
from typing import Any, Dict, Tuple

import numpy as np

from app.backend.utils.tilt_series_stack import QUANTIZED_SIGMAS, quantize, robustStats

VOLUME_MAGIC = b"TVOL"
VOLUME_MEDIA_TYPE = "application/octet-stream"
# Voxels sampled to measure the statistics.
_STATS_SAMPLE = 2_000_000
_CACHE_ITEMS = 3

_cache: "OrderedDict[Tuple, bytes]" = OrderedDict()
_cacheLock = threading.Lock()


def volumeBinningFactor(shape, maxVoxels: int) -> int:
    voxels = float(np.prod([max(1, int(side)) for side in shape]))
    return max(1, int(math.ceil((voxels / float(max(1, maxVoxels))) ** (1.0 / 3.0) - 1e-9)))


def binVolume(volume, factor: int) -> np.ndarray:
    """Block mean by factor on every axis (at most the axis length), a few planes at a time.

    Works on memory mapped volumes without reading them whole.
    """
    shape = volume.shape
    if factor <= 1:
        return np.asarray(volume, dtype=np.float32)
    fz, fy, fx = (max(1, min(factor, side)) for side in shape)
    z, y, x = shape[0] // fz * fz, shape[1] // fy * fy, shape[2] // fx * fx
    reduced = np.empty((z // fz, y // fy, x // fx), dtype=np.float32)
    for plane in range(z // fz):
        slab = np.asarray(volume[plane * fz:(plane + 1) * fz, :y, :x], dtype=np.float32)
        reduced[plane] = slab.reshape(fz, y // fy, fy, x // fx, fx).mean(axis=(0, 2, 4))
    return reduced


def reduceVolumeForViewer(volume, maxVoxels: int) -> Dict[str, Any]:
    """The reduced 8-bit volume (z, y, x) and what the viewer needs to read it."""
    if getattr(volume, "ndim", 0) != 3:
        raise ValueError("Expected a 3D volume")
    factor = volumeBinningFactor(volume.shape, maxVoxels)
    reduced = binVolume(volume, factor)
    finite = np.isfinite(reduced)
    if not finite.all():
        reduced = np.where(finite, reduced, np.median(reduced[finite]) if finite.any() else 0).astype(np.float32)
    flat = reduced.reshape(-1)
    sample = flat[::max(1, flat.size // _STATS_SAMPLE)]
    mean, std = robustStats(sample)
    low = mean - QUANTIZED_SIGMAS * std
    high = mean + QUANTIZED_SIGMAS * std
    return {
        "width": int(reduced.shape[2]),
        "height": int(reduced.shape[1]),
        "depth": int(reduced.shape[0]),
        "origWidth": int(volume.shape[2]),
        "origHeight": int(volume.shape[1]),
        "origDepth": int(volume.shape[0]),
        "binning": [int(volume.shape[2] / reduced.shape[2]), int(volume.shape[1] / reduced.shape[1]),
                    int(volume.shape[0] / reduced.shape[0])],
        "mean": mean,
        "std": std,
        "low": float(low),
        "high": float(high),
        "data": quantize(reduced, low, high),
    }


def encodeVolumeStack(reduced: Dict[str, Any]) -> bytes:
    """``TVOL``, the header length (uint32 LE), a JSON header, then the 8-bit voxels (z, y, x)."""
    header = {key: value for key, value in reduced.items() if key != "data"}
    headerBytes = json.dumps(header).encode("utf-8")
    headerBytes += b" " * (-(8 + len(headerBytes)) % 4)
    return b"".join([VOLUME_MAGIC, struct.pack("<I", len(headerBytes)), headerBytes,
                     np.ascontiguousarray(reduced["data"], dtype=np.uint8).tobytes()])


def decodeVolumeStack(payload: bytes) -> Dict[str, Any]:
    if payload[:4] != VOLUME_MAGIC:
        raise ValueError("Not a volume stack")
    (headerLength,) = struct.unpack("<I", payload[4:8])
    offset = 8 + headerLength
    stack = json.loads(payload[8:offset].decode("utf-8"))
    size = stack["depth"] * stack["height"] * stack["width"]
    stack["data"] = np.frombuffer(payload[offset:offset + size], dtype=np.uint8).reshape(
        stack["depth"], stack["height"], stack["width"])
    return stack


def cachedVolumeStack(key: Tuple, build) -> bytes:
    """encodeVolumeStack of build(), kept for a few volumes (key includes the file mtime)."""
    with _cacheLock:
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
            return cached
    body = build()
    with _cacheLock:
        _cache[key] = body
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_ITEMS:
            _cache.popitem(last=False)
    return body


def clearVolumeStackCache() -> None:
    with _cacheLock:
        _cache.clear()
