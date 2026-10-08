"""Regressions for conditional Scipion protocol parameters.

The definitions mirror XmippProtCreateMask3D, but tests exercise the shared
ScipionAPI save/validation layer without requiring Xmipp to be installed.
"""

import pytest

from pyworkflow.protocol.params import EnumParam, FloatParam, IntParam, Form

from app.backend.runtime.protocol_save_service import RuntimeProtocolSaveService


class ConditionalMaskProtocol:
    """Small protocol exposing the same condition API as native Scipion."""

    def __init__(self):
        self.values = {"source": 0, "volumeOperation": 0, "segmentationType": 2}
        self.params = {
            "source": EnumParam(label="Mask source", choices=["Volume", "Geometry", "Feature File"]),
            "volumeOperation": EnumParam(label="Operation", condition="source==0", choices=["Threshold", "Segment", "Only postprocess"]),
            "segmentationType": EnumParam(label="Segmentation type", condition="source==0 and volumeOperation==1", choices=["Number of voxels", "Number of aminoacids", "Dalton mass", "Automatic"]),
            "threshold": FloatParam(label="Threshold", condition="source==0 and volumeOperation==0"),
            "nvoxels": IntParam(label="Number of voxels", condition="source==0 and volumeOperation==1 and segmentationType==0"),
            "naminoacids": IntParam(label="Number of aminoacids", condition="source==0 and volumeOperation==1 and segmentationType==1"),
            "dalton": FloatParam(label="Mass (Da)", condition="source==0 and volumeOperation==1 and segmentationType==2"),
            "size": IntParam(label="Mask size (px)", condition="source==1"),
        }
        # Populate Scipion's actual dependency metadata instead of keeping
        # an incomplete hand-written param dictionary. Patch 56 relies on
        # Form._analizeCondition(), as real Protocol instances already do.
        self.form = Form(self)
        for name, definition in self.params.items():
            self.form.registerParam(name, definition)
        self.evaluated = []

    def hasAttribute(self, name):
        # Form._analizeCondition checks whether expression identifiers are
        # protocol attributes. Here, the values dictionary acts as storage.
        return name in self.values

    def getParam(self, name):
        return self.params.get(name)

    def setAttributeValue(self, name, value):
        self.values[name] = value

    def evalParamCondition(self, name):
        self.evaluated.append(name)
        condition = self.params[name].condition.get()
        if not condition:
            return True
        # Test-only evaluator for trusted, static conditions matching Xmipp.
        return bool(eval(condition, {"__builtins__": {}}, dict(self.values)))


def apply_mask(values):
    protocol = ConditionalMaskProtocol()
    errors = RuntimeProtocolSaveService()._applyScalarParams(
        protocol=protocol, params=values, validateParams=True
    )
    return protocol, errors


def test_volume_threshold_ignores_hidden_empty_segmentation_and_geometry_fields():
    protocol, errors = apply_mask({
        "nvoxels": "", "naminoacids": "", "dalton": "", "size": "",
        "source": 0, "volumeOperation": 0, "threshold": "0.25",
    })
    assert errors == []
    assert protocol.values["threshold"] == 0.25
    assert {"nvoxels", "naminoacids", "dalton", "size"}.issubset(set(protocol.evaluated))


def test_volume_threshold_ignores_invalid_hidden_fields_even_if_sent_first():
    _, errors = apply_mask({
        "nvoxels": "not an integer", "naminoacids": "oops", "dalton": "bad", "size": "bad",
        "source": 0, "volumeOperation": 0, "threshold": 0.5,
    })
    assert errors == []


@pytest.mark.parametrize("segmentation_type,active_label", [
    (0, "Number of voxels"),
    (1, "Number of aminoacids"),
    (2, "Mass (Da)"),
])
def test_segment_validates_only_selected_numeric_parameter_even_when_selectors_are_last(segmentation_type, active_label):
    _, errors = apply_mask({
        "nvoxels": "", "naminoacids": "", "dalton": "", "size": "",
        "segmentationType": segmentation_type, "volumeOperation": 1, "source": 0,
    })
    assert len(errors) == 1, errors
    assert active_label in errors[0]


def test_automatic_segmentation_requires_none_of_the_numeric_fields():
    _, errors = apply_mask({
        "nvoxels": "", "naminoacids": "", "dalton": "", "size": "",
        "segmentationType": 3, "volumeOperation": 1, "source": 0,
    })
    assert errors == []


def test_geometry_validates_size_but_ignores_all_volume_numeric_fields():
    _, errors = apply_mask({
        "nvoxels": "", "naminoacids": "", "dalton": "", "size": "",
        "source": 1, "volumeOperation": 1, "segmentationType": 0,
    })
    assert len(errors) == 1, errors
    assert "Mask size (px)" in errors[0]


def test_geometry_accepts_valid_size_while_ignoring_hidden_volume_fields():
    protocol, errors = apply_mask({
        "nvoxels": "", "naminoacids": "", "dalton": "", "size": "128",
        "source": 1, "volumeOperation": 1, "segmentationType": 2,
    })
    assert errors == []
    assert protocol.values["size"] == 128


def test_volume_only_postprocess_does_not_require_segment_or_threshold_fields():
    _, errors = apply_mask({
        "threshold": "", "nvoxels": "", "naminoacids": "", "dalton": "", "size": "",
        "source": 0, "volumeOperation": 2,
    })
    assert errors == []


def test_mask_fixture_registers_real_scipion_dependencies():
    protocol = ConditionalMaskProtocol()
    assert "source" in protocol.params["size"]._conditionParams
    assert "source" in protocol.params["nvoxels"]._conditionParams
    assert "volumeOperation" in protocol.params["nvoxels"]._conditionParams
    assert "segmentationType" in protocol.params["nvoxels"]._conditionParams
