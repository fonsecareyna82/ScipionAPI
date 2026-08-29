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
from pyworkflow.object import (
    Boolean,
    Integer,
    Object,
    Pointer,
)

from pyworkflow.protocol.params import (
    BooleanParam,
    IntParam,
)

from app.backend.api.services.protocol_form_serializer import (
    ProtocolFormSerializer,
)


def test_scalar_pointer_runtime_value_from_direct_output():
    output = Integer(128)
    output.setObjId(1000005)
    output._objParentId = 421
    output._objName = "boxsize"

    scalar = Integer()
    scalar.setPointer(
        Pointer(output)
    )

    value = (
        ProtocolFormSerializer
        ._getScalarPointerRuntimeValue(
            scalar
        )
    )

    assert value == {
        "parentId": 421,
        "value": "421.boxsize",
    }


def test_scalar_pointer_runtime_value_from_protocol_pointer():
    parent = Object()
    parent.setObjId(421)

    scalar = Integer()
    scalar.setPointer(
        Pointer(
            parent,
            extended="boxsize",
        )
    )

    value = (
        ProtocolFormSerializer
        ._getScalarPointerRuntimeValue(
            scalar
        )
    )

    assert value == {
        "parentId": 421,
        "value": "421.boxsize",
    }


def test_regular_scalar_param_preserves_runtime_value():
    param = IntParam(
        label="Box size",
        default=64,
    )

    value = Integer(256)

    paramDict, paramValue = (
        ProtocolFormSerializer()
        .serializeParam(
            param=param,
            paramName="boxSize",
            wizards={},
            viewerDict=None,
            visualize=0,
            protVar=value,
            mapper=None,
            projectId=None,
            protocol=None,
            getScipionObjectIdCallback=lambda obj: None,
            resolvePostgresqlProtocolDbIdCallback=lambda **kwargs: None,
            splitPointerValueCallback=lambda value: (None, None),
        )
    )

    assert paramDict["paramClass"] == "IntParam"
    assert paramValue == 256


def test_regular_boolean_param_preserves_false_value():
    param = BooleanParam(
        label="Enabled",
        default=True,
    )

    value = Boolean(False)

    _, paramValue = (
        ProtocolFormSerializer()
        .serializeParam(
            param=param,
            paramName="enabled",
            wizards={},
            viewerDict=None,
            visualize=0,
            protVar=value,
            mapper=None,
            projectId=None,
            protocol=None,
            getScipionObjectIdCallback=lambda obj: None,
            resolvePostgresqlProtocolDbIdCallback=lambda **kwargs: None,
            splitPointerValueCallback=lambda value: (None, None),
        )
    )

    assert paramValue is False


