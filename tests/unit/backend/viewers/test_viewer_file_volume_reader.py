import mrcfile
import numpy as np

from app.backend.api.services import protocol_viewer_file_token_service as tokens
from app.backend.viewers.viewer_file_volume_reader import ViewerFileVolumeReader


def writeVolume(path, value):
    data = np.full((4, 5, 6), value, dtype=np.float32)
    with mrcfile.new(str(path), overwrite=True) as volume:
        volume.set_data(data)
        volume.voxel_size = 1.5


def test_reader_offers_the_token_volumes_with_the_output_reader_interface(tmp_path):
    (tmp_path / "Runs").mkdir()
    writeVolume(tmp_path / "Runs" / "a.mrc", 1.0)
    writeVolume(tmp_path / "Runs" / "b.mrc", 2.0)
    token = tokens.signViewerFileToken(3, ["Runs/a.mrc", "Runs/b.mrc"])
    reader = ViewerFileVolumeReader(tokens.resolveViewerFileTokenPaths(token, 3, str(tmp_path)))

    assert reader.hasOutput()
    assert [(v["id"], v["name"]) for v in reader.listVolumes()] == [(0, "a.mrc"), (1, "b.mrc")]
    info = reader.getVolumeInfo(1)
    assert info["dims"] == [4, 5, 6] and info["max"] == 2.0
    array, _props, _info = reader.getVolumeArray(0)
    assert array.shape == (4, 5, 6)
    assert reader.getVolumeFile(5) is None


def test_multi_file_tokens_are_not_single_metadata_files(tmp_path):
    token = tokens.signViewerFileToken(3, ["Runs/a.mrc", "Runs/b.mrc"])
    assert tokens.readViewerFileToken(token, 3) is None
    assert tokens.readViewerFileTokenPaths(token, 3) == ["Runs/a.mrc", "Runs/b.mrc"]
    assert tokens.readViewerFileTokenPaths(token, 4) is None
