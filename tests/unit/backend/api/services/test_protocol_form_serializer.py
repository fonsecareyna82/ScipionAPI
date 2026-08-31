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
    Float,
    Integer,
    Object,
    Pointer,
    String,
)

from pyworkflow.protocol.params import (
    BooleanParam,
    EnumParam,
    FileParam,
    FloatParam,
    FolderParam,
    Form,
    IntParam,
    PathParam,
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


def test_group_preserves_nested_lines():
    class FakeProtocol:
        def hasAttribute(self, name):
            return hasattr(self, name)

    protocol = FakeProtocol()

    form = Form(protocol)
    form.addSection("Input")

    group = form.addGroup("Alignment")

    line = group.addLine(
        "Frames to ALIGN and SUM",
        help="Frames range to align.",
    )

    line.addParam(
        "alignFrame0",
        IntParam,
        default=1,
        label="from",
    )

    line.addParam(
        "alignFrameN",
        IntParam,
        default=0,
        label="to",
    )

    group.addParam(
        "binFactor",
        FloatParam,
        default=1.0,
        label="Binning factor",
    )

    cropLine = group.addLine(
        "Crop offsets (px)",
        expertLevel=1,
    )

    cropLine.addParam(
        "cropOffsetX",
        IntParam,
        default=0,
        label="X",
        expertLevel=1,
    )

    cropLine.addParam(
        "cropOffsetY",
        IntParam,
        default=0,
        label="Y",
        expertLevel=1,
    )

    protocol._definition = form
    protocol.alignFrame0 = Integer(1)
    protocol.alignFrameN = Integer(64)
    protocol.binFactor = Float(1.0)
    protocol.cropOffsetX = Integer(0)
    protocol.cropOffsetY = Integer(0)

    sections, values = (
        ProtocolFormSerializer()
        .serializeProtocolSections(
            protocol=protocol,
            wizards={},
            mapper=None,
            projectId=1,
            headerParams=[],
            runName="",
            getScipionObjectIdCallback=lambda obj: None,
            resolvePostgresqlProtocolDbIdCallback=lambda **kwargs: None,
            splitPointerValueCallback=lambda value: (None, None),
        )
    )

    inputSection = next(
        section
        for section in sections
        if section["label"] == "Input"
    )

    alignment = inputSection["params"][0]

    assert alignment["paramClass"] == "Group"
    assert alignment["label"] == "Alignment"

    framesLine = alignment["params"][0]

    assert framesLine["paramClass"] == "Line"
    assert framesLine["label"] == "Frames to ALIGN and SUM"
    assert framesLine["help"] == "Frames range to align."
    assert [
        param["name"]
        for param in framesLine["params"]
    ] == [
        "alignFrame0",
        "alignFrameN",
    ]

    assert alignment["params"][1]["name"] == "binFactor"

    cropLine = alignment["params"][2]

    assert cropLine["paramClass"] == "Line"
    assert cropLine["label"] == "Crop offsets (px)"
    assert cropLine["expertLevel"] == 1
    assert [
        param["name"]
        for param in cropLine["params"]
    ] == [
        "cropOffsetX",
        "cropOffsetY",
    ]

    assert values["alignFrame0"] == 1
    assert values["alignFrameN"] == 64
    assert values["cropOffsetX"] == 0
    assert values["cropOffsetY"] == 0


def test_path_param_subclasses_use_path_param_web_semantics():
    serializer = ProtocolFormSerializer()

    for ParamClass in (
            PathParam,
            FileParam,
            FolderParam,
    ):
        param = ParamClass(
            label="Input path",
            default="",
        )

        value = String(
            "/tmp/input.mrc"
        )

        paramDict, paramValue = (
            serializer
            .serializeParam(
                param=param,
                paramName="inputPath",
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

        assert paramDict["paramClass"] == "PathParam"
        assert paramValue == "/tmp/input.mrc"


def test_condition_context_preserves_protocol_constants():
    class FakeProtocol(Object):
        IMPORT_FROM_FILES = 0

    protocol = FakeProtocol()

    form = Form(protocol)
    form.addSection("Import")

    form.addParam(
        "importFrom",
        EnumParam,
        choices=[
            "files",
            "emdb",
        ],
        default=0,
    )

    form.addParam(
        "emdbId",
        IntParam,
        condition=(
            "importFrom "
            "!= IMPORT_FROM_FILES"
        ),
    )

    protocol._definition = form

    param = form.getParam(
        "emdbId"
    )

    paramDict, _ = (
        ProtocolFormSerializer()
        .serializeParam(
            param=param,
            paramName="emdbId",
            wizards={},
            viewerDict=None,
            visualize=0,
            protVar=Integer(1),
            mapper=None,
            projectId=None,
            protocol=protocol,
            getScipionObjectIdCallback=lambda obj: None,
            resolvePostgresqlProtocolDbIdCallback=lambda **kwargs: None,
            splitPointerValueCallback=lambda value: (None, None),
        )
    )

    assert paramDict[
        "conditionContext"
    ] == {
        "IMPORT_FROM_FILES": 0,
    }


