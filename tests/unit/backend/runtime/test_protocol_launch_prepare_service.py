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
import pytest

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

    def resolvePostgresqlProtocolDbIdFromScipionProtocolId(self, protocolId):
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


def test_PreparePointersUsesDirectOutputsWithoutModifyingParent(
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
    childProtocol.setObjId(
        6
    )

    parentProtocol = (
        ExampleProtocol()
    )
    parentProtocol.setObjId(
        5
    )

    # Deliberately do not attach outputs to the parent.
    parentStateBefore = dict(
        parentProtocol.__dict__
    )

    tiltSeries = Object()
    tiltSeries.setObjId(
        40
    )

    ctf = Object()
    ctf.setObjId(
        41
    )

    runtimeOutputs = {
        40: tiltSeries,
        41: ctf,
    }

    parentLoadCalls = []

    def getParentProtocol(
            mapper,
            projectId,
            parentId,
    ):
        parentLoadCalls.append(
            int(parentId)
        )

        return 5, parentProtocol

    resolvedRuntimeIds = []

    def resolveRuntimeInputObject(
            runtimeObjectId,
    ):
        runtimeObjectId = int(
            runtimeObjectId
        )

        resolvedRuntimeIds.append(
            runtimeObjectId
        )

        return runtimeOutputs.get(
            runtimeObjectId
        )

    report = (
        RuntimeProtocolLaunchPrepareService()
        .preparePointerOutputsForLaunch(
            mapper=object(),
            projectId=1,
            protocol=childProtocol,
            getProtocolIdCallback=(
                lambda protocol:
                protocol.getObjId()
            ),
            getParentProtocolCallback=(
                getParentProtocol
            ),
            resolveRuntimeInputObjectCallback=(
                resolveRuntimeInputObject
            ),
        )
    )

    assert report["errors"] == []
    assert report["prepared"] == 2
    assert report[
        "parentProtocolsReadOnly"
    ] is True

    # Existing outputs do not require loading or modifying the parent.
    assert parentLoadCalls == []
    assert parentProtocol.__dict__ == (
        parentStateBefore
    )

    assert resolvedRuntimeIds == [
        40,
        41,
    ]

    assert isinstance(
        childProtocol.inputTiltSeries,
        Pointer,
    )

    assert isinstance(
        childProtocol.inputCtf,
        Pointer,
    )

    assert (
        childProtocol
        .inputTiltSeries
        .getObjValue()
        is tiltSeries
    )

    assert (
        childProtocol
        .inputTiltSeries
        .get()
        is tiltSeries
    )

    assert (
        childProtocol
        .inputCtf
        .getObjValue()
        is ctf
    )

    assert (
        childProtocol
        .inputCtf
        .get()
        is ctf
    )

    assert all(
        item[
            "directOutputPointer"
        ]
        for item in report[
            "items"
        ]
    )


def test_PreparePointersUsesStrictChildScipionProtocolIdentity():
    class MapperStub:
        def __init__(self):
            self.scipionLookups = []
            self.dbLookups = []

        def getProjectProtocolByProtocolId(self, projectId, protocolId):
            self.scipionLookups.append({
                "projectId": projectId,
                "protocolId": protocolId,
            })
            return None

        def getProjectProtocolByDbId(self, projectId, protocolDbId):
            self.dbLookups.append({
                "projectId": projectId,
                "protocolDbId": protocolDbId,
            })

            return {
                "id": 31,
                "protocolId": "99",
            }

    mapper = MapperStub()

    childProtocol = ChildProtocol()
    childProtocol.setObjId(31)

    report = RuntimeProtocolLaunchPrepareService().preparePointerOutputsForLaunch(
        mapper=mapper,
        projectId=7,
        protocol=childProtocol,
        getProtocolIdCallback=lambda protocol: protocol.getObjId(),
        getParentProtocolCallback=lambda **kwargs: None,
        resolveRuntimeInputObjectCallback=lambda runtimeObjectId: None,
    )

    assert report["protocolId"] == "31"
    assert report["protocolDbId"] is None
    assert report["prepared"] == 0
    assert report["skipped"] is True
    assert report["reason"] == "protocol_not_found_in_postgresql"

    assert mapper.scipionLookups == [
        {
            "projectId": 7,
            "protocolId": "31",
        },
    ]
    assert mapper.dbLookups == []


def test_PreparePointersUsesStrictParentScipionProtocolIdentity(monkeypatch):
    class MapperStub:
        def __init__(self):
            self.scipionLookups = []
            self.dbLookups = []

        def getProjectProtocolByProtocolId(self, projectId, protocolId):
            self.scipionLookups.append({
                "projectId": projectId,
                "protocolId": protocolId,
            })

            if str(protocolId) == "6":
                return {
                    "id": 106,
                    "protocolId": "6",
                }

            return None

        def getProjectProtocolByDbId(self, projectId, protocolDbId):
            self.dbLookups.append({
                "projectId": projectId,
                "protocolDbId": protocolDbId,
            })

            if int(protocolDbId) == 31:
                return {
                    "id": 31,
                    "protocolId": "99",
                }

            return None

    class ProtocolGraphRepositoryStub:
        def loadInputRefsForProtocol(
                self,
                mapper,
                projectId,
                protocolDbId,
        ):
            assert projectId == 7
            assert protocolDbId == 106

            return [
                {
                    "inputName": "inputTiltSeries",
                    "itemIndex": 0,
                    "parentProtocolDbId": None,
                    "parentProtocolId": "31",
                    "parentOutputName": "outputTiltSeries",
                },
            ]

        def getPostgresqlRuntimeOutputInfo(self, **kwargs):
            raise AssertionError(
                "Parent output lookup must not happen when the strict parent protocol lookup fails"
            )

    monkeypatch.setattr(
        serviceModule,
        "ProtocolGraphRepository",
        ProtocolGraphRepositoryStub,
    )

    mapper = MapperStub()

    childProtocol = ChildProtocol()
    childProtocol.setObjId(6)

    report = RuntimeProtocolLaunchPrepareService().preparePointerOutputsForLaunch(
        mapper=mapper,
        projectId=7,
        protocol=childProtocol,
        getProtocolIdCallback=lambda protocol: protocol.getObjId(),
        getParentProtocolCallback=lambda **kwargs: (
            pytest.fail("Parent protocol callback must not be called")
        ),
        resolveRuntimeInputObjectCallback=lambda runtimeObjectId: None,
    )

    assert report["prepared"] == 0
    assert len(report["errors"]) == 1
    assert report["errors"][0]["parentProtocolId"] == "31"
    assert report["errors"][0]["error"] == "Parent protocol 31 was not found in PostgreSQL"

    assert mapper.scipionLookups == [
        {
            "projectId": 7,
            "protocolId": "6",
        },
        {
            "projectId": 7,
            "protocolId": "31",
        },
    ]
    assert mapper.dbLookups == []


class SamplingOutput(Object):
    def __init__(
            self,
            samplingRate,
    ):
        super().__init__()

        self.samplingRate = float(
            samplingRate
        )

    def getSamplingRate(self):
        return self.samplingRate


def test_PreparedPointerCanBeUsedDuringProtocolValidation(
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
    childProtocol.setObjId(
        6
    )

    outputMovies = SamplingOutput(
        1.35
    )
    outputMovies.setObjId(
        40
    )

    RuntimeProtocolLaunchPrepareService().preparePointerOutputsForLaunch(
        mapper=object(),
        projectId=1,
        protocol=childProtocol,
        getProtocolIdCallback=(
            lambda protocol:
            protocol.getObjId()
        ),
        getParentProtocolCallback=(
            lambda **kwargs: (
                5,
                ExampleProtocol(),
            )
        ),
        resolveRuntimeInputObjectCallback=(
            lambda runtimeObjectId:
            outputMovies
            if int(runtimeObjectId) == 40
            else Object()
        ),
    )

    movieSampling = (
        childProtocol
        .inputTiltSeries
        .get()
        .getSamplingRate()
    )

    assert movieSampling == 1.35
