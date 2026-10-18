import mrcfile
import numpy as np

from app.backend.utils.thumbnail_service import ThumbnailService


def _service():
    return ThumbnailService.__new__(ThumbnailService)


def test_TilesAreReadFromTheOriginalValuesWithHotPixels(tmp_path):
    rng = np.random.default_rng(3)
    image = (100 + 10 * rng.normal(size=(600, 400))).astype(np.float32)
    image[5, 5] = 1e7
    path = tmp_path / "mic.mrc"
    with mrcfile.new(str(path)) as mrc:
        mrc.set_data(image)

    tile = _service()._read2dTile(path, thumbSize=200)

    assert tile.shape == (200, 133)
    # The noise spreads over the gray range instead of collapsing near black.
    assert len(np.unique(tile)) > 100
    assert 100 < float(np.median(tile)) < 155


def test_MoviesShowTheMeanOfSeveralFrames(tmp_path):
    from pwem.emlib.image.image_readers import ImageReadersRegistry

    rng = np.random.default_rng(5)
    signal = np.zeros((64, 64), dtype=np.float32)
    signal[20:44, 20:44] = 1.0
    frames = np.stack([signal + 3 * rng.normal(size=signal.shape) for _ in range(12)]).astype(np.float32)
    path = tmp_path / "movie.mrcs"
    with mrcfile.new(str(path)) as mrc:
        mrc.set_data(frames)

    averaged = np.asarray(_service()._averageMovieFrames(ImageReadersRegistry.open(str(path))), dtype=float)

    # The square stands out from the noise once frames are averaged.
    assert averaged[24:40, 24:40].mean() - averaged[:12, :12].mean() > 25
