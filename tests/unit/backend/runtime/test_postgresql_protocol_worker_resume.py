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
import json
import pytest
from types import SimpleNamespace

from pyworkflow.object import (
    Boolean,
    CsvList,
    Set,
)

from pyworkflow.protocol import (
    MODE_RESTART,
    MODE_RESUME,
    STATUS_FINISHED,
    STATUS_SAVED,
)
from pyworkflow.protocol.protocol import (
    FunctionStep,
)

from app.backend.runtime.postgresql_protocol_worker import (
    POSTGRESQL_RUN_MODE_RESTART,
    POSTGRESQL_RUN_MODE_RESUME,
    RuntimePostgresqlProtocolWorker,
    RuntimePostgresqlStepAdapter,
    buildPostgresqlWorkerCommand,
    normalizePostgresqlRunMode,
)


class MapperStub:
    def __init__(
            self,
            snapshots=None,
    ):
        self.snapshots = list(
            snapshots
            or []
        )

        self.listCalls = []

    def listProtocolSteps(
            self,
            projectId,
            protocolId,
    ):
        self.listCalls.append({
            "projectId": projectId,
            "protocolId": protocolId,
        })

        return list(
            self.snapshots
        )


class ProtocolStub:
    def __init__(
            self,
            steps=None,
    ):
        self._steps = list(
            steps
            or []
        )


def buildFunctionStep(
        name,
        *args,
):
    step = FunctionStep(
        lambda: None,
        name,
        *args,
    )

    step.setIndex(1)

    return step


def buildStepAdapter(
        *,
        runMode,
        snapshots=None,
        steps=None,
):
    adapter = object.__new__(
        RuntimePostgresqlStepAdapter
    )

    adapter.mapper = MapperStub(
        snapshots=snapshots
    )

    adapter.projectId = 7
    adapter.protocolId = 10

    adapter.protocol = ProtocolStub(
        steps=steps
    )

    adapter.runMode = (
        normalizePostgresqlRunMode(
            runMode
        )
    )

    return adapter


def test_RestartWorkerCommandRemainsBackwardCompatible():
    command = (
        buildPostgresqlWorkerCommand(
            projectId=7,
            protocolId=10,
        )
    )

    assert "--run-mode" not in command
    assert "--execute" not in command


def test_ResumeWorkerCommandIncludesRunMode():
    command = (
        buildPostgresqlWorkerCommand(
            projectId=7,
            protocolId=10,
            execute=True,
            runMode=(
                POSTGRESQL_RUN_MODE_RESUME
            ),
        )
    )

    assert command[-3:] == [
        "--run-mode",
        "resume",
        "--execute",
    ]


def test_WorkerDefaultsToRestartMode():
    worker = RuntimePostgresqlProtocolWorker(
        projectId=7,
        protocolId=10,
    )

    assert worker.runMode == (
        POSTGRESQL_RUN_MODE_RESTART
    )


def test_WorkerAcceptsResumeMode():
    worker = RuntimePostgresqlProtocolWorker(
        projectId=7,
        protocolId=10,
        runMode=(
            POSTGRESQL_RUN_MODE_RESUME
        ),
    )

    assert worker.runMode == (
        POSTGRESQL_RUN_MODE_RESUME
    )


def test_RestartDoesNotLoadPreviousSteps():
    currentStep = buildFunctionStep(
        "firstStep",
        "new-argument",
    )

    adapter = buildStepAdapter(
        runMode=(
            POSTGRESQL_RUN_MODE_RESTART
        ),
        snapshots=[
            {
                "index": 1,
                "name": "firstStep",
                "status": (
                    STATUS_FINISHED
                ),
                "args": [
                    "old-argument",
                ],
            },
        ],
        steps=[
            currentStep,
        ],
    )

    assert (
        adapter.loadPreviousSteps()
        == []
    )

    assert (
        adapter.mapper.listCalls
        == []
    )


