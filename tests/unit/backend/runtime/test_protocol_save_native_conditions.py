"""Native Scipion condition contract: backend-independent runtime save.

Uses real ``Protocol`` and ``Form`` from scipion-pyworkflow. No Xmipp plugin
is required; symbolic constants, nesting and dependency metadata come from
Scipion itself, not from a hand-written expression evaluator.
"""

import pytest

from pyworkflow.protocol import Protocol
from pyworkflow.protocol.params import EnumParam, IntParam, FloatParam, PointerParam

from app.backend.runtime.protocol_save_service import RuntimeProtocolSaveService
from app.backend.api.services.protocol_form_serializer import ProtocolFormSerializer
import app.backend.runtime.protocol_save_service as save_module


@pytest.fixture(autouse=True)
def _ensure_scipion_condition_domain(monkeypatch):
    """Scipion's native condition evaluator expects a configured Domain.

    Actual API launches configure it; isolated unit tests need a minimal
    domain so symbolic protocol constants can still be evaluated natively.
    """
    from types import SimpleNamespace
    from pyworkflow import Config

    if Config.getDomain() is None:
        monkeypatch.setattr(
            Config,
            "getDomain",
            lambda: SimpleNamespace(getObjects=lambda: {}),
        )


class ConditionalProtocol(Protocol):
    MODE_VOLUME = 0
    MODE_GEOMETRY = 1
    METHOD_THRESHOLD = 0
    METHOD_SEGMENT = 1

    def _defineParams(self, form):
        form.addSection(label="Generation")
        form.addParam("source", EnumParam, label="Mask source", default=self.MODE_VOLUME,
                      choices=["Volume", "Geometry"])
        form.addParam("method", EnumParam, label="Operation", default=self.METHOD_THRESHOLD,
                      choices=["Threshold", "Segment"],
                      condition="source == MODE_VOLUME")
        form.addParam("threshold", FloatParam, label="Threshold", default=0.5,
                      condition="source == MODE_VOLUME and method == METHOD_THRESHOLD")
        form.addParam("mass", FloatParam, label="Mass (Da)", default=2.5,
                      condition="source == MODE_VOLUME and method == METHOD_SEGMENT")
        form.addParam("size", IntParam, label="Mask size (px)", default=128,
                      condition="source == MODE_GEOMETRY")
        form.addParam("hiddenRetained", IntParam, label="Hidden retained", default=73,
                      condition="source == MODE_GEOMETRY")
        form.addParam("hiddenPointer", PointerParam, pointerClass="Volume", label="Hidden pointer",
                      allowsNull=True, condition="source == MODE_GEOMETRY")
        form.addParam("always", IntParam, label="Always", default=1, condition="True")
        form.addParam("never", IntParam, label="Never", default=29, condition="False")
        group = form.addGroup("Advanced")
        line = group.addLine("Advanced line")
        line.addParam("nested", IntParam, label="Nested", default=5,
                      condition="source == MODE_GEOMETRY")


class BrokenConditionProtocol(Protocol):
    def _defineParams(self, form):
        form.addSection(label="Input")
        form.addParam("value", IntParam, label="Broken condition value", default=1,
                      condition="nonexistent_constant == 1")


def apply_scalar(protocol, payload):
    return RuntimeProtocolSaveService()._applyScalarParams(
        protocol=protocol, params=payload, validateParams=True)


def test_native_serializer_exports_symbolic_condition_context():
    p = ConditionalProtocol()
    c = ProtocolFormSerializer._buildConditionContext(p.getParam("threshold"), p)
    assert c["MODE_VOLUME"] == ConditionalProtocol.MODE_VOLUME
    assert c["METHOD_THRESHOLD"] == ConditionalProtocol.METHOD_THRESHOLD
    assert "source" not in c, "Dynamic fields belong to the frontend form state"


def test_native_scipion_evaluates_symbolic_constants_and_nested_conditions():
    p = ConditionalProtocol()
    assert p.evalParamCondition("threshold") is True
    assert p.evalParamCondition("mass") is False
    assert p.evalParamCondition("nested") is False
    assert p.evalParamCondition("never") is False
    assert p.evalParamCondition("always") is True
    assert "MODE_VOLUME" in p.getParam("threshold")._conditionParams
    assert "source" in p.getParam("threshold")._conditionParams


@pytest.mark.parametrize("ordered_payload", [
    {"mass": "", "size": "not-a-number", "nested": "bad",
     "source": 0, "method": 0, "threshold": "0.5"},
    {"source": 0, "method": 0, "threshold": "0.5",
     "nested": "bad", "size": "not-a-number", "mass": ""},
])
def test_native_conditions_ignore_inactive_errors_regardless_of_request_order(ordered_payload):
    p = ConditionalProtocol()
    assert apply_scalar(p, ordered_payload) == []
    assert p.threshold.get() == pytest.approx(0.5)


