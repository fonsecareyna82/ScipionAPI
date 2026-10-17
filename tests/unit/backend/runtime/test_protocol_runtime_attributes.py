"""Attributes created by a running protocol survive storing and reloading it."""
import pyworkflow.object as pwobject
from pyworkflow.protocol import params
from pyworkflow.protocol.protocol import Protocol

from app.backend.mapper.postgresql_runtime_mapper import PostgresqlRuntimeMapper
from app.backend.runtime.protocol_runtime_attributes import (
    RUNTIME_ATTRIBUTES_KEY,
    applyRuntimeAttributes,
    collectRuntimeAttributes,
)


class CryosparcLikeProtocol(Protocol):
    def _defineParams(self, form):
        form.addSection("Input")
        form.addParam("symmetryGroup", params.StringParam, default="C1")


def ranProtocol():
    protocol = CryosparcLikeProtocol()
    protocol.setObjId(106)
    # As cryoSPARC protocols do while running.
    protocol.projectName = pwobject.String("P12")
    protocol.workSpaceName = pwobject.String("W3")
    protocol.currenJob = pwobject.String("J45")
    protocol.iterations = pwobject.Integer(7)
    protocol.converged = pwobject.Boolean(True)
    protocol.summaryVar.set("Initial model with 3 classes")
    protocol.symmetryGroup.set("D2")
    protocol.setStatus("finished")
    return protocol


def test_runtime_scalars_are_collected_but_not_form_params_or_managed_state():
    protocol = ranProtocol()
    stored = collectRuntimeAttributes(protocol, protocol.getDefinitionDict().keys())
    assert stored["projectName"] == {"class": "String", "value": "P12"}
    assert stored["currenJob"] == {"class": "String", "value": "J45"}
    assert stored["iterations"] == {"class": "Integer", "value": 7}
    assert stored["converged"] == {"class": "Boolean", "value": True}
    assert stored["summaryVar"]["value"] == "Initial model with 3 classes"
    for excluded in ("symmetryGroup", "status", "_jobId", "_pid", "workingDir", "runName"):
        assert excluded not in stored


def test_stored_attributes_are_restored_on_a_freshly_built_protocol():
    original = ranProtocol()
    stored = collectRuntimeAttributes(original, original.getDefinitionDict().keys())
    reloaded = CryosparcLikeProtocol()
    applyRuntimeAttributes(reloaded, stored)
    assert reloaded.projectName.get() == "P12"
    assert reloaded.workSpaceName.get() == "W3"
    assert reloaded.currenJob.get() == "J45"
    assert reloaded.iterations.get() == 7
    assert reloaded.converged.get() is True
    assert reloaded.summaryVar.get() == "Initial model with 3 classes"


def test_restoring_never_overrides_params_managed_state_or_other_types():
    reloaded = CryosparcLikeProtocol()
    reloaded.symmetryGroup.set("C1")
    reloaded.iterations = pwobject.Integer(1)
    applyRuntimeAttributes(reloaded, {
        "symmetryGroup": {"class": "String", "value": "D7"},
        "status": {"class": "String", "value": "finished"},
        "iterations": {"class": "String", "value": "many"},
        "unknownClass": {"class": "Pointer", "value": 3},
        "not valid": {"class": "String", "value": "x"},
        "nested": {"class": "String", "value": {"a": 1}},
    })
    assert reloaded.symmetryGroup.get() == "C1"
    assert reloaded.getStatus() != "finished"
    assert reloaded.iterations.get() == 1
    assert not hasattr(reloaded, "unknownClass")
    assert not hasattr(reloaded, "nested")


def test_protocol_context_stores_the_runtime_attributes_with_the_params():
    mapper = object.__new__(PostgresqlRuntimeMapper)
    mapper.projectId = 7
    context = mapper._buildProtocolContext(ranProtocol())
    stored = context["values"][RUNTIME_ATTRIBUTES_KEY]
    assert stored["projectName"]["value"] == "P12"
    assert context["values"]["symmetryGroup"] == "D2"
