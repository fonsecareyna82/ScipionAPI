"""What a launch says when the validation of a protocol breaks."""
import pytest
from fastapi import HTTPException

from app.backend.runtime.protocol_launch_service import RuntimeProtocolLaunchService


class BrokenValidation:
    def _validate(self):
        inputs = object()
        return inputs.areRe5Particles()


def _errors(previous):
    service = RuntimeProtocolLaunchService.__new__(RuntimeProtocolLaunchService)
    with pytest.raises(HTTPException) as raised:
        service._validateProtocol(protocol=BrokenValidation(), errors=list(previous))
    return raised.value.detail


def test_a_broken_validation_with_nothing_else_to_correct_says_what_broke():
    errors = _errors([])

    assert len(errors) == 1
    assert "AttributeError" in errors[0] and "areRe5Particles" in errors[0]
    assert "test_protocol_launch_validation.py, line" in errors[0]
    assert "Other errors" not in errors[0]


def test_a_broken_validation_after_other_errors_points_to_them():
    errors = _errors(["Input particles is required"])

    assert errors[0] == "Input particles is required"
    assert errors[1].startswith("**Other errors:**")
