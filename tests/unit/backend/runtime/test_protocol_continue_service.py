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
import inspect
import pytest
from fastapi import HTTPException

from app.backend.runtime.protocol_continue_service import (
    RuntimeProtocolContinueService,
)


class ProtocolStub:
    def __init__(self, protocolId):
        self.protocolId = protocolId

    def getObjId(self):
        return self.protocolId


def buildResult(
        message,
        **kwargs,
):
    return {
        "message": message,
        **kwargs,
    }


def test_PostgresqlContinueValidatesBeforeCleanupAndLaunch():
    restartProtocol = (
        ProtocolStub(10)
    )

    resumeProtocol = (
        ProtocolStub(11)
    )

    operations = []

    plan = {
        "entries": [
            {
                "protocol": (
                    restartProtocol
                ),
                "protocolId": 10,
                "action": "restart",
            },
            {
                "protocol": (
                    resumeProtocol
                ),
                "protocolId": 11,
                "action": "resume",
            },
        ],
        "errors": [],
        "summary": {
            "protocolsCount": 2,
            "actionableCount": 2,
            "restartProtocolIds": [
                "10",
            ],
            "resumeProtocolIds": [
                "11",
            ],
            "skipped": [],
        },
    }

    def buildPlan(**kwargs):
        operations.append(
            "plan"
        )

        return plan

    def deleteOutputs(**kwargs):
        operations.append(
            "cleanup_outputs"
        )

        assert kwargs["protocols"] == [
            restartProtocol,
        ]

        return {
            "errors": [],
        }

    def clearRefs(**kwargs):
        operations.append(
            "cleanup_refs"
        )

        assert kwargs["protocols"] == [
            restartProtocol,
        ]

        return {
            "updated": 1,
        }

    def launch(**kwargs):
        operations.append(
            "launch"
        )

        assert kwargs["plan"] is plan

        return {
            "protocolsCount": 2,
            "errors": [],
        }

    result = (
        RuntimeProtocolContinueService()
        .continueProtocolSubworkflow(
            mapper=SimpleNamespace(),
            projectId=7,
            protocolId=10,
            getPostgresqlRuntimeSubworkflowCallback=(
                lambda **kwargs: {
                    "10": (
                        restartProtocol,
                        0,
                    ),
                    "11": (
                        resumeProtocol,
                        1,
                    ),
                }
            ),
            buildPostgresqlContinuePlanCallback=(
                buildPlan
            ),
            launchPostgresqlContinueSubworkflowCallback=(
                launch
            ),
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback=(
                deleteOutputs
            ),
            clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback=(
                clearRefs
            ),
            buildProtocolMutationResultCallback=(
                buildResult
            ),
        )
    )

    assert operations == [
        "plan",
        "cleanup_outputs",
        "cleanup_refs",
        "launch",
    ]

    assert result[
        "postgresqlRuntimeContinue"
    ] is True
    workerLaunch = result[
        "postgresqlWorkerLaunch"
    ]

    assert workerLaunch[
        "protocolsCount"
    ] == 2

    for legacyField in (
            "usesProjectSqlite",
            "usesRunDb",
            "usesStepsSqlite",
    ):
        assert legacyField not in workerLaunch



def test_InvalidPostgresqlContinuePlanDoesNotCleanup():
    operations = []

    def unexpected(**kwargs):
        operations.append(
            "unexpected"
        )

        raise AssertionError(
            "Destructive callback must not run"
        )

    with pytest.raises(
            HTTPException,
    ) as errorInfo:
        (
            RuntimeProtocolContinueService()
            .continueProtocolSubworkflow(
                mapper=SimpleNamespace(),
                projectId=7,
                protocolId=10,
                getPostgresqlRuntimeSubworkflowCallback=(
                    lambda **kwargs: {
                        "10": (
                            ProtocolStub(10),
                            0,
                        ),
                    }
                ),
                buildPostgresqlContinuePlanCallback=(
                    lambda **kwargs: {
                        "entries": [],
                        "summary": {},
                        "errors": [{
                            "protocolId": "10",
                            "error": (
                                "active_protocol"
                            ),
                        }],
                    }
                ),
                launchPostgresqlContinueSubworkflowCallback=(
                    unexpected
                ),
                deletePersistedProtocolOutputsForRuntimeProtocolsCallback=(
                    unexpected
                ),
                clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback=(
                    unexpected
                ),
                buildProtocolMutationResultCallback=(
                    buildResult
                ),
            )
        )

    assert errorInfo.value.status_code == 422
    assert operations == []


def test_LegacyProtocolContinueCompatibilityIsRemoved():
    parameters = inspect.signature(
        RuntimeProtocolContinueService
        .continueProtocolSubworkflow
    ).parameters

    assert "usingPostgresqlRuntime" not in parameters
    assert "currentProject" not in parameters
    assert "getScipionProtocolForRuntimeCallback" not in parameters
    assert "workflowProtocolMapToProtocolsCallback" not in parameters


