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
from pathlib import Path

import numpy as np
import pytest
from PIL import Image


class FakeCurrentProject:
    # fakeCurrentProject
    def __init__(self, projectPath):
        self._projectPath = projectPath

    def getPath(self):
        return self._projectPath


@pytest.fixture
def thumbnailServiceModule(authTestEnv):
    # thumbnailServiceModule
    return importlib.import_module("app.backend.utils.thumbnail_service")


@pytest.fixture
def service(thumbnailServiceModule, tmp_path):
    # service
    projectPath = tmp_path / "DemoProject"
    projectPath.mkdir(parents=True, exist_ok=True)

    currentProject = FakeCurrentProject(str(projectPath))
    return thumbnailServiceModule.ThumbnailService(currentProject)


def test_NormalizeArrayToUint8ScalesFiniteData(service):
    array = np.array([[0.0, 1.0], [2.0, 3.0]], dtype=np.float32)

    result = service._normalizeArrayToUint8(array)

    assert result.dtype == np.uint8
    assert result.shape == (2, 2)
    assert int(result.min()) == 0
    assert int(result.max()) == 255


def test_NormalizeArrayToUint8HandlesNaNs(service):
    array = np.array([[0.0, np.nan], [np.inf, 1.0]], dtype=np.float32)

    result = service._normalizeArrayToUint8(array)

    assert result.dtype == np.uint8
    assert result.shape == (2, 2)


def test_GrayTileToImageReturnsRgbImage(service):
    gray = np.array([[0, 128], [255, 64]], dtype=np.uint8)

    image = service._grayTileToImage(gray)

    assert image is not None
    assert image.mode == "RGB"
    assert image.size == (2, 2)


def test_RgbTileToImageReturnsRgbImage(service):
    rgb = np.zeros((3, 4, 3), dtype=np.uint8)
    rgb[:, :, 0] = 255

    image = service._rgbTileToImage(rgb)

    assert image is not None
    assert image.mode == "RGB"
    assert image.size == (4, 3)


def test_ArrayToImageUsesColormap(service):
    array = np.array([[0.0, 0.5], [0.75, 1.0]], dtype=np.float32)

    image = service._arrayToImage(array, cmapName="viridis")

    assert image is not None
    assert image.mode == "RGB"
    assert image.size == (2, 2)


def test_ApplyColormapReturnsRgbUint8(service):
    gray = np.array([[0, 64], [128, 255]], dtype=np.uint8)

    rgb = service._applyColormap(gray, cmapName="viridis")

    assert rgb.dtype == np.uint8
    assert rgb.shape == (2, 2, 3)


def test_NormalizePilImageConvertsToRgb(service):
    image = Image.new("L", (10, 6), color=120)

    normalized = service._normalizePilImage(image)

    assert normalized.mode == "RGB"
    assert normalized.size == (10, 6)


def test_StatusAccentReturnsExpectedColors(service):
    assert service._statusAccent("finished") == (75, 170, 96)
    assert service._statusAccent("running") == (59, 130, 246)
    assert service._statusAccent("failed") == (220, 38, 38)
    assert service._statusAccent("unknown") == (148, 163, 184)


def test_MixColorInterpolatesBetweenTwoColors(service):
    mixed = service._mixColor((0, 0, 0), (255, 255, 255), 0.5)

    assert mixed == (128, 128, 128)


def test_BuildRoundedMaskCreatesExpectedSize(service):
    mask = service._buildRoundedMask((120, 80), radius=12)

    assert mask.mode == "L"
    assert mask.size == (120, 80)


def test_MakeProtocolPlaceholderPreviewBuildsCanvas(service):
    image = service._makeProtocolPlaceholderPreview(status="running", size=320)

    assert image.mode == "RGB"
    assert image.size[0] >= 180
    assert image.size[1] >= 120


def test_FinalizeProtocolThumbnailProducesExpectedAspect(service):
    preview = Image.new("RGB", (120, 120), color=(200, 200, 200))

    thumb = service._finalizeProtocolThumbnail(
        previewImage=preview,
        size=320,
        protocolId=10,
    )

    assert thumb.mode == "RGB"
    assert thumb.size == (
        320,
        192,
    )


def test_ComposeProjectStripBuildsHorizontalCanvas(service, tmp_path):
    img1 = tmp_path / "thumb1.png"
    img2 = tmp_path / "thumb2.png"

    Image.new("RGB", (120, 80), color=(255, 0, 0)).save(img1)
    Image.new("RGB", (120, 80), color=(0, 255, 0)).save(img2)

    strip = service._composeProjectStrip(
        items=[
            {"absolutePath": str(img1)},
            {"absolutePath": str(img2)},
        ],
        size=720,
    )

    assert strip.mode == "RGB"
    assert strip.size[0] > strip.size[1]
    assert strip.size[0] > 200


