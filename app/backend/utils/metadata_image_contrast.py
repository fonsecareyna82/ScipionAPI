"""Display-only contrast enhancement for cryo-EM class-average images.

This transforms a 2-D grayscale array into viewable 8-bit pixels. It must
never change a scientific image stored in Scipion or its metadata.
"""

import numpy as np


# Robust percentile clipping avoids washing out the rest of an image when
# a few isolated pixels are abnormally bright or dark.
_CLASS_AVERAGE_LOWER_PERCENTILE = 0.5
_CLASS_AVERAGE_UPPER_PERCENTILE = 99.5

# A monotone gamma > 1 darkens the background while retaining the ordering
# of intensities, including negative-density contours.
_CLASS_AVERAGE_DISPLAY_GAMMA = 1.45


def enhanceClassAverageContrast(image):
    """Return a high-contrast uint8 *display image* from a 2-D input array.

    Uses per-image percentile windowing followed by a monotone gamma curve.
    Does not mutate the source or invert its contrast. NaN/Inf values are
    filled using the finite median. Empty/invalid inputs have a stable
    fallback and constant images remain uniform.
    """
    original = np.asarray(image)
    if original.ndim != 2:
        raise ValueError("Class-average contrast enhancement expects a 2D image")

    if original.size == 0:
        return np.zeros(original.shape, dtype=np.uint8)

    # Float64 keeps the range computation stable for both integral and
    # floating-point source images without modifying the original object.
    pixels = original.astype(np.float64, copy=True)
    finiteMask = np.isfinite(pixels)

    if not finiteMask.any():
        return np.zeros(pixels.shape, dtype=np.uint8)

    finiteValues = pixels[finiteMask]
    lower, upper = np.percentile(
        finiteValues,
        (_CLASS_AVERAGE_LOWER_PERCENTILE, _CLASS_AVERAGE_UPPER_PERCENTILE),
    )

    if not np.isfinite(lower) or not np.isfinite(upper) or upper <= lower:
        return np.full(pixels.shape, 127, dtype=np.uint8)

    if not finiteMask.all():
        pixels[~finiteMask] = float(np.median(finiteValues))

    normalized = np.clip((pixels - lower) / (upper - lower), 0.0, 1.0)
    enhanced = np.power(normalized, _CLASS_AVERAGE_DISPLAY_GAMMA)
    return np.rint(enhanced * 255.0).astype(np.uint8)
