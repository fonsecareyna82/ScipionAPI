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
# app/backend/utils/volume_utils.py
from pathlib import Path
from dataclasses import dataclass
from functools import lru_cache
from typing import Tuple, Dict, Any, Optional
import numpy as np
from pwem.emlib.image.image_readers import (
    ImageReadersRegistry,
    MRCImageReader,
)

# Slices are shown lightly smoothed: at pixel level a tomogram is mostly noise.
DISPLAY_SMOOTHING_SIGMA = 1.0
DISPLAY_WINDOW_PERCENTILES = (0.5, 99.5)
DISPLAY_WINDOW_SAMPLE_SLICES = 9


@dataclass(frozen=True)
class VolumeSignature:
    path: str
    mtime_ns: int
    size: int


def buildVolumeSignature(p: Path) -> VolumeSignature:
    st = p.stat()
    return VolumeSignature(str(p), st.st_mtime_ns, st.st_size)


def readVolumeSlice2d(
        volumePath: str,
        sliceIndex: int,
        axis: str = "z",
        maxSide: Optional[int] = None,
) -> Tuple[np.ndarray, Dict[str, Any], Dict[str, Any]]:
    vol3d, props = readVolumeArray3d(volumePath)

    if vol3d.ndim != 3:
        raise ValueError(f"Unsupported volume shape {vol3d.shape}, expected 3D")

    zdim, ydim, xdim = (
        int(vol3d.shape[0]),
        int(vol3d.shape[1]),
        int(vol3d.shape[2]),
    )

    axis = (axis or "z").lower()
    if axis not in ("z", "y", "x"):
        axis = "z"

    if axis == "z":
        dim = zdim
        outH, outW = ydim, xdim
    elif axis == "y":
        dim = ydim
        outH, outW = zdim, xdim
    else:
        dim = xdim
        outH, outW = zdim, ydim

    if dim <= 0:
        raise ValueError("Empty volume")

    k = max(0, min(int(sliceIndex), dim - 1))

    step = 1

    if axis == "z":
        slice2d = vol3d[k, :, :]
    elif axis == "y":
        slice2d = vol3d[:, k, :]
    else:
        slice2d = vol3d[:, :, k]

    meta = {
        "axis": axis,
        "index": k,
        "dims": (zdim, ydim, xdim),
        "step": step,
    }

    return np.asarray(slice2d), props, meta


def _normalizeVolumeArray(
        data: Any,
        *,
        castFloat32: bool = True,
) -> np.ndarray:
    arr = np.asarray(data)

    if arr.ndim not in (2, 3):
        arr = np.squeeze(arr)
        if arr.ndim not in (2, 3):
            raise ValueError(f"Unsupported dimensionality: {arr.shape}")

    if arr.ndim == 2:
        arr = arr[None, ...]
    elif arr.ndim != 3:
        raise ValueError(f"Unsupported volume shape {arr.shape}")

    if castFloat32:
        return arr.astype(np.float32, copy=False)

    return arr


def _extractMrcVoxelSize(mrc: Any) -> Dict[str, Any]:
    voxelSize = getattr(mrc, "voxel_size", None)
    if voxelSize is None:
        return {}

    try:
        values = (float(voxelSize.x), float(voxelSize.y), float(voxelSize.z))
    except Exception:
        try:
            rawValues = list(voxelSize)
            if len(rawValues) < 3:
                return {}
            values = (float(rawValues[0]), float(rawValues[1]), float(rawValues[2]))
        except Exception:
            return {}

    if not all(np.isfinite(v) and v > 0 for v in values):
        return {}

    return {"voxelSize": values, "samplingRate": values}


def _openMrcMemmap(path: str) -> Optional[Tuple[np.ndarray, Dict[str, Any], Any]]:
    try:
        import mrcfile
    except Exception:
        return None

    try:
        mrc = mrcfile.mmap(path, mode="r", permissive=True)
        arr = _normalizeVolumeArray(mrc.data, castFloat32=False)
        props = _extractMrcVoxelSize(mrc)
        return arr, props, mrc
    except Exception:
        try:
            mrc.close()
        except Exception:
            pass
        return None


