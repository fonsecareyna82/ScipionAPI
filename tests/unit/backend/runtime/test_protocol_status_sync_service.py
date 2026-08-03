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
# * All comments concerning this program package may be sent to the
# * e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************
from app.backend.runtime.protocol_status_sync_service import (
    RuntimeProtocolStatusSyncService,
)


class FakeActiveRuntimeProtocol:
    def getPid(self):
        return 4321

    def getJobIds(self):
        return [
            "77",
            "78",
        ]

    def getElapsedTime(self):
        return None


class FakeRuntimeMetadataProtocol(FakeActiveRuntimeProtocol):
    def __init__(self):
        self._cpuTime = 7.5

    def getElapsedTime(self):
        return 18.25


class FakeMapper:
    def __init__(self):
        self.row = {
            "id": 10,
            "status": "running",
            "params": {},
            "relationsSynchronized": False,
        }

    def getProjectProtocolByProtocolId(
            self,
            projectId,
            protocolId,
    ):
        return dict(self.row)

    def updateProtocol(self, values):
        if "status" in values:
            self.row["status"] = values["status"]

        if "params" in values:
            self.row["params"] = values["params"]


def test_PersistProtocolProcessIdentityPreservesRuntimeMetadata():
    mapper = FakeMapper()

    mapper.row["params"] = {
        (
            RuntimeProtocolStatusSyncService
            .RUNTIME_METADATA_KEY
        ): {
            "elapsedTimeSeconds": 18.5,
            "cpuTimeSeconds": 7.0,
            "pid": 1111,
            "jobIds": [
                "old-job",
            ],
        },
    }

    protocol = (
        FakeActiveRuntimeProtocol()
    )

    result = (
        RuntimeProtocolStatusSyncService()
        .persistProtocolProcessIdentity(
            mapper=mapper,
            projectId=1,
            protocolId=10,
            protocol=protocol,
        )
    )

    params = (
        RuntimeProtocolStatusSyncService()
        .normalizeParams(
            mapper.row["params"]
        )
    )

    metadata = params[
        (
            RuntimeProtocolStatusSyncService
            .RUNTIME_METADATA_KEY
        )
    ]

    assert metadata[
        "elapsedTimeSeconds"
    ] == 18.5

    assert metadata[
        "cpuTimeSeconds"
    ] == 7.0

    assert metadata["pid"] == 4321

    assert metadata["jobIds"] == [
        "77",
        "78",
    ]

    assert result == {
        "protocolId": "10",
        "pid": 4321,
        "jobIds": [
            "77",
            "78",
        ],
    }


def test_BuildRuntimeMetadataIncludesTimingAndProcessIdentity():
    metadata = RuntimeProtocolStatusSyncService().buildRuntimeMetadata(FakeRuntimeMetadataProtocol())

    assert metadata == {
        "cpuTimeSeconds": 7.5,
        "elapsedTimeSeconds": 18.25,
        "pid": 4321,
        "jobIds": ["77", "78"],
    }


def test_ResetProtocolRuntimeMetadataClearsExecutionState():
    mapper = FakeMapper()

    mapper.row["params"] = {
        (
            RuntimeProtocolStatusSyncService
            .RUNTIME_METADATA_KEY
        ): {
            "cpuTimeSeconds": 21.0,
            "elapsedTimeSeconds": 92.5,
            "elapsedUpdatedAtEpochSeconds": 12345.0,
            "finalSyncPending": True,
            "pid": 4321,
            "jobIds": [
                "77",
                "78",
            ],
        },
    }

    result = (
        RuntimeProtocolStatusSyncService()
        .resetProtocolRuntimeMetadata(
            mapper=mapper,
            projectId=1,
            protocolId=10,
        )
    )

    params = (
        RuntimeProtocolStatusSyncService()
        .normalizeParams(
            mapper.row["params"]
        )
    )

    metadata = params[
        (
            RuntimeProtocolStatusSyncService
            .RUNTIME_METADATA_KEY
        )
    ]

    assert metadata[
        "cpuTimeSeconds"
    ] == 0.0

    assert metadata[
        "elapsedTimeSeconds"
    ] == 0.0

    assert metadata[
        "pid"
    ] is None

    assert metadata[
        "jobIds"
    ] == []

    assert (
        "elapsedUpdatedAtEpochSeconds"
        not in metadata
    )

    assert (
        "finalSyncPending"
        not in metadata
    )

    assert result == {
        "protocolId": "10",
        "cpuTimeSeconds": 0.0,
        "elapsedTimeSeconds": 0.0,
        "pid": None,
        "jobIds": [],
    }

def test_GetEffectiveElapsedTimeProjectsActiveCheckpoint():
    service = (
        RuntimeProtocolStatusSyncService()
    )

    result = (
        service
        .getEffectiveElapsedTimeSeconds(
            runtimeMetadata={
                "elapsedTimeSeconds": 25.0,
                (
                    service
                    .ELAPSED_UPDATED_AT_KEY
                ): 100.0,
            },
            statusValue="running",
            nowEpochSeconds=115.0,
        )
    )

    assert result == 40.0


def test_GetEffectiveElapsedTimeDoesNotProjectTerminalProtocol():
    service = (
        RuntimeProtocolStatusSyncService()
    )

    result = (
        service
        .getEffectiveElapsedTimeSeconds(
            runtimeMetadata={
                "elapsedTimeSeconds": 25.0,
                (
                    service
                    .ELAPSED_UPDATED_AT_KEY
                ): 100.0,
            },
            statusValue="finished",
            nowEpochSeconds=115.0,
        )
    )

    assert result == 25.0


def test_GetEffectiveElapsedTimeIgnoresFutureCheckpoint():
    service = (
        RuntimeProtocolStatusSyncService()
    )

    result = (
        service
        .getEffectiveElapsedTimeSeconds(
            runtimeMetadata={
                "elapsedTimeSeconds": 25.0,
                (
                    service
                    .ELAPSED_UPDATED_AT_KEY
                ): 120.0,
            },
            statusValue="running",
            nowEpochSeconds=115.0,
        )
    )

    assert result == 25.0


def test_GetEffectiveElapsedTimeUsesStepFallbackWhenMetadataIsZero():
    service = RuntimeProtocolStatusSyncService()

    result = service.getEffectiveElapsedTimeSeconds(
        {
            "elapsedTimeSeconds": 0.0,
            service.ELAPSED_UPDATED_AT_KEY: 100.0,
        },
        "running",
        nowEpochSeconds=100.0,
        fallbackElapsedSeconds=137.0,
    )

    assert result == 137.0


def test_GetEffectiveElapsedTimeKeepsProjectedMetadataWhenGreaterThanSteps():
    service = RuntimeProtocolStatusSyncService()

    result = service.getEffectiveElapsedTimeSeconds(
        {
            "elapsedTimeSeconds": 25.0,
            service.ELAPSED_UPDATED_AT_KEY: 100.0,
        },
        "running",
        nowEpochSeconds=115.0,
        fallbackElapsedSeconds=30.0,
    )

    assert result == 40.0

