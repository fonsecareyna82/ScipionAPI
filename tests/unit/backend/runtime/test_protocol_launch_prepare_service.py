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
from pyworkflow.object import Object, Pointer
from pyworkflow.protocol.protocol import Protocol

import app.backend.runtime.protocol_launch_prepare_service as serviceModule

from app.backend.runtime.protocol_launch_prepare_service import (
    RuntimeProtocolLaunchPrepareService,
)


class ExampleProtocol(Protocol):
    def _defineParams(self, form):
        pass


class ChildProtocol(ExampleProtocol):
    def __init__(self):
        super().__init__()

        self.paramsByName = {
            "inputTiltSeries": object(),
            "inputCtf": object(),
        }

    def getParam(self, name):
        return self.paramsByName.get(name)


class FakeProtocolIdentityResolver:
    def __init__(self, mapper, projectId):
        self.mapper = mapper
        self.projectId = projectId

    def resolveScipionProtocolId(self, protocolId):
        return int(protocolId)

    def resolvePostgresqlProtocolDbId(self, protocolId):
        protocolId = int(protocolId)

        if protocolId == 6:
            return 106

        if protocolId == 5:
            return 105

        return None


class FakeProtocolGraphRepository:
    def loadInputRefsForProtocol(
            self,
            mapper,
            projectId,
            protocolDbId,
    ):
        assert projectId == 1
        assert protocolDbId == 106

        return [
            {
                "inputName": "inputTiltSeries",
                "itemIndex": 0,
                "parentProtocolDbId": 105,
                "parentProtocolId": "5",
                "parentOutputName": "outputTiltSeries",
            },
            {
                "inputName": "inputCtf",
                "itemIndex": 0,
                "parentProtocolDbId": 105,
                "parentProtocolId": "5",
                "parentOutputName": "outputCtf",
            },
        ]

    def getPostgresqlRuntimeOutputInfo(
            self,
            mapper,
            projectId,
            parentProtocolDbId,
            outputName,
    ):
        assert projectId == 1
        assert parentProtocolDbId == 105

        return {
            "exists": True,
            "kind": "set",
            "setId": 20 if outputName == "outputTiltSeries" else 21,
            "objectId": 30 if outputName == "outputTiltSeries" else 31,
            "runtimeObjectId": 40 if outputName == "outputTiltSeries" else 41,
            "outputName": outputName,
            "className": "ExampleSet",
            "itemClassName": "ExampleItem",
            "itemsCount": 2,
        }


def test_PreparePointersReusesOneParentProtocolInstance(
        monkeypatch,
):
    monkeypatch.setattr(
        serviceModule,
        "ProtocolIdentityResolver",
        FakeProtocolIdentityResolver,
    )

    monkeypatch.setattr(
        serviceModule,
        "ProtocolGraphRepository",
        FakeProtocolGraphRepository,
    )

    childProtocol = ChildProtocol()
    childProtocol.setObjId(6)

    loadedParents = []

    def getParentProtocol(
            mapper,
            projectId,
            parentId,
    ):
        assert projectId == 1
        assert int(parentId) == 5

        parentProtocol = ExampleProtocol()
        parentProtocol.setObjId(5)

        parentProtocol.outputTiltSeries = Object()
        parentProtocol.outputCtf = Object()

        loadedParents.append(parentProtocol)

        return 5, parentProtocol

    report = RuntimeProtocolLaunchPrepareService().preparePointerOutputsForLaunch(
        mapper=object(),
        projectId=1,
        protocol=childProtocol,
        getProtocolIdCallback=lambda protocol: protocol.getObjId(),
        getParentProtocolCallback=getParentProtocol,
    )

    assert report["errors"] == []
    assert report["prepared"] == 2

    assert len(loadedParents) == 1

    assert isinstance(childProtocol.inputTiltSeries, Pointer)
    assert isinstance(childProtocol.inputCtf, Pointer)

    tiltSeriesParent = childProtocol.inputTiltSeries.getObjValue()
    ctfParent = childProtocol.inputCtf.getObjValue()

    assert tiltSeriesParent is loadedParents[0]
    assert ctfParent is loadedParents[0]
    assert tiltSeriesParent is ctfParent

    assert childProtocol.inputTiltSeries.getExtended() == "outputTiltSeries"
    assert childProtocol.inputCtf.getExtended() == "outputCtf"

    assert childProtocol.inputTiltSeries.get() is tiltSeriesParent.outputTiltSeries
    assert childProtocol.inputCtf.get() is ctfParent.outputCtf