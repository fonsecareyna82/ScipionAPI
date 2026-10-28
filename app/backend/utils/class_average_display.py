"""Display images of class representatives (2D class averages, 3D class volumes).

Display only: these never change an image stored in Scipion or its metadata.
They start from the original floating-point data, not from an 8-bit preview.

2D class averages are scaled to the noise of their background (the outer ring
inside any mask the plugin applied), so every class shows its background at
the same dark gray and its particle stands out; comparing classes shows their
quality. A light smoothing removes the pixel noise of classes with few
particles, and the image is enlarged here (Lanczos) before quantizing.

3D class volumes show as a lit surface (as a molecular viewer would), as a
projection, or as their central slice.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

# Background noise is shown at this many standard deviations above black: in
# 2D classes, and in the projections and slices of 3D classes.
_NOISE_FLOOR_SIGMA = 5.0
_VOLUME_NOISE_FLOOR_SIGMA = 3.0
# Gray of the background (the mean of the noise) in every class.
_BACKGROUND_LEVEL = 0.22
# Highest displayed value: this percentile of the particle area.
_SIGNAL_PERCENTILE = 99.7
# Gaussian smoothing (pixels of the original image) of 2D classes.
_CLASS_SMOOTHING = 1.2
# Noise up to this many standard deviations above the background mean stays in
# the background grays of a 2D class; only what rises above it goes towards white.
_SIGNAL_KNEE_SIGMA = 2.0
# Smoothing of the central slice of a 3D class (no knee: 3D classes keep their display).
_VOLUME_SLICE_SMOOTHING = 0.8
# The background is measured outside this fraction of the image radius.
_BACKGROUND_RADIUS = 0.75
# The background noise counts as at least this fraction of the spread of the
# particle area: a background a mask flattened (the solvent of a map) would
# otherwise blow its rounding ripples up into a checkered pattern.
_MIN_NOISE_FRACTION = 0.3
# Volumes are reduced to at most this size per side before rendering.
_VOLUME_MAX_DIM = 128
# The surface encloses the densest fraction of the volume.
_SURFACE_MASS_FRACTION = 0.06

VOLUME_VIEWS = ("surface", "projection", "slice")


def _gaussian(data, sigma):
    from scipy import ndimage
    return ndimage.gaussian_filter(data, sigma) if sigma else data


def _radialDistance(shape):
    height, width = shape
    yy, xx = np.mgrid[:height, :width]
    return np.hypot(yy - (height - 1) / 2, xx - (width - 1) / 2) / (min(height, width) / 2)


def _resizeUnit(values, size: int) -> np.ndarray:
    """A [0, 1] float image (2D, or 3 channels) resized with Lanczos, as uint8."""
    from PIL import Image
    size = max(1, int(size))
    if values.ndim == 2:
        image = Image.fromarray(values.astype(np.float32), mode="F").resize((size, size), Image.LANCZOS)
        return (np.clip(np.asarray(image), 0, 1) * 255).round().astype(np.uint8)
    channels = [_resizeUnit(values[..., channel], size) for channel in range(values.shape[-1])]
    return np.dstack(channels)


def displayClassAverage(image, size: int, smoothing: float = _CLASS_SMOOTHING,
                        knee: float = _SIGNAL_KNEE_SIGMA, noiseFloor: float = _NOISE_FLOOR_SIGMA) -> np.ndarray:
    """A uint8 (size x size) display image of a 2D class average."""
    data = np.asarray(image, dtype=np.float64)
    if data.ndim != 2 or data.size == 0:
        return np.zeros((size, size), dtype=np.uint8)
    finite = np.isfinite(data)
    if not finite.any():
        return np.zeros((size, size), dtype=np.uint8)
    data = np.where(finite, data, np.median(data[finite]))

    # An area the plugin masked holds one exact value over a large part of the image.
    values, counts = np.unique(data, return_counts=True)
    masked = (data == values[counts.argmax()]) if counts.max() > 0.05 * data.size else np.zeros(data.shape, bool)
    valid = ~masked
    if valid.sum() < 16:
        return np.full((size, size), 64, dtype=np.uint8)

    data = _gaussian(np.where(valid, data, np.median(data[valid])), smoothing)
    distance = _radialDistance(data.shape)
    radius = float(distance[valid].max())
    ring = valid & (distance > _BACKGROUND_RADIUS * radius)
    background = data[ring] if ring.sum() > 50 else data[valid]
    center = float(np.median(background))
    noise = float(1.4826 * np.median(np.abs(background - center)))
    inner = data[valid & (distance <= _BACKGROUND_RADIUS * radius)]
    if inner.size > 50:
        q1, q3 = np.percentile(inner, [25, 75])
        noise = max(noise, _MIN_NOISE_FRACTION * float(q3 - q1) / 1.349)
    noise = noise or float(data[valid].std()) or 1.0
    scaled = (data - center) / noise

    # Two linear pieces: the noise up to the knee rises slowly from black
    # through the background gray (its mean), the signal above it goes on to
    # white. Every class then shows its background at the same gray.
    high = max(float(np.percentile(scaled[valid], _SIGNAL_PERCENTILE)), knee + 1.0)
    backgroundLevel = _BACKGROUND_LEVEL
    kneeLevel = backgroundLevel * (knee + noiseFloor) / noiseFloor
    unit = np.where(
        scaled < knee,
        backgroundLevel * (scaled + noiseFloor) / noiseFloor,
        kneeLevel + (1 - kneeLevel) * (scaled - knee) / (high - knee),
    )
    unit = np.clip(unit, 0, 1)
    # The masked area shows as background, and the image fades into it at its border.
    unit = np.where(valid, unit, backgroundLevel)
    fade = np.clip((radius * 0.98 - distance) / (0.12 * radius), 0, 1)
    weight = 0.5 - 0.5 * np.cos(np.pi * fade)
    unit = unit * weight + backgroundLevel * (1 - weight)
    return _resizeUnit(unit, size)


def shrinkVolume(volume, maxDim: int = _VOLUME_MAX_DIM) -> np.ndarray:
    """The volume binned (block mean) to at most maxDim voxels per side."""
    volume = np.asarray(volume, dtype=np.float64)
    factor = int(np.ceil(max(volume.shape) / float(maxDim)))
    if factor <= 1:
        return volume
    z, y, x = (side // factor * factor for side in volume.shape)
    return volume[:z, :y, :x].reshape(z // factor, factor, y // factor, factor,
                                      x // factor, factor).mean(axis=(1, 3, 5))


def _surface(volume, size: int, massFraction: float, smoothing: float, largestBody: bool = True) -> np.ndarray:
    """A lit isosurface seen along Z: the densest connected body of the volume (or all of them)."""
    from scipy import ndimage

    data = _gaussian(volume, smoothing)
    threshold = float(np.quantile(data, 1 - massFraction))
    if threshold >= float(data.max()):
        # Few distinct values (a binary mask): the surface between them.
        threshold = 0.5 * (float(data.min()) + float(data.max()))
    labels, count = ndimage.label(data > threshold) if largestBody else (None, 0)
    if count > 1:
        sizes = ndimage.sum(np.ones_like(data), labels, index=range(1, count + 1))
        body = labels == (int(np.argmax(sizes)) + 1)
        data = np.where(ndimage.binary_dilation(body, iterations=1), data, np.minimum(data, threshold - 1e-9))
    inside = data > threshold
    hit = inside.any(axis=0)
    background = np.array([0.08, 0.09, 0.11])
    if not hit.any():
        return _resizeUnit(np.broadcast_to(background, data.shape[1:] + (3,)).copy(), size)

    first = inside.argmax(axis=0)
    yy, xx = np.indices(first.shape)
    before = np.clip(first - 1, 0, None)
    a, b = data[before, yy, xx], data[first, yy, xx]
    step = np.where(np.abs(b - a) > 1e-12, (threshold - a) / (b - a + 1e-12), 0.0)
    depth = np.where(hit, before + np.clip(step, 0, 1), float(data.shape[0]))
    farthest = float(depth[hit].max())
    gy, gx = np.gradient(ndimage.gaussian_filter(np.where(hit, depth, farthest), 0.7))
    normal = np.dstack([-gx, -gy, np.ones_like(gx)])
    normal /= np.linalg.norm(normal, axis=2, keepdims=True)
    light = np.array([-0.4, -0.5, 0.77])
    light /= np.linalg.norm(light)
    halfway = light + np.array([0.0, 0.0, 1.0])
    halfway /= np.linalg.norm(halfway)
    diffuse = np.clip((normal * light).sum(axis=2), 0, 1)
    specular = np.clip((normal * halfway).sum(axis=2), 0, 1) ** 24
    nearness = 1 - (depth - float(depth[hit].min())) / (float(np.ptp(depth[hit])) + 1e-9)
    shade = (0.18 + 0.62 * diffuse + 0.25 * specular) * (0.75 + 0.25 * nearness)
    protein = np.array([0.55, 0.72, 0.95])
    rgb = np.empty(depth.shape + (3,))
    rgb[:] = background
    rgb[hit] = np.clip(shade[hit, None] * protein + 0.12 * specular[hit, None], 0, 1)
    return _resizeUnit(rgb, size)


def renderClassVolume(volume, size: int, view: str = "surface") -> np.ndarray:
    """A display image of a 3D class: a lit surface (RGB), a projection or the central slice."""
    data = np.squeeze(np.asarray(volume, dtype=np.float64))
    if data.ndim == 2:
        return displayClassAverage(data, size)
    if data.ndim != 3 or data.size == 0:
        return np.zeros((size, size), dtype=np.uint8)
    data = np.where(np.isfinite(data), data, np.nanmedian(data) if np.isfinite(data).any() else 0.0)
    data = shrinkVolume(data)
    if view == "projection":
        return displayClassAverage(data.sum(axis=0), size, smoothing=0.6, knee=0.0,
                                   noiseFloor=_VOLUME_NOISE_FLOOR_SIGMA)
    if view == "slice":
        return displayClassAverage(data[data.shape[0] // 2], size, smoothing=_VOLUME_SLICE_SMOOTHING, knee=0.0,
                                   noiseFloor=_VOLUME_NOISE_FLOOR_SIGMA)
    return _surface(data, size, _SURFACE_MASS_FRACTION, smoothing=1.0)


def readClassRepresentative(filePath: str, index: Optional[int]) -> np.ndarray:
    """The original data of a representative: ``index`` (1-based) of a stack, or the whole file.

    Read with pwem's readers (MRC files through mrcfile, in Python): a broken
    file raises an error instead of bringing the server process down.
    """
    from pwem.emlib.image.image_readers import ImageReadersRegistry
    location = "%d@%s" % (index, filePath) if index else str(filePath)
    images = ImageReadersRegistry.open(location).getImages()
    if isinstance(images, list):
        images = images[0] if len(images) == 1 else np.stack(images)
    return np.asarray(images)


_MRC_EXTENSIONS = (".mrc", ".mrcs", ".map", ".st", ".ali", ".rec")


def readVolumeForDisplay(filePath: str, index: Optional[int] = None):
    """The volume of a file, memory mapped when possible (tomograms can be large).

    ``index`` (1-based) selects one volume of a stack of volumes.
    """
    path = str(filePath)
    if path.lower().endswith(_MRC_EXTENSIONS):
        import mrcfile
        data = mrcfile.mmap(path, mode="r", permissive=True).data
        if data.ndim == 4 and index:
            data = data[index - 1]
        return data
    return readClassRepresentative(path, index)


def shrinkVolumeInSlabs(volume, maxDim: int) -> np.ndarray:
    """shrinkVolume reading a few planes at a time, for memory mapped volumes.

    Every axis is reduced by the same factor, but never below one voxel (a
    thin tomogram keeps its few planes).
    """
    from app.backend.utils.volume_stack import binVolume

    return binVolume(volume, int(np.ceil(max(volume.shape) / float(maxDim))))


def _finite(data: np.ndarray) -> np.ndarray:
    finite = np.isfinite(data)
    if finite.all():
        return data
    return np.where(finite, data, np.median(data[finite]) if finite.any() else 0.0).astype(np.float32)


def renderVolumeImage(volume, size: int, view: str = "slice") -> Optional[np.ndarray]:
    """A display image of any volume (map, tomogram, mask): a lit surface (RGB),
    its projection or its central slice. None when it is not 3D."""
    from app.backend.utils.image_display import reduceForDisplay, toDisplayUint8

    if getattr(volume, "ndim", 0) != 3 or min(volume.shape) < 2:
        return None
    if view == "slice":
        central = _finite(np.asarray(volume[volume.shape[0] // 2], dtype=np.float32))
        return toDisplayUint8(reduceForDisplay(central, size))
    if view == "projection":
        reduced = _finite(shrinkVolumeInSlabs(volume, min(max(int(size), _VOLUME_MAX_DIM), 256)))
        return toDisplayUint8(reduceForDisplay(reduced.sum(axis=0), size))
    reduced = _finite(shrinkVolumeInSlabs(volume, _VOLUME_MAX_DIM))
    # Every body: a map or a mask may hold several on purpose.
    return _surface(reduced.astype(np.float64), size, _SURFACE_MASS_FRACTION, smoothing=1.0, largestBody=False)
