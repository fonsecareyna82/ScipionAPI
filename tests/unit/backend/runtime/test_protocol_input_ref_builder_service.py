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
from pyworkflow.object import Pointer
from pyworkflow.protocol.protocol import Protocol

from app.backend.runtime.protocol_input_ref_builder_service import (
    RuntimeProtocolInputRefBuilderService,
)


class ParentProtocolStub(Protocol):
    def getObjId(self):
        return 1374


class ChildProtocolStub:
    def __init__(self, pointer):
        self.pointer = pointer

    def getObjId(self):
        return 1451

    def iterInputAttributes(self):
        return [
            (
                "inputProtocol",
                self.pointer,
            ),
        ]


def test_BuildProtocolInputRefsSupportsDirectProtocolPointer():
    parentProtocol = object.__new__(
        ParentProtocolStub
    )

    pointer = Pointer(
        parentProtocol
    )

    childProtocol = ChildProtocolStub(
        pointer
    )

    refs = (
        RuntimeProtocolInputRefBuilderService()
        .buildProtocolInputRefsForPostgresql(
            projectId=394,
            protocol=childProtocol,
            protocolDbIdByScipionId={
                "1374": 31,
                "1451": 41,
            },
            strict=True,
        )
    )

    assert refs == [
        {
            "projectId": 394,
            "protocolDbId": 41,
            "protocolId": "1451",
            "inputName": "inputProtocol",
            "itemIndex": 0,
            "parentProtocolDbId": 31,
            "parentProtocolId": "1374",
            "parentOutputName": None,
            "objectClassName": "ParentProtocolStub",
            "objectId": "1374",
        },
    ]