def test_ResumeRestoresPreviousStepSnapshot():
    currentStep = buildFunctionStep(
        "firstStep",
        "argument",
    )

    adapter = buildStepAdapter(
        runMode=(
            POSTGRESQL_RUN_MODE_RESUME
        ),
        snapshots=[
            {
                "index": 1,
                "name": "firstStep",
                "status": (
                    STATUS_SAVED
                ),
                "prerequisites": [],
                "args": [
                    "argument",
                ],
                "initTime": None,
                "endTime": None,
                "error": None,
                "interactive": False,
                "needsGpu": True,
            },
        ],
        steps=[
            currentStep,
        ],
    )

    previousSteps = (
        adapter.loadPreviousSteps()
    )

    assert len(previousSteps) == 1

    previousStep = previousSteps[0]

    assert previousStep is not currentStep
    assert previousStep.getIndex() == 1
    assert previousStep.getStatus() == (
        STATUS_SAVED
    )

    assert previousStep.funcName.get() == (
        "firstStep"
    )

    assert json.loads(
        previousStep.argsStr.get()
    ) == [
        "argument",
    ]

    assert adapter.mapper.listCalls == [
        {
            "projectId": 7,
            "protocolId": 10,
        },
    ]


def test_ResumePreservesStepDifferenceDetection():
    currentStep = buildFunctionStep(
        "firstStep",
        "new-argument",
    )

    adapter = buildStepAdapter(
        runMode=(
            POSTGRESQL_RUN_MODE_RESUME
        ),
        snapshots=[
            {
                "index": 1,
                "name": "firstStep",
                "status": (
                    STATUS_FINISHED
                ),
                "prerequisites": [],
                "args": [
                    "old-argument",
                ],
                "interactive": False,
                "needsGpu": True,
            },
        ],
        steps=[
            currentStep,
        ],
    )

    previousStep = (
        adapter
        .loadPreviousSteps()[0]
    )

    assert previousStep != currentStep


def test_ScipionRunModesRemainDistinct():
    assert MODE_RESTART != MODE_RESUME


class ResumeOutputProtocolStub:
    def __init__(self):
        self._outputs = CsvList()
        self._useOutputList = Boolean(
            False
        )


def test_ResumeRestoresAndReopensOwnOutputs():
    worker = RuntimePostgresqlProtocolWorker(
        projectId=7,
        protocolId=10,
        runMode=(
            POSTGRESQL_RUN_MODE_RESUME
        ),
    )

    protocol = (
        ResumeOutputProtocolStub()
    )

    outputSet = Set()
    outputSet.setObjId(
        500
    )

    objectMapper = SimpleNamespace(
        listProtocolStoredObjects=(
            lambda **kwargs: [
                {
                    "protocolDbId": 110,
                    "scipionObjId": 500,
                    "parentObjectId": None,
                    "name": "outputSet",
                    "path": "outputSet",
                    "className": "Set",
                },
            ]
        )
    )

    runtimeMapper = SimpleNamespace(
        objectMapper=objectMapper,
        selectRuntimeInputObjectById=(
            lambda runtimeObjectId: (
                outputSet
                if runtimeObjectId == 500
                else None
            )
        ),
    )

    worker.protocol = protocol
    worker.runtimeMapper = runtimeMapper
    worker.getProtocolDbId = (
        lambda: 110
    )

    report = (
        worker.restoreResumeOutputs()
    )

    assert report["errors"] == []
    assert report["restored"] == 1
    assert report[
        "parentProtocolsModified"
    ] is False

    assert protocol.outputSet is (
        outputSet
    )

    assert outputSet._objParent is (
        protocol
    )

    assert outputSet.isStreamOpen()
    assert "outputSet" in (
        protocol._outputs
    )

    assert (
        protocol
        ._useOutputList
        .get()
        is True
    )


def test_RestartDoesNotRestorePreviousOutputs():
    worker = RuntimePostgresqlProtocolWorker(
        projectId=7,
        protocolId=10,
        runMode=(
            POSTGRESQL_RUN_MODE_RESTART
        ),
    )

    worker.protocol = (
        ResumeOutputProtocolStub()
    )

    worker.runtimeMapper = SimpleNamespace(
        objectMapper=SimpleNamespace(
            listProtocolStoredObjects=(
                lambda **kwargs: (
                    pytest.fail(
                        "Restart must not load "
                        "previous outputs"
                    )
                )
            )
        )
    )

    report = (
        worker.restoreResumeOutputs()
    )

    assert report == {
        "restored": 0,
        "items": [],
        "errors": [],
        "skipped": True,
        "reason": (
            "protocol_not_resuming"
        ),
        "selfProtocolOnly": True,
        "parentProtocolsModified": False,
    }