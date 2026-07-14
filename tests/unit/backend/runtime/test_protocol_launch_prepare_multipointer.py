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
from types import SimpleNamespace

import app.backend.runtime.protocol_launch_prepare_service as launchPrepareModule

from pyworkflow.object import Object, PointerList


class FakeValueHolder:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value


class FakeMultiPointerParam:
    def __init__(self):
        self.default = FakeValueHolder()


class FakeProtocol:
    def __init__(self):
        self._objId = 10
        self._params = {
            "inputVolumes": FakeMultiPointerParam(),
        }
        self.inputVolumes = PointerList()

    def getObjId(self):
        return self._objId

    def getParam(self, name):
        return self._params.get(name)


class FakeProtocolIdentityResolver:
    protocolDbIds = {
        10: 100,
        20: 200,
        30: 300,
    }

    def __init__(self, mapper, projectId):
        self.mapper = mapper
        self.projectId = projectId

    def resolveScipionProtocolId(self, protocolId):
        return int(protocolId)

    def resolvePostgresqlProtocolDbId(self, protocolId):
        return self.protocolDbIds.get(int(protocolId))


class FakeProtocolGraphRepository:
    def loadInputRefsForProtocol(
            self,
            mapper,
            projectId,
            protocolDbId,
    ):
        assert projectId == 4
        assert protocolDbId == 100

        return [
            {
                "inputName": "inputVolumes",
                "itemIndex": 0,
                "parentProtocolDbId": 200,
                "parentProtocolId": "20",
                "parentOutputName": "outputVolume",
                "objectClassName": "Volume",
                "objectId": "201",
            },
            {
                "inputName": "inputVolumes",
                "itemIndex": 1,
                "parentProtocolDbId": 300,
                "parentProtocolId": "30",
                "parentOutputName": "outputFilteredVolume",
                "objectClassName": "Volume",
                "objectId": "301",
            },
        ]

    def getPostgresqlRuntimeOutputInfo(
            self,
            mapper,
            projectId,
            parentProtocolDbId,
            outputName,
    ):
        assert projectId == 4

        expectedOutputs = {
            200: "outputVolume",
            300: "outputFilteredVolume",
        }

        assert expectedOutputs[parentProtocolDbId] == outputName

        return {
            "exists": True,
            "kind": "object",
            "setId": None,
            "objectId": parentProtocolDbId + 1,
            "className": "Volume",
            "itemClassName": None,
            "itemsCount": None,
        }


def test_PreparePointerOutputsRestoresMultiPointerWithoutMutatingParents(
        monkeypatch,
):
    monkeypatch.setattr(
        launchPrepareModule,
        "MultiPointerParam",
        FakeMultiPointerParam,
    )

    monkeypatch.setattr(
        launchPrepareModule,
        "ProtocolIdentityResolver",
        FakeProtocolIdentityResolver,
    )

    monkeypatch.setattr(
        launchPrepareModule,
        "ProtocolGraphRepository",
        FakeProtocolGraphRepository,
    )

    protocol = FakeProtocol()
    previousPointerList = protocol.inputVolumes

    firstParent = Object()
    firstParent.setObjId(20)

    firstOriginalOutput = object()
    firstParent.outputVolume = firstOriginalOutput

    secondParent = Object()
    secondParent.setObjId(30)

    secondOriginalOutput = object()
    secondParent.outputFilteredVolume = secondOriginalOutput

    parents = {
        20: firstParent,
        30: secondParent,
    }

    def getParentProtocolCallback(
            mapper,
            projectId,
            parentId,
    ):
        parentId = int(parentId)
        return parentId, parents[parentId]

    service = launchPrepareModule.RuntimeProtocolLaunchPrepareService()

    report = service.preparePointerOutputsForLaunch(
        mapper=SimpleNamespace(),
        projectId=4,
        protocol=protocol,
        getProtocolIdCallback=lambda item: item.getObjId(),
        getParentProtocolCallback=getParentProtocolCallback,
    )

    assert report["prepared"] == 2
    assert report["errors"] == []
    assert report["parentProtocolsReadOnly"] is True

    assert protocol.inputVolumes is not previousPointerList
    assert isinstance(protocol.inputVolumes, PointerList)
    assert len(protocol.inputVolumes) == 2

    firstPointer = protocol.inputVolumes[0]
    secondPointer = protocol.inputVolumes[1]

    assert firstPointer.getObjValue() is firstParent
    assert firstPointer.getExtended() == "outputVolume"

    assert secondPointer.getObjValue() is secondParent
    assert secondPointer.getExtended() == "outputFilteredVolume"

    assert firstParent.outputVolume is firstOriginalOutput
    assert secondParent.outputFilteredVolume is secondOriginalOutput

    assert [
        item["itemIndex"]
        for item in report["items"]
    ] == [0, 1]

    assert [
        item["pointerValue"]
        for item in report["items"]
    ] == [
        "20.outputVolume",
        "30.outputFilteredVolume",
    ]

    assert all(
        item["multiPointer"] is True
        for item in report["items"]
    )

    assert all(
        item["pointerResolutionSkipped"]
        == "parent_protocol_and_outputs_are_read_only"
        for item in report["items"]
    )

    assert protocol.getParam("inputVolumes").default.value is None