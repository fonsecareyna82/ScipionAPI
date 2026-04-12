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

from pathlib import Path

from PIL import Image

from app.backend.api.services.wizard_handlers import executeWizardHandler


class FakeVar:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


class FakeItem:
    def __init__(self, file_path: str, index: int):
        self._file_path = file_path
        self._index = index

    def getLocation(self):
        return self._index, self._file_path


class FakeCollection:
    def __init__(self, items, sampling_rate: float = 1.4):
        self._items = list(items)
        self._sampling_rate = sampling_rate

    def iterItems(self, iterate=False):
        return list(self._items)

    def getSamplingRate(self):
        return self._sampling_rate


class FakePointer:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


class FakeProtocol:
    def __init__(self, image_path: str):
        self.radius = FakeVar(1)
        self.inputParticles = FakePointer(
            FakeCollection(
                items=[
                    FakeItem(image_path, 1),
                    FakeItem(image_path, 2),
                ],
                sampling_rate=1.4,
            )
        )


class ScalarRadiusWizard:
    def getRadius(self, protocol, param_name):
        return 42


class ParamUpdatesRadiusWizard:
    def getRadius(self, protocol, param_name):
        return {
            "paramUpdates": {
                param_name: 33,
                "otherParam": "abc",
            }
        }


def _create_test_image(path: Path, size: int = 64) -> None:
    image = Image.new("L", (size, size))
    pixels = image.load()

    for y in range(size):
        for x in range(size):
            pixels[x, y] = int((x + y) / max(1, (size * 2 - 2)) * 255)

    image.save(path, format="PNG")


def test_execute_wizard_handler_normalizes_scalar_compute_result():
    result = executeWizardHandler(
        kind="compute",
        wizardClass=ScalarRadiusWizard,
        protocol=object(),
        paramName="radius",
        descriptor={},
        wizardInputs={},
        currentProject=None,
        projectId=None,
    )

    assert result["paramUpdates"] == {"radius": 42}


def test_execute_wizard_handler_preserves_param_updates_dict():
    result = executeWizardHandler(
        kind="compute",
        wizardClass=ParamUpdatesRadiusWizard,
        protocol=object(),
        paramName="radius",
        descriptor={},
        wizardInputs={},
        currentProject=None,
        projectId=None,
    )

    assert result["paramUpdates"] == {
        "radius": 33,
        "otherParam": "abc",
    }


def test_mask_radius_wizard_open_returns_interactive_viewer_state(tmp_path):
    image_path = tmp_path / "particles.png"
    _create_test_image(image_path, size=64)

    protocol = FakeProtocol(str(image_path))

    result = executeWizardHandler(
        kind="mask_radius",
        wizardClass=object,
        protocol=protocol,
        paramName="radius",
        descriptor={},
        wizardInputs={},
        currentProject=None,
        projectId=None,
    )

    assert result["paramUpdates"] == {}
    assert result["requiresUserInput"] is True
    assert result["availableValues"] == []

    input_schema = result["inputSchema"]
    assert input_schema["type"] == "mask_radius"
    assert input_schema["paramName"] == "radius"

    viewer_state = result["viewerState"]
    assert viewer_state["radius"] == 1
    assert viewer_state["radiusMin"] == 1
    assert viewer_state["radiusMax"] == 32
    assert viewer_state["radiusStep"] == 1
    assert viewer_state["selectedIndex"] == 1
    assert viewer_state["samplingRate"] == 1.4
    assert viewer_state["radiusAngstrom"] == 1.4

    items = viewer_state["items"]
    assert len(items) == 2
    assert items[0]["index"] == 1
    assert items[0]["label"].startswith("001@")

    preview = viewer_state["preview"]
    assert preview["width"] == 512
    assert preview["height"] == 512
    assert preview["sourceWidth"] == 64
    assert preview["sourceHeight"] == 64
    assert preview["caption"] == "Central slice"
    assert preview["imageUrl"].startswith("data:image/png;base64,")


def test_mask_radius_wizard_apply_returns_param_update(tmp_path):
    image_path = tmp_path / "particles.png"
    _create_test_image(image_path, size=64)

    protocol = FakeProtocol(str(image_path))

    result = executeWizardHandler(
        kind="mask_radius",
        wizardClass=object,
        protocol=protocol,
        paramName="radius",
        descriptor={},
        wizardInputs={
            "action": "apply",
            "selectedIndex": 2,
            "radius": 12,
        },
        currentProject=None,
        projectId=None,
    )

    assert result["paramUpdates"] == {"radius": 12}
    assert result["availableValues"] == []
    assert "Mask radius set to 12" in result["message"]