def test_native_multilevel_condition_validates_only_active_numeric_field():
    p = ConditionalProtocol()
    errors = apply_scalar(p, {
        "mass": "", "size": "", "threshold": "bad", "method": 1, "source": 0,
    })
    assert len(errors) == 1
    assert "mass" in errors[0].lower() or "float" in errors[0].lower()
    assert "threshold" not in errors[0].lower()


def test_native_hidden_valid_value_survives_form_update():
    p = ConditionalProtocol()
    p.hiddenRetained.set(73)
    assert apply_scalar(p, {"hiddenRetained": "", "source": 0}) == []
    assert p.hiddenRetained.get() == 73, "Hidden values must not be overwritten by empty web fields"


def test_native_false_condition_never_overwrites_previous_value():
    p = ConditionalProtocol()
    assert apply_scalar(p, {"never": "999", "always": "2"}) == []
    assert p.never.get() == 29
    assert p.always.get() == 2


def test_native_hidden_nested_param_is_preserved():
    p = ConditionalProtocol()
    assert apply_scalar(p, {"nested": "", "source": 0}) == []
    assert p.nested.get() == 5


def test_native_active_invalid_numeric_value_is_not_silently_accepted():
    p = ConditionalProtocol()
    errors = apply_scalar(p, {"source": 1, "size": "bad"})
    assert errors
    assert "size" in " ".join(errors).lower()


def test_condition_evaluation_failure_must_report_error_not_accept_value():
    p = BrokenConditionProtocol()
    errors = apply_scalar(p, {"value": "123"})
    assert errors, "An unresolved native condition cannot silently authorize a value"
    assert "condition" in " ".join(errors).lower()


def test_hidden_native_pointer_is_not_resolved_or_rejected(monkeypatch):
    p = ConditionalProtocol()
    assert p.evalParamCondition("hiddenPointer") is False
    calls = []

    class ResolverMustNotRun:
        def completePointerValuesFromInputRefs(self, **kwargs):
            calls.append(kwargs)
            raise AssertionError("Inactive pointers must not be resolved")

    monkeypatch.setattr(save_module, "RuntimePointerResolver", ResolverMustNotRun)
    errors = RuntimeProtocolSaveService().applyPointerParamsToProtocol(
        mapper=object(), projectId=1, protocol=p,
        params={"hiddenPointer": "not.a.real.output"},
        resolvePointerParentProtocolCallback=lambda **kw: None,
        resolveParentOutputCallback=lambda **kw: None,
    )
    assert errors == []
    assert calls == []


class PointerDependentProtocol(Protocol):
    def _defineParams(self, form):
        form.addSection(label="Input")
        form.addParam("enabled", EnumParam, default=0,
                      choices=["No", "Yes"])
        form.addParam("inputObject", PointerParam, pointerClass="Object",
                      condition="enabled == 1", allowsNull=True)
        form.addParam("dependentValue", IntParam, default=17,
                      condition="inputObject is not None")


def test_native_scalar_dependent_on_pointer_is_deferred_until_pointer_phase():
    from pyworkflow.object import Object
    p = PointerDependentProtocol()
    svc = RuntimeProtocolSaveService()
    payload = {"dependentValue": "42", "enabled": 1}
    assert svc._applyScalarParams(
        protocol=p, params=payload, validateParams=True,
        phase="beforePointers",
    ) == []
    assert p.dependentValue.get() == 17
    assert p.enabled.get() == 1
    p.inputObject.set(Object())
    assert svc._applyScalarParams(
        protocol=p, params=payload, validateParams=True,
        phase="afterPointers",
    ) == []
    assert p.dependentValue.get() == 42


def test_native_scalar_dependent_on_empty_pointer_stays_unchanged():
    p = PointerDependentProtocol()
    svc = RuntimeProtocolSaveService()
    payload = {"dependentValue": "42", "enabled": 1}
    assert svc._applyScalarParams(
        protocol=p, params=payload, validateParams=True,
        phase="beforePointers",
    ) == []
    assert svc._applyScalarParams(
        protocol=p, params=payload, validateParams=True,
        phase="afterPointers",
    ) == []
    assert p.dependentValue.get() == 17


def test_native_hidden_scalar_pointer_never_clears_previous_pointer():
    from pyworkflow.object import Object, Pointer
    p = ConditionalProtocol()
    p.hiddenRetained.set(73)
    assert apply_scalar(p, {"source": 0, "hiddenRetained": None}) == []
    assert p.hiddenRetained.get() == 73


def test_native_condition_failure_preserves_previous_value():
    p = BrokenConditionProtocol()
    p.value.set(8)
    errors = apply_scalar(p, {"value": "123"})
    assert errors and "condition" in " ".join(errors).lower()
    assert p.value.get() == 8
