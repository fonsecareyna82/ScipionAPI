"""Display images of class representatives, drawn from their original data."""
import numpy as np
import pytest

from app.backend.utils import class_average_display as display


def classAverage(size=64, signal=5.0, seed=0, masked=False):
    rng = np.random.default_rng(seed)
    image = rng.normal(0.0, 1.0, (size, size))
    yy, xx = np.mgrid[:size, :size]
    distance = np.hypot(yy - size / 2, xx - size / 2)
    image[distance < size / 8] += signal
    if masked:
        image[distance > size * 0.45] = 0.0  # As plugins mask their averages.
    return image


def test_background_noise_shows_at_the_same_gray_in_every_class():
    weak = display.displayClassAverage(classAverage(signal=3, seed=1), 64)
    strong = display.displayClassAverage(classAverage(signal=8, seed=2) * 50 + 1000, 64)
    corner = (slice(4, 10), slice(30, 34))
    # Different scales and offsets, a similar dark background.
    assert abs(float(weak[corner].mean()) - float(strong[corner].mean())) < 30
    assert weak[corner].mean() < 110
    # The particle stands out.
    assert weak[28:36, 28:36].mean() > weak[corner].mean() + 80


def test_the_area_a_plugin_masked_shows_as_background():
    image = display.displayClassAverage(classAverage(masked=True), 64)
    assert image.shape == (64, 64) and image.dtype == np.uint8
    assert image[0, 0] == image[0, 63] == image[63, 0]
    assert image[32, 32] > image[0, 0] + 80


def test_a_flattened_background_does_not_turn_into_a_checkered_pattern():
    # A map's solvent, masked to almost zero: only tiny ripples are left there.
    image = classAverage(signal=4, seed=3)
    yy, xx = np.mgrid[:64, :64]
    outside = np.hypot(yy - 32, xx - 32) > 22
    image[outside] = 1e-4 * np.sin(xx[outside] * 0.6) * np.cos(yy[outside] * 0.5)
    shown = display.displayClassAverage(image, 64).astype(float)
    corner = shown[2:10, 26:38]
    assert corner.std() < 4
    assert shown[28:36, 28:36].mean() > corner.mean() + 60


def test_invalid_images_do_not_fail():
    assert display.displayClassAverage(np.full((32, 32), np.nan), 16).shape == (16, 16)
    assert display.displayClassAverage(np.zeros((32, 32)), 16).shape == (16, 16)
    assert display.displayClassAverage(np.zeros((2, 2, 2)), 16).shape == (16, 16)


def blob(size=48):
    zz, yy, xx = np.mgrid[:size, :size, :size] - size / 2
    volume = np.exp(-(zz ** 2 + yy ** 2 + (xx / 1.6) ** 2) / (2 * (size / 8) ** 2))
    return volume + np.random.default_rng(3).normal(0, 0.01, volume.shape)


def test_3d_classes_show_as_a_lit_surface_a_projection_or_a_slice():
    surface = display.renderClassVolume(blob(), 64, "surface")
    assert surface.shape == (64, 64, 3)
    # The body is lit, the background stays dark.
    assert surface[32, 32].mean() > 3 * surface[2, 2].mean()
    for view in ("projection", "slice"):
        image = display.renderClassVolume(blob(), 64, view)
        assert image.shape == (64, 64) and image[32, 32] > image[2, 2]


def test_big_volumes_are_reduced_before_rendering():
    assert display.shrinkVolume(np.zeros((300, 300, 300))).shape == (100, 100, 100)
    assert display.shrinkVolume(np.zeros((64, 64, 64))).shape == (64, 64, 64)


def test_representatives_are_read_from_their_original_data(tmp_path):
    mrcfile = pytest.importorskip("mrcfile")
    stack = np.stack([classAverage(32, seed=i).astype(np.float32) for i in range(3)])
    path = tmp_path / "classes.mrcs"
    with mrcfile.new(str(path)) as mrc:
        mrc.set_data(stack)
    second = display.readClassRepresentative(str(path), 2)
    assert second.shape == (32, 32)
    assert np.allclose(second, stack[1])
    volume = tmp_path / "class.mrc"
    with mrcfile.new(str(volume)) as mrc:
        mrc.set_data(blob(16).astype(np.float32))
    assert display.readClassRepresentative(str(volume), None).shape == (16, 16, 16)
