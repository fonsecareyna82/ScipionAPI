import importlib

import numpy as np
import pytest


def getEnhancer():
    module = importlib.import_module(
        "app.backend.utils.metadata_image_contrast"
    )
    return module.enhanceClassAverageContrast


def makeClassAverage():
    rng = np.random.RandomState(19)
    yy, xx = np.ogrid[:96, :96]
    radius2 = (xx - 48) ** 2 + (yy - 48) ** 2

    # Weak background, bright molecular density, and a negative ring.
    image = rng.normal(0.0, 0.025, (96, 96)).astype(np.float32)
    image[radius2 <= 11 ** 2] += 0.42
    image[(radius2 > 13 ** 2) & (radius2 < 17 ** 2)] -= 0.14
    return image


def test_EnhanceClassAverageContrastDarkensBackgroundAndPreservesSignal():
    enhance = getEnhancer()
    source = makeClassAverage()
    output = enhance(source)

    assert output.shape == source.shape
    assert output.dtype == np.uint8

    background = output[0:24, 0:24]
    molecularDensity = output[44:52, 44:52]
    negativeRing = output[46:50, 63:65]

    assert float(np.median(background)) < 85.0
    assert float(np.median(molecularDensity)) > 175.0
    assert float(np.median(negativeRing)) < float(np.median(background))


def test_EnhanceClassAverageContrastResistsAnExtremeOutlier():
    enhance = getEnhancer()
    source = makeClassAverage()
    reference = enhance(source)
    source[0, 0] = 1000.0

    result = enhance(source)

    # One extreme sample must not wash out the rest of the image.
    np.testing.assert_allclose(
        result[32:64, 32:64].astype(np.float32),
        reference[32:64, 32:64].astype(np.float32),
        atol=18.0,
    )
    assert float(np.median(result[44:52, 44:52])) > 175.0


def test_EnhanceClassAverageContrastHandlesNonfinitePixelsWithoutMutatingSource():
    enhance = getEnhancer()
    source = makeClassAverage()
    source[0, 0] = np.nan
    source[0, 1] = np.inf
    source[0, 2] = -np.inf
    before = source.copy()

    result = enhance(source)

    assert result.dtype == np.uint8
    assert result.shape == source.shape
    assert np.isfinite(result).all()
    np.testing.assert_array_equal(source, before)


def test_EnhanceClassAverageContrastHandlesConstantImage():
    enhance = getEnhancer()
    source = np.full((32, 32), 0.5, dtype=np.float32)

    result = enhance(source)

    assert result.shape == source.shape
    assert result.dtype == np.uint8
    assert np.unique(result).size == 1
    np.testing.assert_array_equal(source, np.full((32, 32), 0.5))


def test_EnhanceClassAverageContrastRejectsNon2DData():
    enhance = getEnhancer()

    with pytest.raises(ValueError, match="2D"):
        enhance(np.zeros((4, 4, 3), dtype=np.float32))
