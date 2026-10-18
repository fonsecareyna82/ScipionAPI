"""Tilt images reduced for the web viewer, sent many at once.

Display only: the images stored in Scipion never change.

Each tilt image is reduced by averaging blocks of pixels (from its original
floating point values, never from an 8-bit preview), and its statistics are
measured without its outliers (hot pixels, dead areas). The image is sent as
8 bits over mean +/- QUANTIZED_SIGMAS standard deviations: the viewer shows
windows of a few standard deviations, so 256 levels over that range keep
every visible detail while the image takes a quarter of its float size.

The viewer draws the images itself: contrast, the alignment (rotation and
shifts, sent in the header) and the vertical flip of the previews.
"""
from __future__ import annotations

import json
import math
import struct
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

STACK_MAGIC = b"TSST"
STACK_MEDIA_TYPE = "application/octet-stream"
# The 8 bits cover mean +/- this many standard deviations.
QUANTIZED_SIGMAS = 5.0
# Outliers left out of the statistics (percent at each end).
OUTLIER_PERCENT = 0.1
# Reduced images kept in memory (a few series of ~60 tilts).
_FRAME_CACHE_ITEMS = 240

_frameCache: "OrderedDict[Tuple, Dict[str, Any]]" = OrderedDict()
_frameCacheLock = threading.Lock()


def binningFactor(height: int, width: int, maxDim: int) -> int:
    return max(1, int(math.ceil(max(height, width) / float(max(1, maxDim)))))


def binImage(image, maxDim: int) -> Tuple[np.ndarray, int]:
    """The image averaged in square blocks so its longest side is at most maxDim."""
    data = np.asarray(image, dtype=np.float32)
    data = np.squeeze(data)
    if data.ndim != 2 or data.size == 0:
        raise ValueError("Expected a 2D image")
    factor = binningFactor(data.shape[0], data.shape[1], maxDim)
    if factor == 1:
        return np.ascontiguousarray(data), 1
    height = data.shape[0] // factor * factor
    width = data.shape[1] // factor * factor
    blocks = data[:height, :width].reshape(height // factor, factor, width // factor, factor)
    return blocks.mean(axis=(1, 3), dtype=np.float64).astype(np.float32), factor


def robustStats(image: np.ndarray) -> Tuple[float, float]:
    """Mean and standard deviation of the image without its outliers."""
    values = image[np.isfinite(image)]
    if values.size == 0:
        return 0.0, 1.0
    low, high = np.percentile(values, [OUTLIER_PERCENT, 100.0 - OUTLIER_PERCENT])
    inner = values[(values >= low) & (values <= high)]
    if inner.size == 0:
        inner = values
    mean = float(inner.mean())
    std = float(inner.std())
    if not np.isfinite(std) or std <= 0:
        std = float(np.abs(values - mean).max()) or 1.0
    return mean, std


def quantize(image: np.ndarray, low: float, high: float) -> np.ndarray:
    span = high - low if high > low else 1.0
    scaled = (np.nan_to_num(image, nan=low) - low) * (255.0 / span)
    return np.clip(np.rint(scaled), 0, 255).astype(np.uint8)


def reduceTiltImage(image, maxDim: int) -> Dict[str, Any]:
    """The reduced 8-bit image and what the viewer needs to read it."""
    original = np.squeeze(np.asarray(image))
    binned, factor = binImage(original, maxDim)
    mean, std = robustStats(binned)
    low = mean - QUANTIZED_SIGMAS * std
    high = mean + QUANTIZED_SIGMAS * std
    return {
        "width": int(binned.shape[1]),
        "height": int(binned.shape[0]),
        "origWidth": int(original.shape[1]),
        "origHeight": int(original.shape[0]),
        "binning": int(factor),
        "mean": mean,
        "std": std,
        "low": float(low),
        "high": float(high),
        "data": quantize(binned, low, high),
    }


def cachedReducedTiltImage(key: Tuple, load) -> Dict[str, Any]:
    """reduceTiltImage of load(), kept in memory under key (which must include the file mtime)."""
    with _frameCacheLock:
        cached = _frameCache.get(key)
        if cached is not None:
            _frameCache.move_to_end(key)
            return cached
    reduced = load()
    with _frameCacheLock:
        _frameCache[key] = reduced
        _frameCache.move_to_end(key)
        while len(_frameCache) > _FRAME_CACHE_ITEMS:
            _frameCache.popitem(last=False)
    return reduced


def clearFrameCache() -> None:
    with _frameCacheLock:
        _frameCache.clear()


def encodeTiltSeriesStack(header: Dict[str, Any], frames: Sequence[Dict[str, Any]]) -> bytes:
    """``TSST``, the header length (uint32 LE), a JSON header, then the 8-bit images.

    The header lists the frames in the order of their images; each frame has
    its width and height (the image is ``width * height`` bytes, row by row,
    the first row of the file first) or an ``error`` and no image.
    """
    described: List[Dict[str, Any]] = []
    images: List[bytes] = []
    for frame in frames:
        entry = {key: value for key, value in frame.items() if key != "data"}
        data = frame.get("data")
        if data is not None and "error" not in frame:
            images.append(np.ascontiguousarray(data, dtype=np.uint8).tobytes())
        described.append(entry)
    headerBytes = json.dumps({**header, "frames": described}).encode("utf-8")
    headerBytes += b" " * (-(8 + len(headerBytes)) % 4)
    return b"".join([STACK_MAGIC, struct.pack("<I", len(headerBytes)), headerBytes, *images])


def decodeTiltSeriesStack(payload: bytes) -> Dict[str, Any]:
    """The stack written by encodeTiltSeriesStack, with numpy images."""
    if payload[:4] != STACK_MAGIC:
        raise ValueError("Not a tilt series stack")
    (headerLength,) = struct.unpack("<I", payload[4:8])
    offset = 8 + headerLength
    stack = json.loads(payload[8:offset].decode("utf-8"))
    for frame in stack["frames"]:
        if "error" in frame:
            continue
        size = int(frame["width"]) * int(frame["height"])
        frame["data"] = np.frombuffer(payload[offset:offset + size], dtype=np.uint8).reshape(
            int(frame["height"]), int(frame["width"]))
        offset += size
    return stack


def parseIndices(text: Optional[str], limit: int) -> Optional[List[int]]:
    """``"3,1,2"`` as [3, 1, 2] (unique, non negative, at most limit); None for every tilt."""
    if text is None or not str(text).strip():
        return None
    indices: List[int] = []
    for part in str(text).split(","):
        try:
            value = int(part.strip())
        except ValueError:
            continue
        if value >= 0 and value not in indices:
            indices.append(value)
        if len(indices) >= limit:
            break
    return indices
