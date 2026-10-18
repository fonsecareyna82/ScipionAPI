"""Display images (micrographs, tilt images, volume slices) from their original values.

Display only: the stored images never change. The image is reduced from its
floating point values (block averaging, then a Lanczos resampling to the exact
size) and shown over mean +/- DISPLAY_SIGMAS standard deviations measured
without its outliers, so hot pixels or dead areas do not squeeze the image
into a few gray levels.
"""
from __future__ import annotations

import numpy as np

from app.backend.utils.tilt_series_stack import robustStats

# The previews have always shown mean +/- 2 standard deviations.
DISPLAY_SIGMAS = 2.0


def reduceForDisplay(image, size: int) -> np.ndarray:
    """The 2D image as float32 with its longest side at most size."""
    from PIL import Image

    data = np.squeeze(np.asarray(image, dtype=np.float32))
    if data.ndim != 2 or data.size == 0:
        raise ValueError("Expected a 2D image")
    data = np.where(np.isfinite(data), data, np.float32(np.nanmedian(data) if np.isfinite(data).any() else 0))
    height, width = data.shape
    longest = max(height, width)
    if not size or longest <= size:
        return data

    factor = int(longest // size)
    if factor > 1:
        croppedHeight = height // factor * factor
        croppedWidth = width // factor * factor
        data = data[:croppedHeight, :croppedWidth].reshape(
            croppedHeight // factor, factor, croppedWidth // factor, factor).mean(axis=(1, 3), dtype=np.float64).astype(np.float32)
        height, width = data.shape
        longest = max(height, width)
    if longest > size:
        scale = size / float(longest)
        target = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
        data = np.asarray(Image.fromarray(data, mode="F").resize(target, Image.LANCZOS), dtype=np.float32)
    return data


def toDisplayUint8(image: np.ndarray, sigmas: float = DISPLAY_SIGMAS) -> np.ndarray:
    """The image over mean +/- sigmas robust standard deviations, as uint8."""
    data = np.asarray(image, dtype=np.float32)
    mean, std = robustStats(data)
    low, high = mean - sigmas * std, mean + sigmas * std
    if not high > low:
        return np.zeros(data.shape, dtype=np.uint8)
    scaled = (data - low) * (255.0 / (high - low))
    return np.clip(np.rint(scaled), 0, 255).astype(np.uint8)
