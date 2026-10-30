"""Movies in the metadata viewer are shown as the mean of their frames: one frame is mostly noise."""
import importlib
import io

import numpy as np
import pytest
from PIL import Image
from pwem.emlib.image.image_readers import ImageStack


@pytest.fixture
def outputsPreviewModule(authTestEnv):
    return importlib.import_module("app.backend.utils.outputs_preview")


@pytest.fixture
def projectServiceClass(authTestEnv):
    return importlib.import_module("app.backend.api.services.project_service").ProjectService


def _movieFrames(count=16, size=256, seed=3):
    """Frames of a faint disc under noise much stronger than it."""
    rng = np.random.RandomState(seed)
    yy, xx = np.ogrid[:size, :size]
    disc = ((xx - size / 2) ** 2 + (yy - size / 2) ** 2 < (size / 4) ** 2).astype(np.float32)
    return [disc * 0.5 + rng.normal(0, 4, (size, size)).astype(np.float32) for _ in range(count)], disc > 0


def _pixels(response):
    return np.asarray(Image.open(io.BytesIO(response.body)).convert("L"), dtype=np.float32)


def _discContrast(response, mask):
    pixels = _pixels(response)
    mask = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).resize(pixels.shape[::-1])) > 127
    return (pixels[mask].mean() - pixels[~mask].mean()) / pixels.std()


def _preview(module):
    return module.OutputsPreview(currentProject=None, protocol=None, output=None)


def _noReader(module, monkeypatch):
    def refuse(_path):
        raise AssertionError("This movie is read on its own, not through pwem's reader")

    monkeypatch.setattr(module.ImageReadersRegistry, "open", staticmethod(refuse))


def _writeMrcMovie(path, frames):
    import mrcfile

    with mrcfile.new(str(path), overwrite=True) as mrc:
        mrc.set_data(np.stack(frames).astype(np.float32))


def test_an_mrc_movie_is_drawn_from_the_mean_of_a_few_frames_read_from_a_memory_map(
        outputsPreviewModule, tmp_path, monkeypatch):
    frames, disc = _movieFrames(count=16, size=1024)
    path = tmp_path / "movie.mrcs"
    _writeMrcMovie(path, frames)
    _noReader(outputsPreviewModule, monkeypatch)

    cell = _preview(outputsPreviewModule).renderImageFromFilePath(
        path, size=64, fmt="png", index=0, applyTransform=False, averageFrames=True)

    assert _discContrast(cell, disc) > 1.0
    assert len(outputsPreviewModule.movieFrames(path)) == outputsPreviewModule.MOVIE_PREVIEW_FRAMES


def test_one_frame_of_a_movie_hides_what_the_mean_shows(outputsPreviewModule, tmp_path, monkeypatch):
    frames, disc = _movieFrames(count=16, size=256)
    path = tmp_path / "movie.mrcs"
    _writeMrcMovie(path, frames)
    preview = _preview(outputsPreviewModule)

    oneFrame = preview.renderImageFromFilePath(path, size=64, fmt="png", index=0, applyTransform=False)
    mean = preview.renderImageFromFilePath(path, size=64, fmt="png", index=0, applyTransform=False,
                                           averageFrames=True)

    # Two frames halve the noise power: about 1.4 times the contrast of one
    assert _discContrast(mean, disc) > 1.2 * _discContrast(oneFrame, disc)


def test_a_small_cell_shows_what_a_big_preview_shows(outputsPreviewModule, tmp_path, monkeypatch):
    """The contrast is set at the reference size: set on the cell, it closed on the noise left and
    burnt the cell to black and white."""
    frames, _ = _movieFrames(count=4, size=2048)
    path = tmp_path / "movie.mrcs"
    _writeMrcMovie(path, frames)
    preview = _preview(outputsPreviewModule)

    cell = _pixels(preview.renderImageFromFilePath(path, size=64, fmt="png", index=0, applyTransform=False,
                                                   averageFrames=True))
    big = _pixels(preview.renderImageFromFilePath(path, size=512, fmt="png", index=0, applyTransform=False,
                                                  averageFrames=True))

    saturated = np.mean((cell == 0) | (cell == 255))
    assert saturated < 0.02
    shrunk = np.asarray(Image.fromarray(big.astype(np.uint8)).resize(cell.shape[::-1], Image.LANCZOS),
                        dtype=np.float32)
    assert np.abs(cell - shrunk).mean() < 3


def _writeTiffMovie(path, frames):
    # LZW, as many K2/K3 movies are written: pwem's reader needs imagecodecs for it, Pillow does not
    pages = [Image.fromarray(np.clip(frame + 8, 0, 255).astype(np.uint8)) for frame in frames]
    pages[0].save(path, save_all=True, append_images=pages[1:], compression="tiff_lzw")


