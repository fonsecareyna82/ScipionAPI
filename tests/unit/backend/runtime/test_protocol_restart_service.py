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
import inspect
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.backend.runtime.protocol_restart_service import (
    RuntimeProtocolRestartService,
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


def test_PostgresqlRestartValidatesBeforeCleanupAndLaunch():
    protocolA = ProtocolStub(10)
    protocolB = ProtocolStub(11)

    workflowProtocolMap = {
        "10": (
            protocolA,
            0,
        ),
        "11": (
            protocolB,
            1,
        ),
    }

    workflowProtocols = [
        protocolA,
        protocolB,
    ]

    operations = []

    def getSubworkflow(**kwargs):
        operations.append(
            "resolve"
        )

        assert kwargs["projectId"] == 7
        assert kwargs["protocolId"] == 10

        return workflowProtocolMap

    def mapProtocols(protocolMap):
        operations.append(
            "map"
        )

        assert protocolMap is workflowProtocolMap

        return workflowProtocols

    def validate(**kwargs):
        operations.append(
            "validate"
        )

        assert kwargs["workflowProtocolMap"] is workflowProtocolMap

        return {
            "errors": [],
            "validatedProtocolsCount": 2,
        }

    def deleteOutputs(**kwargs):
        operations.append(
            "cleanup_outputs"
        )

        assert kwargs["protocols"] is workflowProtocols

        return {
            "deletedOutputs": 2,
            "errors": [],
        }

    def clearRefs(**kwargs):
        operations.append(
            "cleanup_refs"
        )

        assert kwargs["protocols"] is workflowProtocols

        return {
            "updated": 1,
        }

    def launch(**kwargs):
        operations.append(
            "launch"
        )

        assert kwargs["workflowProtocolMap"] is workflowProtocolMap

        return {
            "protocolsCount": 2,
            "errors": [],
        }

    result = RuntimeProtocolRestartService().restartProtocolSubworkflow(
        mapper=SimpleNamespace(),
        projectId=7,
        protocolId=10,
        getPostgresqlRuntimeSubworkflowCallback=getSubworkflow,
        workflowProtocolMapToProtocolsCallback=mapProtocols,
        deletePersistedProtocolOutputsForRuntimeProtocolsCallback=deleteOutputs,
        clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback=clearRefs,
        validatePostgresqlRestartSubworkflowCallback=validate,
        launchPostgresqlRestartSubworkflowCallback=launch,
        buildProtocolMutationResultCallback=buildResult,
    )

    assert operations == [
        "resolve",
        "map",
        "validate",
        "cleanup_outputs",
        "cleanup_refs",
        "launch",
    ]

    assert result["protocolsCount"] == 2
    assert result["postgresqlRuntimeRestart"] is True
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


def test_InvalidPostgresqlRestartDoesNotCleanupOrLaunch():
    protocol = ProtocolStub(10)

    workflowProtocolMap = {
        "10": (
            protocol,
            0,
        ),
    }

    operations = []

    def getSubworkflow(**kwargs):
        operations.append(
            "resolve"
        )
        return workflowProtocolMap

    def mapProtocols(protocolMap):
        operations.append(
            "map"
        )
        return [
            protocol,
        ]

    def validate(**kwargs):
        operations.append(
            "validate"
        )

        return {
            "errors": [
                {
                    "protocolId": "10",
                    "error": "active_protocol",
                },
            ],
        }

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
        RuntimeProtocolRestartService().restartProtocolSubworkflow(
            mapper=SimpleNamespace(),
            projectId=7,
            protocolId=10,
            getPostgresqlRuntimeSubworkflowCallback=getSubworkflow,
            workflowProtocolMapToProtocolsCallback=mapProtocols,
            deletePersistedProtocolOutputsForRuntimeProtocolsCallback=unexpected,
            clearPostgresqlChildInputRefObjectIdsForOutputProtocolsCallback=unexpected,
            validatePostgresqlRestartSubworkflowCallback=validate,
            launchPostgresqlRestartSubworkflowCallback=unexpected,
            buildProtocolMutationResultCallback=buildResult,
        )

    assert errorInfo.value.status_code == 422

    assert operations == [
        "resolve",
        "map",
        "validate",
    ]


def test_LegacyProtocolRestartCompatibilityIsRemoved():
    parameters = inspect.signature(
        RuntimeProtocolRestartService.restartProtocolSubworkflow
    ).parameters

    assert "usingPostgresqlRuntime" not in parameters
    assert "currentProject" not in parameters
    assert "getScipionProtocolForRuntimeCallback" not in parameters