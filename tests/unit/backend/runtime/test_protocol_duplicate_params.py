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
from app.backend.runtime.protocol_duplicate_service import (
    RuntimeProtocolDuplicateService,
)


class FakeSourceProtocol:
    def getParam(self, key):
        return None


def test_BuildDuplicatedProtocolParamsDropsObjectMetadata():
    params = {
        "object.id": 41,
        "object.label": "Union sets",
        "object.comment": "Original protocol",
        "object.className": "ProtUnionSet",
        "runName": "Union sets",
        "ignoreDuplicates": True,
    }

    result = RuntimeProtocolDuplicateService().buildDuplicatedProtocolParams(
        sourceProtocol=FakeSourceProtocol(),
        sourceParams=params,
    )

    assert result == {
        "runName": "Union sets copy",
        "ignoreDuplicates": True,
    }