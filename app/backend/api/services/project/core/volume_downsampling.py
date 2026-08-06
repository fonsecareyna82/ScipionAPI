"""Pure numpy volume downsampling pipeline used to build lightweight 3D/mesh
previews of Volume/SetOfVolumes outputs. No Scipion runtime or PostgreSQL
state involved.
"""
from typing import Tuple

import numpy as np
from fastapi import HTTPException


def centerCrop3d(fshift: np.ndarray, targetShape: Tuple[int, int, int]) -> np.ndarray:
    """Crop a centered 3D Fourier volume to targetShape (tz, ty, tx)."""
    tz, ty, tx = targetShape
    z, y, x = fshift.shape

    z0 = max(0, (z - tz) // 2)
    y0 = max(0, (y - ty) // 2)
    x0 = max(0, (x - tx) // 2)

    return fshift[z0:z0 + tz, y0:y0 + ty, x0:x0 + tx]


def binVolume(vol: np.ndarray, factor: int) -> np.ndarray:
    """Real-space average binning by an integer factor."""
    if factor <= 1:
        return vol.astype(np.float32)

    z, y, x = vol.shape
    z2 = (z // factor) * factor
    y2 = (y // factor) * factor
    x2 = (x // factor) * factor

    volC = vol[:z2, :y2, :x2]

    binned = volC.reshape(
        z2 // factor, factor,
        y2 // factor, factor,
        x2 // factor, factor
    ).mean(axis=(1, 3, 5))

    return np.asarray(binned, dtype=np.float32)


def resizeVolumeFourier(vol: np.ndarray, maxDim: int) -> np.ndarray:
    """Fourier crop downsample (low-pass) preserving global structure."""
    z, y, x = vol.shape
    m = max(z, y, x)
    if m <= maxDim:
        return vol.astype(np.float32)

    scale = maxDim / float(m)
    tz = max(8, int(z * scale))
    ty = max(8, int(y * scale))
    tx = max(8, int(x * scale))

    f = np.fft.fftn(vol)
    fshift = np.fft.fftshift(f)

    cropped = centerCrop3d(fshift, (tz, ty, tx))

    out = np.fft.ifftn(np.fft.ifftshift(cropped)).real
    out *= (z * y * x) / float(tz * ty * tx)

    return np.asarray(out, dtype=np.float32)


def downsampleVolumePreview(
        vol: np.ndarray,
        maxDim: int,
        method: str = "binning",
) -> np.ndarray:
    """
    Downsample a volume to a preview size suitable for web 3D rendering.
    - binning: real-space average pooling with integer factor
    - linear: scipy.ndimage.zoom (if available), else binning
    - fourier: Fourier crop + inverse FFT
    """
    if vol is None or vol.ndim != 3:
        raise HTTPException(status_code=500, detail="Invalid volume data")

    z, y, x = vol.shape
    m = max(z, y, x)

    if m <= maxDim:
        return vol.astype(np.float32)

    methodLower = (method or "binning").lower()

    if methodLower == "fourier":
        return resizeVolumeFourier(vol, maxDim)

    if methodLower == "linear":
        try:
            from scipy.ndimage import zoom
            scale = maxDim / float(m)
            small = zoom(vol, zoom=scale, order=1, prefilter=False)
            return np.asarray(small, dtype=np.float32)
        except Exception:
            pass

    factor = int(np.ceil(m / float(maxDim)))
    return binVolume(vol, factor)


def strideDownsampleVolume(volume: np.ndarray, maxDim: int) -> np.ndarray:
    z, y, x = volume.shape
    largestDim = max(z, y, x)
    if largestDim <= maxDim:
        return volume.astype(np.float32, copy=False)

    step = max(1, int(np.ceil(largestDim / float(maxDim))))
    return volume[::step, ::step, ::step].astype(np.float32, copy=False)


def downsampleVolumeForSurface(
        volume: np.ndarray,
        *,
        maxDim: int,
        method: str,
) -> np.ndarray:
    methodLower = (method or "stride").lower()

    if methodLower == "none":
        return volume.astype(np.float32, copy=False)

    if methodLower == "stride":
        return strideDownsampleVolume(volume, maxDim=maxDim)

    return downsampleVolumePreview(volume, maxDim=maxDim, method=methodLower)
