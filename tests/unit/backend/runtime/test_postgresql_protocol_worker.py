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
import threading

from app.backend.runtime.postgresql_protocol_worker import (
    RuntimePostgresqlProtocolWorker, RuntimePostgresqlStepAdapter,
)


class ProtocolStub:
    def __init__(
            self,
            streaming=False,
            prerequisites=None,
    ):
        self.streaming = streaming
        self.prerequisites = (
            []
            if prerequisites is None
            else prerequisites
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
        prerequisiteStatuses=None,
        validationErrors=None,
        inputRestoreErrors=None,
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

    prerequisiteStatuses = (
        prerequisiteStatuses
        or {}
    )

    def loadPrerequisiteStatuses(
            protocolIds,
    ):
        result = {}

        for protocolId in protocolIds:
            if (
                    protocolId
                    not in prerequisiteStatuses
            ):
                continue

            result[protocolId] = {
                "protocolDbId": (
                    100 + protocolId
                ),
                "protocolId": protocolId,
                "status": (
                    prerequisiteStatuses[
                        protocolId
                    ]
                ),
            }

        return result

    worker.loadPrerequisiteStatuses = (
        loadPrerequisiteStatuses
    )

    worker.validateAvailableInputs = (
        lambda: {
            "inputRestoreErrors": list(
                inputRestoreErrors
                or []
            ),
            "validationErrors": list(
                validationErrors
                or []
            ),
        }
    )

    return worker


def test_NonStreamingProtocolWaitsForRunningParent():
    worker = buildWorker(
        streaming=False,
        parentStatus="running",
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
                "input_parent_not_finished"
            ),
        },
    ]


def test_NonStreamingProtocolWaitsForInteractiveParent():
    worker = buildWorker(
        streaming=False,
        parentStatus="interactive",
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
            "status": "interactive",
            "reason": (
                "input_parent_not_finished"
            ),
        },
    ]


def test_NonStreamingProtocolStartsAfterParentFinished():
    worker = buildWorker(
        streaming=False,
        parentStatus="finished",
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

    assert readiness[
        "validationErrors"
    ] == []


def test_StreamingProtocolStartsWhenInputsValidate():
    worker = buildWorker(
        streaming=True,
        parentStatus="running",
        outputExists=True,
        validationErrors=[],
    )

    readiness = (
        worker.getReadinessState()
    )

    assert readiness[
        "pendingParents"
    ] == []

    assert readiness[
        "missingInputs"
    ] == []

    assert readiness[
        "validationErrors"
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


def test_StreamingProtocolWaitsWhileValidationFails():
    worker = buildWorker(
        streaming=True,
        parentStatus="running",
        outputExists=True,
        validationErrors=[
            "Input set does not contain enough items",
        ],
    )

    readiness = (
        worker.getReadinessState()
    )

    assert readiness[
        "pendingParents"
    ] == []

    assert readiness[
        "missingInputs"
    ] == []

    assert readiness[
        "validationErrors"
    ] == [
        "Input set does not contain enough items",
    ]


def test_CommaSeparatedPrerequisitesAreParsed():
    worker = buildWorker(
        streaming=True,
        parentStatus="finished",
        prerequisites="5, 8; 13",
    )

    assert (
        worker
        .getPrerequisiteProtocolIds()
        == {
            5,
            8,
            13,
        }
    )


def test_PrerequisiteIsCheckedWhenNotInputParent():
    worker = buildWorker(
        streaming=True,
        parentStatus="finished",
        outputExists=True,
        prerequisites="9",
        prerequisiteStatuses={
            9: "running",
        },
    )

    readiness = (
        worker.getReadinessState()
    )

    assert readiness[
        "pendingParents"
    ] == [
        {
            "protocolDbId": 109,
            "protocolId": 9,
            "status": "running",
            "reason": (
                "prerequisite_not_terminal"
            ),
        },
    ]


def test_FailedPrerequisiteDoesNotBlockProtocol():
    worker = buildWorker(
        streaming=True,
        parentStatus="finished",
        outputExists=True,
        prerequisites="9",
        prerequisiteStatuses={
            9: "failed",
        },
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
        "missingPrerequisites"
    ] == []


def test_MissingPrerequisiteIsReported():
    worker = buildWorker(
        streaming=True,
        parentStatus="finished",
        outputExists=True,
        prerequisites="9",
        prerequisiteStatuses={},
    )

    readiness = (
        worker.getReadinessState()
    )

    assert readiness[
        "missingPrerequisites"
    ] == [
        {
            "protocolId": 9,
            "reason": (
                "prerequisite_not_found"
            ),
        },
    ]


class DependencyEventListenerStub:
    def __init__(
            self,
            event=None,
    ):
        self.event = event
        self.waitCalls = []

    def wait(
            self,
            timeoutSeconds,
    ):
        self.waitCalls.append(
            timeoutSeconds
        )

        return self.event


def test_WaitForDependencyChangeUsesEventListener():
    worker = RuntimePostgresqlProtocolWorker(
        projectId=1,
        protocolId=30,
    )

    listener = (
        DependencyEventListenerStub(
            event={
                "eventType": (
                    "protocol_changed"
                ),
                "projectId": 1,
                "protocolId": 2,
            }
        )
    )

    worker.dependencyEventListener = (
        listener
    )

    event = worker.waitForDependencyChange(
        90
    )

    assert event == {
        "eventType": (
            "protocol_changed"
        ),
        "projectId": 1,
        "protocolId": 2,
    }

    assert listener.waitCalls == [
        90,
    ]


def test_StreamingProtocolWaitsForScheduledParent():
    worker = buildWorker(
        streaming=True,
        parentStatus="scheduled",
        outputExists=True,
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
            "status": "scheduled",
            "reason": (
                "streaming_input_parent_not_started"
            ),
        },
    ]

    assert readiness[
        "missingInputs"
    ] == []



class ProtocolJobStoreStub:
    def __init__(self):
        self._jobId = []
        self._lock = threading.RLock()
        self.originalStoreCalls = []

    def _store(
            self,
            *objects,
    ):
        self.originalStoreCalls.append(
            objects
        )


def test_StepAdapterPersistsQueueJobIdsInsteadOfChildObject():
    protocol = (
        ProtocolJobStoreStub()
    )

    adapter = object.__new__(
        RuntimePostgresqlStepAdapter
    )

    adapter.protocol = protocol

    persistedJobIds = []

    adapter.persistProtocolProcessIdentity = (
        lambda: persistedJobIds.append(
            list(
                protocol._jobId
            )
        )
    )

    adapter.install()

    protocol._jobId.append(
        "77"
    )

    protocol._store(
        protocol._jobId
    )

    assert persistedJobIds == [
        [
            "77",
        ],
    ]

    assert (
        protocol.originalStoreCalls
        == []
    )

    otherObject = object()

    protocol._store(
        otherObject
    )

    assert (
        protocol.originalStoreCalls
        == [
            (
                otherObject,
            ),
        ]
    )