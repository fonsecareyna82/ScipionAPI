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
from app.backend.runtime.postgresql_protocol_worker import (
    RuntimePostgresqlProtocolWorker,
)


class ProtocolStub:
    def __init__(
            self,
            streaming=False,
            prerequisites=None,
    ):
        self.streaming = streaming
        self.prerequisites = (
            prerequisites or []
        )

    def worksInStreaming(self):
        return self.streaming

    def getPrerequisites(self):
        return self.prerequisites


def buildWorker(
        streaming,
        parentStatus="running",
        outputExists=True,
        prerequisites=None,
):
    worker = RuntimePostgresqlProtocolWorker(
        projectId=1,
        protocolId=30,
    )

    worker.protocol = ProtocolStub(
        streaming=streaming,
        prerequisites=prerequisites,
    )

    worker.loadParentStatuses = lambda: [
        {
            "protocolDbId": 20,
            "protocolId": 2,
            "status": parentStatus,
        },
    ]

    worker.loadInputRefs = lambda: [
        {
            "inputName": "inputSet",
            "itemIndex": 0,
            "parentProtocolDbId": 20,
            "parentProtocolId": 2,
            "parentOutputName": "outputSet",
        },
    ]

    worker.getRuntimeOutputInfo = (
        lambda inputRef: {
            "exists": outputExists,
            "runtimeObjectId": (
                200
                if outputExists
                else None
            ),
        }
    )

    return worker


def test_NonStreamingProtocolWaitsForRunningParent():
    worker = buildWorker(
        streaming=False,
        parentStatus="running",
        outputExists=True,
    )

    readiness = (
        worker.getReadinessState()
    )

    assert readiness[
        "missingInputs"
    ] == []

    assert readiness[
        "pendingParents"
    ] == [
        {
            "protocolDbId": 20,
            "protocolId": 2,
            "status": "running",
            "reason": (
                "input_parent_not_finished"
            ),
        },
    ]


def test_StreamingProtocolStartsWhenParentOutputExists():
    worker = buildWorker(
        streaming=True,
        parentStatus="running",
        outputExists=True,
    )

    readiness = (
        worker.getReadinessState()
    )

    assert readiness[
        "failedParents"
    ] == []

    assert readiness[
        "pendingParents"
    ] == []

    assert readiness[
        "missingInputs"
    ] == []


def test_StreamingProtocolWaitsUntilParentOutputExists():
    worker = buildWorker(
        streaming=True,
        parentStatus="running",
        outputExists=False,
    )

    readiness = (
        worker.getReadinessState()
    )

    assert readiness[
        "pendingParents"
    ] == []

    assert readiness[
        "missingInputs"
    ] == [
        {
            "inputName": "inputSet",
            "itemIndex": 0,
            "parentProtocolDbId": 20,
            "parentProtocolId": 2,
            "parentOutputName": "outputSet",
            "reason": (
                "parent_output_not_available"
            ),
        },
    ]


def test_StreamingProtocolStillWaitsForExplicitPrerequisite():
    worker = buildWorker(
        streaming=True,
        parentStatus="running",
        outputExists=True,
        prerequisites=[2],
    )

    readiness = (
        worker.getReadinessState()
    )

    assert readiness[
        "pendingParents"
    ] == [
        {
            "protocolDbId": 20,
            "protocolId": 2,
            "status": "running",
            "reason": (
                "prerequisite_not_finished"
            ),
        },
    ]