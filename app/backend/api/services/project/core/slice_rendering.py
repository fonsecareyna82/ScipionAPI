"""Pure 2D-slice pixel manipulation shared by every "render a tomogram/volume
slice as an image" preview path (Coordinates3D, Volumes, metadata image
cells). No Scipion runtime or PostgreSQL state involved - just numpy/PIL.
"""
from typing import Optional

import numpy as np

from app.backend.utils.constants import maxThumbSize


def coords3dPilTo2dTile(imgStk, pilImg) -> Optional[np.ndarray]:
    """
    Convert a PIL tomogram slice into a small 2D float array.

    - Downsamples to <= maxThumbSize without upscaling.
    - Converts to grayscale if needed.
    - Applies highlightSlice/normalizeSlice at most once.
    - Returns float32 2D array; caller can decide final uint8/colormap.
    """
    try:
        width, height = pilImg.size
        scale = min(
            maxThumbSize / float(width),
            maxThumbSize / float(height),
            1.0,
        )
        thumbWidth = max(1, int(round(width * scale)))
        thumbHeight = max(1, int(round(height * scale)))

        if pilImg.mode not in ("L", "I;16", "F"):
            pilGray = pilImg.convert("L")
        else:
            pilGray = pilImg

        if thumbWidth < width or thumbHeight < height:
            pilGray = pilGray.copy()
            pilGray.thumbnail((thumbWidth, thumbHeight))

        arr = np.asarray(pilGray, dtype=np.float32)

        arr = np.squeeze(arr)
        if arr.ndim != 2 or arr.size == 0:
            return None

        try:
            arr = imgStk.highlightSlice(arr)
            arr = imgStk.normalizeSlice(arr)
        except Exception:
            pass

        return arr.astype(np.float32, copy=False)
    except Exception:
        return None


def normalize2dSlice(a: np.ndarray, mode: str = "minmax") -> np.ndarray:
    """
    Normalize a 2D slice into uint8 according to mode: 'minmax' | 'zscore' | 'none'.

    Safeguards:
    - Accepts any numeric dtype.
    - If already uint8 and mode in ('minmax', 'none'), returns a copy directly.
    - Handles NaNs and constant arrays without blowing up.
    """
    if a.ndim != 2:
        raise ValueError("Expected 2D slice")

    arr = np.asarray(a)

    if arr.dtype == np.uint8 and (mode or "minmax").lower() in ("minmax", "none"):
        return arr.copy()

    arr = arr.astype(np.float32, copy=False)
    mode = (mode or "minmax").lower()

    finiteMask = np.isfinite(arr)
    if not finiteMask.all():
        if finiteMask.any():
            fillVal = float(np.nanmedian(arr[finiteMask]))
        else:
            fillVal = 0.0
        arr = np.where(finiteMask, arr, fillVal)

    if mode == "zscore":
        mu = float(np.mean(arr))
        sd = float(np.std(arr))
        if sd == 0.0 or not np.isfinite(sd):
            return np.zeros_like(arr, dtype=np.uint8)
        arr = (arr - mu) / sd
        arr = np.clip(arr, -3.0, 3.0)
        amin, amax = float(arr.min()), float(arr.max())
        if amax <= amin:
            return np.zeros_like(arr, dtype=np.uint8)
        arr = (arr - amin) / (amax - amin + 1e-12)
        return (255.0 * arr).astype(np.uint8)

    amin, amax = float(arr.min()), float(arr.max())
    if (not np.isfinite(amin)) or (not np.isfinite(amax)) or amax <= amin:
        return np.zeros_like(arr, dtype=np.uint8)

    arr = (arr - amin) / (amax - amin + 1e-12)
    return (255.0 * arr).astype(np.uint8)