def test_ComposeCleanGridBuildsMosaic(service):
    tiles = [
        Image.new("RGB", (80, 80), color=(255, 0, 0)),
        Image.new("RGB", (80, 80), color=(0, 255, 0)),
        Image.new("RGB", (80, 80), color=(0, 0, 255)),
    ]

    grid = service._composeCleanGrid(
        tiles=tiles,
        maxCols=2,
        targetWidth=320,
    )

    assert grid.mode == "RGB"
    assert grid.size[0] > 0
    assert grid.size[1] > 0


def test_ComposeCleanStripBuildsStrip(service):
    panels = [
        Image.new("RGB", (90, 120), color=(255, 0, 0)),
        Image.new("RGB", (90, 120), color=(0, 255, 0)),
    ]

    strip = service._composeCleanStrip(panels=panels, targetHeight=180)

    assert strip.mode == "RGB"
    assert strip.size[0] > strip.size[1]


def test_ComposeParticleMosaicBuildsDenseMontage(
        service,
):
    tiles = [
        Image.new(
            "RGB",
            (
                64,
                64,
            ),
            color=(
                value,
                value,
                value,
            ),
        )
        for value in range(
            20,
            170,
            10,
        )
    ]

    mosaic = (
        service
        ._composeParticleMosaic(
            tiles=tiles,
            targetWidth=128,
            maxCols=5,
        )
    )

    assert mosaic.mode == "RGB"
    assert mosaic.size[0] > mosaic.size[1]
    assert mosaic.size[0] >= 360


def test_VolumeProjectionScorePrefersStructuredSignal(
        service,
):
    empty = np.zeros(
        (
            64,
            64,
        ),
        dtype=np.float32,
    )

    structured = np.zeros(
        (
            64,
            64,
        ),
        dtype=np.float32,
    )

    structured[
        18:46,
        18:46,
    ] = 1.0

    assert (
        service
        ._scoreVolumeProjection(
            structured
        )
        >
        service
        ._scoreVolumeProjection(
            empty
        )
    )


def test_CentralVolumeProjectionSupportsAllAxes(
        service,
):
    volume = np.arange(
        24 * 32 * 40,
        dtype=np.float32,
    ).reshape(
        (
            24,
            32,
            40,
        )
    )

    projectionZ = (
        service
        ._centralVolumeProjection(
            volume,
            axis=0,
        )
    )

    projectionY = (
        service
        ._centralVolumeProjection(
            volume,
            axis=1,
        )
    )

    projectionX = (
        service
        ._centralVolumeProjection(
            volume,
            axis=2,
        )
    )

    assert projectionZ.shape == (
        32,
        40,
    )

    assert projectionY.shape == (
        24,
        40,
    )

    assert projectionX.shape == (
        24,
        32,
    )


def test_RankClasses2dPrefersLargestPopulations(
        service,
):
    class FakeClass2D:
        def __init__(
                self,
                name,
                population,
        ):
            self.name = name
            self.population = population

        def getSize(self):
            return self.population

    small = FakeClass2D(
        "small",
        10,
    )

    large = FakeClass2D(
        "large",
        100,
    )

    medium = FakeClass2D(
        "medium",
        50,
    )

    ranked = service._rankClasses2d(
        [
            small,
            large,
            medium,
        ],
        maxItems=3,
    )

    assert [
        item.name
        for item in ranked
    ] == [
        "large",
        "medium",
        "small",
    ]


def test_RankClasses3dPrefersLargestPopulations(
        service,
):
    class FakeClass3D:
        def __init__(
                self,
                name,
                population,
        ):
            self.name = name
            self.population = population

        def getSize(self):
            return self.population

    small = FakeClass3D(
        "small",
        25,
    )

    large = FakeClass3D(
        "large",
        900,
    )

    medium = FakeClass3D(
        "medium",
        250,
    )

    ranked = service._rankClasses3d(
        [
            small,
            large,
            medium,
        ],
        maxItems=3,
    )

    assert [
        item.name
        for item in ranked
    ] == [
        "large",
        "medium",
        "small",
    ]


