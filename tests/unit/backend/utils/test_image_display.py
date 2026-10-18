import numpy as np

from app.backend.utils.image_display import reduceForDisplay, toDisplayUint8


def _micrograph(height=1000, width=700, seed=2):
    rng = np.random.default_rng(seed)
    return (500 + 20 * rng.normal(size=(height, width))).astype(np.float32)


def test_ReducesToTheExactSizeFromTheOriginalValues():
    reduced = reduceForDisplay(_micrograph(), 256)

    assert reduced.dtype == np.float32
    assert max(reduced.shape) == 256
    assert reduced.shape == (256, 179)
    # Averaging keeps the values (no 8-bit step on the way).
    assert abs(float(reduced.mean()) - 500) < 1
    assert reduceForDisplay(_micrograph(100, 80), 256).shape == (100, 80)


def test_HotPixelsDoNotFlattenTheImage():
    image = _micrograph()
    image[10, 10] = 1e7
    image[20, 30] = -1e7

    shown = toDisplayUint8(reduceForDisplay(image, 512))

    # The noise spans the gray range instead of a few levels around the middle.
    assert len(np.unique(shown)) > 150
    assert 100 < float(np.median(shown)) < 155


def test_NonFiniteValuesDoNotBreakTheImage():
    image = _micrograph(64, 64)
    image[0, :] = np.nan
    image[1, :] = np.inf

    shown = toDisplayUint8(reduceForDisplay(image, 32))

    assert shown.shape == (32, 32)
    assert len(np.unique(shown)) > 20
