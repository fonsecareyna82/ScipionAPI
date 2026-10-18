import numpy as np

from app.backend.utils import tilt_series_stack as stack


def _noisyImage(height=300, width=200, seed=1):
    rng = np.random.default_rng(seed)
    return (100 + 10 * rng.normal(size=(height, width))).astype(np.float32)


def test_BinningAveragesBlocksDownToTheLargestSide():
    image = np.arange(12 * 8, dtype=np.float32).reshape(12, 8)

    binned, factor = stack.binImage(image, maxDim=6)

    assert factor == 2
    assert binned.shape == (6, 4)
    assert binned[0, 0] == np.mean([0, 1, 8, 9])
    assert stack.binImage(image, maxDim=64)[1] == 1


def test_HotPixelsDoNotChangeTheContrast():
    image = _noisyImage()
    clean = stack.reduceTiltImage(image, 1024)
    image[5, 5] = 1e6
    image[7, 9] = -1e6
    withOutliers = stack.reduceTiltImage(image, 1024)

    assert abs(withOutliers["mean"] - clean["mean"]) < 0.1
    assert abs(withOutliers["std"] - clean["std"]) < 0.1
    # The noise spreads over many gray levels, not a few.
    assert len(np.unique(withOutliers["data"])) > 100


def test_TheStackKeepsEveryImageAndItsDescription():
    frames = [
        {"index": 3, "rot": 85.0, "shiftX": 1.5, "shiftY": -2.0, **stack.reduceTiltImage(_noisyImage(seed=3), 128)},
        {"index": 4, "error": "Tilt image not found"},
        {"index": 5, "rot": None, "shiftX": None, "shiftY": None, **stack.reduceTiltImage(_noisyImage(41, 33, 5), 128)},
    ]

    decoded = stack.decodeTiltSeriesStack(stack.encodeTiltSeriesStack({"tiltSeriesId": "TS_1"}, frames))

    assert decoded["tiltSeriesId"] == "TS_1"
    assert [frame["index"] for frame in decoded["frames"]] == [3, 4, 5]
    assert decoded["frames"][1] == {"index": 4, "error": "Tilt image not found"}
    for original, frame in zip(frames[::2], decoded["frames"][::2]):
        assert (frame["data"] == original["data"]).all()
        assert frame["width"] == original["width"] and frame["height"] == original["height"]
    assert decoded["frames"][0]["rot"] == 85.0
    assert decoded["frames"][0]["binning"] == 3


def test_ReducedImagesAreKeptByKey():
    stack.clearFrameCache()
    loads = []

    def load():
        loads.append(1)
        return stack.reduceTiltImage(_noisyImage(), 64)

    first = stack.cachedReducedTiltImage(("a.mrc", 1.0, 0, 64), load)
    again = stack.cachedReducedTiltImage(("a.mrc", 1.0, 0, 64), load)
    stack.cachedReducedTiltImage(("a.mrc", 2.0, 0, 64), load)

    assert again is first
    assert len(loads) == 2


def test_IndicesAreReadInOrderWithoutRepeats():
    assert stack.parseIndices("4, 2,x,4,-1,7", 3) == [4, 2, 7]
    assert stack.parseIndices("", 10) is None
    assert stack.parseIndices(None, 10) is None
