import mrcfile
import numpy as np

from app.backend.utils import volume_stack


def test_TheFactorKeepsTheVolumeWithinTheVoxelBudget():
    assert volume_stack.volumeBinningFactor((300, 1024, 1024), 64_000_000) == 2
    assert volume_stack.volumeBinningFactor((100, 512, 512), 64_000_000) == 1
    assert volume_stack.volumeBinningFactor((500, 2048, 2048), 64_000_000) == 4


def test_BinningAveragesBlocksWithoutDroppingThinAxes():
    volume = np.arange(4 * 8 * 6, dtype=np.float32).reshape(4, 8, 6)

    binned = volume_stack.binVolume(volume, 2)

    assert binned.shape == (2, 4, 3)
    assert binned[0, 0, 0] == volume[:2, :2, :2].mean()
    assert volume_stack.binVolume(np.ones((2, 40, 40), dtype=np.float32), 8).shape == (1, 5, 5)


def test_TheReducedVolumeRoundTripsWithOneWindowForEverySlice():
    rng = np.random.default_rng(4)
    volume = (100 + 10 * rng.normal(size=(20, 30, 40))).astype(np.float32)
    volume[0, 0, 0] = 1e6

    reduced = volume_stack.reduceVolumeForViewer(volume, 4000)
    decoded = volume_stack.decodeVolumeStack(volume_stack.encodeVolumeStack(reduced))

    assert (decoded["depth"], decoded["height"], decoded["width"]) == reduced["data"].shape
    assert decoded["binning"] == [40 // decoded["width"], 30 // decoded["height"], 20 // decoded["depth"]]
    assert (decoded["data"] == reduced["data"]).all()
    assert abs(decoded["mean"] - 100) < 1
    assert decoded["low"] < 100 < decoded["high"]