@lru_cache(maxsize=4)
def _readMrcVolumeMapped(sig: VolumeSignature) -> Tuple[np.ndarray, Dict[str, Any], Any]:
    mapped = _openMrcMemmap(sig.path)
    if mapped is None:
        raise RuntimeError("Could not open volume as an MRC memory map")
    return mapped


@lru_cache(maxsize=2)
def _readVolumeCached(sig: VolumeSignature) -> Tuple[np.ndarray, Dict[str, Any]]:
    imgStk = ImageReadersRegistry.open(sig.path)
    data = _normalizeVolumeArray(imgStk.getImages())
    try:
        props = imgStk.getProperties() or {}
    except Exception:
        props = {}
    return data, props


def readVolumeArray3d(volumePath: str) -> Tuple[np.ndarray, Dict[str, Any]]:
    p = Path(volumePath)
    if not p.exists():
        raise FileNotFoundError(volumePath)

    sig = buildVolumeSignature(p)

    try:
        readerClass = ImageReadersRegistry.getReader(str(p))
    except Exception:
        readerClass = None

    if readerClass is MRCImageReader:
        try:
            arr, props, _mrcHandle = _readMrcVolumeMapped(sig)
            return arr, props
        except Exception:
            pass

    arr, props = _readVolumeCached(sig)
    return arr, props


def smoothSliceForDisplay(slice2d: np.ndarray) -> np.ndarray:
    """Gaussian smoothing applied to every displayed slice; the data are never changed."""
    from scipy.ndimage import gaussian_filter

    arr = np.asarray(slice2d, dtype=np.float32)
    finiteMask = np.isfinite(arr)
    if not finiteMask.any():
        return arr
    if not finiteMask.all():
        arr = np.where(finiteMask, arr, float(np.median(arr[finiteMask])))
    return gaussian_filter(arr, sigma=DISPLAY_SMOOTHING_SIGMA, mode="nearest")


def readVolumeDisplayWindow(volumePath: str, axis: str = "z") -> Optional[Tuple[float, float]]:
    """Intensity window shared by every slice of a volume along one axis.

    One window per axis, not per volume: smoothing removes less noise from the X and Y
    slices, where it is stretched along Z, so a Z window would saturate them.
    """
    p = Path(volumePath)
    if not p.exists():
        return None
    axis = (axis or "z").lower()
    if axis not in ("z", "y", "x"):
        axis = "z"
    return _computeVolumeDisplayWindow(buildVolumeSignature(p), axis)


@lru_cache(maxsize=48)
def _computeVolumeDisplayWindow(sig: VolumeSignature, axis: str) -> Optional[Tuple[float, float]]:
    vol3d, _props = readVolumeArray3d(sig.path)
    arrayAxis = {"z": 0, "y": 1, "x": 2}[axis]
    dim = int(vol3d.shape[arrayAxis])
    if dim <= 0:
        return None

    # A few slices over the central part are enough; the outer ones are often empty
    first, last = int(dim * 0.1), max(int(dim * 0.9) - 1, int(dim * 0.1))
    indexes = sorted(set(np.linspace(first, last, DISPLAY_WINDOW_SAMPLE_SLICES).round().astype(int)))
    values = np.concatenate([
        smoothSliceForDisplay(np.take(vol3d, k, axis=arrayAxis)).ravel() for k in indexes
    ])
    values = values[np.isfinite(values)]
    if values.size == 0:
        return None

    low, high = (float(v) for v in np.percentile(values, DISPLAY_WINDOW_PERCENTILES))
    if high <= low:
        # Mostly constant volumes (masks): fall back to the full range
        low, high = float(values.min()), float(values.max())
    if high <= low:
        return None
    return low, high
