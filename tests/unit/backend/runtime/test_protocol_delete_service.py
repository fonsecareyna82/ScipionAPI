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
from pyworkflow.protocol import (
    STATUS_FINISHED,
    STATUS_RUNNING,
)

import app.backend.runtime.protocol_delete_service as deleteModule
from app.backend.runtime.protocol_delete_service import (
    RuntimeProtocolDeleteService,
)


class FakeProtocol:
    def __init__(
            self,
            protocolId,
            protocolStatus=STATUS_FINISHED,
    ):
        self.protocolId = int(protocolId)
        self.protocolStatus = protocolStatus

    def getObjId(self):
        return self.protocolId

    def getStatus(self):
        return self.protocolStatus


class FakeMapper:
    def __init__(self):
        self.db = object()


class FakeGraphRepository:
    def __init__(
            self,
            *,
            statuses=None,
            externalDescendants=None,
            deleteGraphInfo=None,
    ):
        self.statuses = dict(
            statuses or {}
        )
        self.externalDescendants = list(
            externalDescendants or []
        )
        self.deleteGraphInfo = (
            deleteGraphInfo
            or {
                "deletedProtocolIds": [
                    "10",
                ],
                "deletedProtocolDbIds": [
                    101,
                ],
                "deletedCount": 1,
                "runtimeObjectIds": [
                    9001,
                ],
                "runtimeSetObjectIds": [
                    9001,
                ],
                "relationsDeleted": 2,
                "affectedChildren": [],
                "parentsRefresh": {
                    "refreshed": [],
                    "count": 0,
                },
            }
        )
        self.deleteCalls = []
        self.externalValidationCalls = []

    def getProtocolStatusByScipionProtocolId(
            self,
            *,
            mapper,
            projectId,
            protocolId,
    ):
        return self.statuses.get(
            str(protocolId)
        )

    def loadExternalDescendantsForDeleteValidation(
            self,
            *,
            mapper,
            projectId,
            selectedProtocolDbIds,
    ):
        self.externalValidationCalls.append({
            "mapper": mapper,
            "projectId": int(projectId),
            "selectedProtocolDbIds": list(
                selectedProtocolDbIds
            ),
        })

        return list(
            self.externalDescendants
        )

    def deleteProtocolsAndRefreshChildren(
            self,
            *,
            mapper,
            projectId,
            protocolDbIds,
            blockedStatusTexts,
    ):
        self.deleteCalls.append({
            "mapper": mapper,
            "projectId": int(projectId),
            "protocolDbIds": list(
                protocolDbIds
            ),
            "blockedStatusTexts": set(
                blockedStatusTexts
            ),
        })

        return dict(
            self.deleteGraphInfo
        )


def failCallback(*args, **kwargs):
    raise AssertionError(
        "Unexpected callback"
    )


def test_BuildBlockedProtocolReportsUsesPostgresqlStatus():
    service = RuntimeProtocolDeleteService()
    mapper = FakeMapper()
    protocol = FakeProtocol(
        10,
        STATUS_FINISHED,
    )
    repository = FakeGraphRepository(
        statuses={
            "10": STATUS_RUNNING,
        }
    )

    result = (
        service
        .buildBlockedProtocolReports(
            mapper=mapper,
            projectId=1,
            protocols=[
                protocol,
            ],
            protocolGraphRepository=(
                repository
            ),
        )
    )

    assert result == [
        {
            "protocolId": "10",
            "status": str(
                STATUS_RUNNING
            ).strip().lower(),
        },
    ]