def test_a_tiff_movie_is_drawn_from_its_first_frame_read_with_pillow(outputsPreviewModule, tmp_path, monkeypatch):
    rng = np.random.RandomState(5)
    yy, xx = np.ogrid[:1024, :1024]
    disc = (xx - 512) ** 2 + (yy - 512) ** 2 < 256 ** 2
    # Counts, mostly 0 and 1, as an electron-counting frame: one 8-bit frame of them turned black
    frames = [rng.poisson(np.where(disc, 0.6, 1.0)).astype(np.float32) - 8 for _ in range(12)]
    path = tmp_path / "movie.tif"
    _writeTiffMovie(path, frames)
    _noReader(outputsPreviewModule, monkeypatch)

    cell = _preview(outputsPreviewModule).renderImageFromFilePath(
        path, size=64, fmt="png", index=0, applyTransform=False, averageFrames=True)

    pixels = _pixels(cell)
    assert 60 < pixels.mean() < 200
    assert _discContrast(cell, disc) < -1.0  # the disc gets fewer electrons: darker
    assert len(outputsPreviewModule.movieFrames(path)) == 1


def test_other_movie_formats_use_pwems_reader(outputsPreviewModule, tmp_path, monkeypatch):
    frames, disc = _movieFrames(count=8, size=512)
    path = tmp_path / "movie.stk"
    path.write_bytes(b"placeholder")
    monkeypatch.setattr(outputsPreviewModule.ImageReadersRegistry, "open",
                        staticmethod(lambda p: ImageStack(np.stack(frames))))

    cell = _preview(outputsPreviewModule).renderImageFromFilePath(
        path, size=64, fmt="png", index=0, applyTransform=False, averageFrames=True)

    assert _discContrast(cell, disc) > 1.0


def test_a_single_image_is_drawn_as_before(outputsPreviewModule, tmp_path, monkeypatch):
    frames, _ = _movieFrames(count=1)
    path = tmp_path / "image.stk"
    path.write_bytes(b"placeholder")
    monkeypatch.setattr(outputsPreviewModule.ImageReadersRegistry, "open",
                        staticmethod(lambda p: ImageStack(np.stack(frames))))
    preview = _preview(outputsPreviewModule)

    plain = preview.renderImageFromFilePath(path, size=64, fmt="png", index=0, applyTransform=False)
    averaged = preview.renderImageFromFilePath(path, size=64, fmt="png", index=0, applyTransform=False,
                                               averageFrames=True)

    assert plain.body == averaged.body


class _Dao:
    def __init__(self, setClassName):
        self.setClassName = setClassName

    def _getStoredSetHeader(self):
        return {"setClassName": self.setClassName}


class _Manager:
    def __init__(self, setClassName):
        self._dao = _Dao(setClassName)


class _Table:
    def __init__(self, alias):
        self.alias = alias

    def getAlias(self):
        return self.alias


@pytest.mark.parametrize("setClassName, isMovie", [
    ("SetOfMovies", True), ("SetOfTiltSeriesM", True), ("SetOfMicrographs", False), ("SetOfParticles", False),
])
def test_movie_tables_are_told_by_their_set_class(projectServiceClass, setClassName, isMovie):
    assert projectServiceClass._isMetadataMovieOutput(_Manager(setClassName), _Table("")) is isMovie


def test_without_a_stored_header_the_table_alias_tells_a_movie(projectServiceClass):
    class NoHeader:
        _dao = None

    assert projectServiceClass._isMetadataMovieOutput(NoHeader(), _Table("Movie")) is True
    assert projectServiceClass._isMetadataMovieOutput(NoHeader(), _Table("Micrograph")) is False


def test_cells_drawn_before_are_not_served_from_the_cache(projectServiceClass, authTestEnv):
    module = importlib.import_module("app.backend.api.services.project_service")
    key = projectServiceClass._buildMetadataImageCacheKey(
        projectId=1, protocolId=2, outputName="outputMovies", tableName="objects", rowId=None, rowIndex=0,
        columnName="_filename", size=128, applyTransform=False, fmt="png", sortBy="id", asc=True)
    assert module.METADATA_IMAGE_DISPLAY_VERSION in key



def test_a_short_tiff_movie_is_read_whole(outputsPreviewModule, tmp_path):
    """A tilt of a tilt series movie holds a few e/A^2 over a few frames: one frame holds too little."""
    frames, _ = _movieFrames(count=3, size=256)
    path = tmp_path / "tilt.tif"
    _writeTiffMovie(path, frames)

    read = outputsPreviewModule.movieFrames(path, size=64)

    assert len(read) == 3
    expected = np.mean([np.clip(frame + 8, 0, 255).astype(np.uint8).astype(np.float32) for frame in frames], axis=0)
    mean = outputsPreviewModule.movieMeanImage(path, 512)
    assert mean.shape == expected.shape and np.allclose(mean, expected, atol=1e-4)


def test_a_single_image_has_no_movie_mean(outputsPreviewModule, tmp_path):
    path = tmp_path / "micrograph.mrc"
    _writeMrcMovie(path, [np.zeros((16, 16), dtype=np.float32)])

    assert outputsPreviewModule.movieMeanImage(path, 512) is None
