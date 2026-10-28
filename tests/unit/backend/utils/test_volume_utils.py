# ******************************************************************************
# *
# * Authors:     Yunior C. Fonseca Reyna
# *
# * Unidad de  Bioinformatica of Centro Nacional de Biotecnologia , CSIC
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 3 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************
import importlib

import numpy as np
import pytest


@pytest.fixture
def volumeUtilsModule():
    return importlib.import_module(
        "app.backend.utils.volume_utils"
    )


def test_ReadVolumeArray3dUsesRegistryForMap(
    volumeUtilsModule,
    monkeypatch,
    tmp_path,
):
    volumePath = tmp_path / "volume.map"
    volumePath.write_bytes(b"placeholder")

    readerClass = (
        volumeUtilsModule
        .ImageReadersRegistry
        .getReader(str(volumePath))
    )

    assert readerClass is not volumeUtilsModule.MRCImageReader

    mappedCalls = []

    def readMrcVolumeMapped(signature):
        mappedCalls.append(signature)
        raise AssertionError(
            "Non-MRC readers must not use the MRC mmap path"
        )

    expected = np.arange(
        24,
        dtype=np.float32,
    ).reshape((2, 3, 4))

    monkeypatch.setattr(
        volumeUtilsModule,
        "_readMrcVolumeMapped",
        readMrcVolumeMapped,
    )
    monkeypatch.setattr(
        volumeUtilsModule,
        "_readVolumeCached",
        lambda signature: (expected, {}),
    )

    data, props = volumeUtilsModule.readVolumeArray3d(
        str(volumePath)
    )

    assert mappedCalls == []
    np.testing.assert_array_equal(data, expected)
    assert props == {}


def test_ReadVolumeArray3dUsesReadOnlyMmapForMrc(
    volumeUtilsModule,
    monkeypatch,
    tmp_path,
):
    volumePath = tmp_path / "volume.mrc"
    volumePath.write_bytes(b"placeholder")

    readerClass = (
        volumeUtilsModule
        .ImageReadersRegistry
        .getReader(str(volumePath))
    )

    assert readerClass is volumeUtilsModule.MRCImageReader

    expected = np.arange(
        24,
        dtype=np.float32,
    ).reshape((2, 3, 4))

    registryCalls = []

    monkeypatch.setattr(
        volumeUtilsModule,
        "_readMrcVolumeMapped",
        lambda signature: (
            expected,
            {"voxelSize": (1.0, 1.0, 1.0)},
            object(),
        ),
    )

    def readVolumeCached(signature):
        registryCalls.append(signature)
        raise AssertionError(
            "Valid MRC mmap must not use generic registry loading"
        )

    monkeypatch.setattr(
        volumeUtilsModule,
        "_readVolumeCached",
        readVolumeCached,
    )

    data, props = volumeUtilsModule.readVolumeArray3d(
        str(volumePath)
    )

    assert registryCalls == []
    np.testing.assert_array_equal(data, expected)
    assert props == {
        "voxelSize": (1.0, 1.0, 1.0),
    }


def test_ReadVolumeArray3dFallsBackToRegistryWhenMrcMmapFails(
    volumeUtilsModule,
    monkeypatch,
    tmp_path,
):
    volumePath = tmp_path / "volume.mrc"
    volumePath.write_bytes(b"placeholder")

    expected = np.arange(
        24,
        dtype=np.float32,
    ).reshape((2, 3, 4))

    monkeypatch.setattr(
        volumeUtilsModule,
        "_readMrcVolumeMapped",
        lambda signature: (_ for _ in ()).throw(
            RuntimeError("mmap failed")
        ),
    )
    monkeypatch.setattr(
        volumeUtilsModule,
        "_readVolumeCached",
        lambda signature: (
            expected,
            {"source": "registry"},
        ),
    )

    data, props = volumeUtilsModule.readVolumeArray3d(
        str(volumePath)
    )

    np.testing.assert_array_equal(data, expected)
    assert props == {
        "source": "registry",
    }

def test_VolumeDisplayWindowIgnoresOutliersAndFitsSmoothedSlices(volumeUtilsModule, tmp_path):
    import mrcfile

    rng = np.random.default_rng(5)
    volume = rng.normal(0.0, 1.0, size=(30, 48, 48)).astype(np.float32)
    volume[15, 5, 5] = 1000.0
    volumePath = tmp_path / "tomogram.mrc"
    with mrcfile.new(str(volumePath)) as mrc:
        mrc.set_data(volume)

    low, high = volumeUtilsModule.readVolumeDisplayWindow(str(volumePath))

    smoothed = volumeUtilsModule.smoothSliceForDisplay(volume[15])
    assert -3.0 < low < 0.0 < high < 3.0
    # Smoothing narrows the noise, and the window follows it
    assert high - low < 6.0 * float(np.std(volume))
    assert np.mean((smoothed > low) & (smoothed < high)) > 0.95


def test_SmoothSliceForDisplayToleratesNonFiniteValues(volumeUtilsModule):
    slice2d = np.ones((8, 8), dtype=np.float32)
    slice2d[3, 3] = np.nan

    smoothed = volumeUtilsModule.smoothSliceForDisplay(slice2d)

    assert np.isfinite(smoothed).all()
    np.testing.assert_allclose(smoothed, 1.0)
