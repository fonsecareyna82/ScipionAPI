import mrcfile
import numpy as np

from app.backend.utils.class_average_display import (
    readVolumeForDisplay,
    renderVolumeImage,
    shrinkVolumeInSlabs,
)


def _twoBalls(n=48):
    zz, yy, xx = np.indices((n, n, n))
    first = np.sqrt((zz - 16) ** 2 + (yy - 16) ** 2 + (xx - 16) ** 2) < 7
    second = np.sqrt((zz - 32) ** 2 + (yy - 32) ** 2 + (xx - 32) ** 2) < 7
    return (first | second).astype(np.float32)


def test_SlabShrinkingKeepsThinAxes():
    volume = np.ones((4, 400, 300), dtype=np.float32)

    reduced = shrinkVolumeInSlabs(volume, 100)

    assert reduced.shape == (1, 100, 75)
    assert np.allclose(reduced, 1)


def test_VolumesAreDrawnAsSurfaceProjectionOrSlice(tmp_path):
    path = tmp_path / "mask.mrc"
    with mrcfile.new(str(path)) as mrc:
        mrc.set_data(_twoBalls())
    volume = readVolumeForDisplay(str(path))

    surface = renderVolumeImage(volume, 128, "surface")
    projection = renderVolumeImage(volume, 128, "projection")
    central = renderVolumeImage(volume, 128, "slice")

    assert surface.shape == (128, 128, 3)
    assert projection.ndim == 2 and central.ndim == 2
    # A binary mask still has a surface, with both of its bodies.
    lit = surface.mean(axis=2) > surface.mean(axis=2).min() + 20
    assert lit[:64, :64].any() and lit[64:, 64:].any()
    assert renderVolumeImage(np.zeros((8, 8)), 64, "slice") is None