def test_ComposeClasses3dPreviewBuildsReadableLayout(
        service,
):
    items = [
        (
            Image.new(
                "RGB",
                (
                    140,
                    140,
                ),
                color=(
                    255,
                    0,
                    0,
                ),
            ),
            "Class 2 · 572",
        ),
        (
            Image.new(
                "RGB",
                (
                    140,
                    140,
                ),
                color=(
                    0,
                    255,
                    0,
                ),
            ),
            "Class 1 · 547",
        ),
    ]

    preview = (
        service
        ._composeClasses3dPreview(
            items=items,
            targetWidth=128,
        )
    )

    assert preview.mode == "RGB"
    assert preview.size[0] > preview.size[1]
    assert preview.size[0] >= 420


def test_PickCoordinates3dSlicePrefersDenseRegion(
        service,
):
    zValues = [
        5,
        6,
        7,
        68,
        69,
        70,
        71,
        72,
        73,
        74,
        75,
    ]

    selected = (
        service
        ._pickCoordinates3dSlice(
            zValues=zValues,
            zSize=100,
        )
    )

    assert 67 <= selected <= 76


def test_ComposeScientificHeroPreviewBuildsThreePanelLayout(
        service,
):
    tiles = [
        Image.new(
            "RGB",
            (
                120,
                120,
            ),
            color=color,
        )
        for color in (
            (
                255,
                0,
                0,
            ),
            (
                0,
                255,
                0,
            ),
            (
                0,
                0,
                255,
            ),
        )
    ]

    preview = (
        service
        ._composeScientificHeroPreview(
            tiles=tiles,
            targetWidth=128,
        )
    )

    assert preview.mode == "RGB"
    assert preview.size[0] > preview.size[1]
    assert preview.size[0] >= 360


def test_SelectRepresentativeTiltFramesUsesZeroAndExtremes(
        service,
):
    frames = [
        (
            -60.0,
            object(),
        ),
        (
            -25.0,
            object(),
        ),
        (
            0.0,
            object(),
        ),
        (
            25.0,
            object(),
        ),
        (
            60.0,
            object(),
        ),
    ]

    selected = (
        service
        ._selectRepresentativeTiltFrames(
            frames
        )
    )

    assert [
        item[0]
        for item in selected
    ] == [
        0.0,
        -60.0,
        60.0,
    ]


def test_ComposeScientificSplitBuildsWidePreview(
        service,
):
    left = Image.new(
        "RGB",
        (
            100,
            100,
        ),
        color=(
            255,
            0,
            0,
        ),
    )

    right = Image.new(
        "RGB",
        (
            220,
            120,
        ),
        color=(
            0,
            255,
            0,
        ),
    )

    preview = (
        service
        ._composeScientificSplitPreview(
            leftImage=left,
            rightImage=right,
            targetWidth=128,
        )
    )

    assert preview.mode == "RGB"
    assert preview.size[0] > preview.size[1]
    assert preview.size[0] >= 360


def test_ComposeTiltSeriesHeroPreviewBuildsHeroLayout(
        service,
):
    tiles = [
        Image.new(
            "RGB",
            (
                120,
                120,
            ),
            color=color,
        )
        for color in (
            (
                255,
                0,
                0,
            ),
            (
                0,
                255,
                0,
            ),
            (
                0,
                0,
                255,
            ),
        )
    ]

    preview = (
        service
        ._composeTiltSeriesHeroPreview(
            tiles=tiles,
            targetWidth=128,
        )
    )

    assert preview.mode == "RGB"
    assert preview.size[0] > preview.size[1]
    assert preview.size[0] >= 360


def test_ComposeTriptychBuildsThreePanelLayout(service):
    panels = [
        Image.new("RGB", (120, 120), color=(255, 0, 0)),
        Image.new("RGB", (120, 120), color=(0, 255, 0)),
        Image.new("RGB", (120, 120), color=(0, 0, 255)),
    ]

    triptych = service._composeTriptych(panels=panels, targetHeight=180)

    assert triptych.mode == "RGB"
    assert triptych.size[0] > triptych.size[1]


def test_ReadCoordinate3dScalarUsesPostgresqlBottomLeftCoordinates(service):
    class FakeCoordinate3D:
        def __init__(self):
            self._postgresqlRuntimeValues = {
                "bottomLeftX": 10.5,
                "bottomLeftY": 20.25,
                "bottomLeftZ": 30.75,
            }

        def getX(self, *_args):
            raise RuntimeError("Native coordinate is not available")

        def getY(self, *_args):
            raise RuntimeError("Native coordinate is not available")

        def getZ(self, *_args):
            raise RuntimeError("Native coordinate is not available")

    coordinate = FakeCoordinate3D()

    assert service._readCoordinate3dScalar(coordinate, "getX") == 10.5
    assert service._readCoordinate3dScalar(coordinate, "getY") == 20.25
    assert service._readCoordinate3dScalar(coordinate, "getZ") == 30.75