def test_ValidatePostgresqlDeleteReportsActiveAndOutputDescendants():
    service = RuntimeProtocolDeleteService()
    mapper = FakeMapper()
    repository = FakeGraphRepository(
        externalDescendants=[
            {
                "protocolDbId": 201,
                "protocolId": "20",
                "status": STATUS_RUNNING,
                "setsCount": 0,
                "objectsCount": 0,
            },
            {
                "protocolDbId": 202,
                "protocolId": "21",
                "status": "saved",
                "setsCount": 1,
                "objectsCount": 2,
            },
            {
                "protocolDbId": 203,
                "protocolId": "22",
                "status": "saved",
                "setsCount": 0,
                "objectsCount": 0,
            },
        ]
    )

    result = (
        service
        .validatePostgresqlRuntimeProtocolDelete(
            mapper=mapper,
            projectId=1,
            selectedProtocolDbIds=[
                101,
            ],
            protocolGraphRepository=(
                repository
            ),
        )
    )

    assert result["blocked"] is True
    assert result["externalDescendants"] == [
        {
            "protocolDbId": 201,
            "protocolId": "20",
            "status": str(
                STATUS_RUNNING
            ).strip().lower(),
            "setsCount": 0,
            "objectsCount": 0,
            "reasons": [
                "active",
            ],
        },
        {
            "protocolDbId": 202,
            "protocolId": "21",
            "status": "saved",
            "setsCount": 1,
            "objectsCount": 2,
            "reasons": [
                "has_outputs",
            ],
        },
    ]


def test_DeletePostgresqlRuntimeProtocolsPassesBlockedStatusesAndReturnsRealIds():
    service = RuntimeProtocolDeleteService()
    mapper = FakeMapper()
    protocol = FakeProtocol(10)
    repository = FakeGraphRepository(
        deleteGraphInfo={
            "deletedProtocolIds": [
                "10",
            ],
            "deletedProtocolDbIds": [
                101,
            ],
            "deletedCount": 1,
            "runtimeObjectIds": [
                9001,
                9002,
            ],
            "runtimeSetObjectIds": [
                9001,
            ],
            "relationsDeleted": 3,
            "affectedChildren": [
                102,
            ],
            "parentsRefresh": {
                "refreshed": [
                    {
                        "childProtocolDbId": 102,
                        "dependenciesSaved": 1,
                    },
                ],
                "count": 1,
            },
        }
    )

    result = (
        service
        .deletePostgresqlRuntimeProtocols(
            mapper=mapper,
            projectId=1,
            protocols=[
                protocol,
            ],
            protocolDbIds=[
                101,
            ],
            protocolIds=[
                "requested-value-is-not-authoritative",
            ],
            protocolGraphRepository=(
                repository
            ),
        )
    )

    assert result == repository.deleteGraphInfo

    assert repository.deleteCalls == [
        {
            "mapper": mapper,
            "projectId": 1,
            "protocolDbIds": [
                101,
            ],
            "blockedStatusTexts": (
                service
                .getRuntimeBlockedStatusTexts()
            ),
        },
    ]


def test_BuildPostgresqlRuntimeDeleteResultContainsDeleteDataOnly():
    result = (
        RuntimeProtocolDeleteService()
        .buildPostgresqlRuntimeDeleteResult(
            deleteInfo={
                "deletedProtocolIds": [
                    "10",
                    "11",
                ],
                "deletedProtocolDbIds": [
                    101,
                    102,
                ],
                "parentsRefresh": {
                    "refreshed": [
                        {
                            "dependenciesSaved": 2,
                        },
                        {
                            "dependenciesSaved": 1,
                        },
                    ],
                },
            },
            deleteValidationInfo={
                "blocked": False,
                "externalDescendants": [],
            },
        )
    )

    assert result["status"] == 0
    assert result["errors"] == []
    assert result["protocolsCount"] == 2
    assert result["dependenciesCount"] == 3
    assert result["postgresqlRuntimeDelete"] is True
    for legacyField in (
            "postgresqlOnly",
            "usesProjectSqlite",
            "usesRunDb",
            "usesStepsSqlite",
    ):
        assert legacyField not in result


def test_LegacyProtocolDeleteCompatibilityIsRemoved():
    parameters = inspect.signature(
        RuntimeProtocolDeleteService.deleteProtocols
    ).parameters

    assert "usingPostgresqlRuntime" not in parameters
    assert "currentProjectDeleteProtocolCallback" not in parameters
    assert "mapperDeleteProtocolCallback" not in parameters
    assert "syncProjectProtocolsAndDependenciesCallback" not in parameters


