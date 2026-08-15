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
from app.backend.mapper.postgresql_runtime_mapper import (
    PostgresqlRuntimeMapper,
)
from app.backend.runtime.protocol_status_sync_service import (
    RuntimeProtocolStatusSyncService,
)
from pyworkflow.protocol.protocol import Protocol


class FakePid:
    def __init__(self):
        self.value = 0

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class FakeProtocol:
    def __init__(self):
        self._pid = FakePid()
        self._jobId = []

    def getParam(self, key):
        return None

    def setPid(self, pid):
        self._pid.set(
            pid
        )

    def getPid(self):
        return self._pid.get()

    def appendJobId(self, jobId):
        self._jobId.append(
            jobId
        )

    def getJobIds(self):
        return self._jobId


def buildMapper():
    return object.__new__(
        PostgresqlRuntimeMapper
    )


def test_RuntimeProcessMetadataIsHydrated():
    mapper = buildMapper()
    protocol = FakeProtocol()

    mapper._applyStoredProtocolParams(
        protocol,
        {
            (
                RuntimeProtocolStatusSyncService
                .RUNTIME_METADATA_KEY
            ): {
                "pid": 4321,
                "jobIds": [
                    "77",
                    "78",
                ],
            },
        },
    )

    assert protocol.getPid() == 4321

    assert protocol.getJobIds() == [
        "77",
        "78",
    ]

    assert not hasattr(
        protocol,
        RuntimeProtocolStatusSyncService
        .RUNTIME_METADATA_KEY,
    )


def test_EmptyRuntimeIdentityClearsPreviousValues():
    mapper = buildMapper()
    protocol = FakeProtocol()

    protocol.setPid(
        4321
    )

    protocol.appendJobId(
        "77"
    )

    mapper._applyStoredProtocolParams(
        protocol,
        {
            (
                RuntimeProtocolStatusSyncService
                .RUNTIME_METADATA_KEY
            ): {
                "pid": None,
                "jobIds": [],
            },
        },
    )

    assert protocol.getPid() == 0
    assert protocol.getJobIds() == []


class FakeHostConfig:
    def __init__(self):
        self.store = True

    def setStore(
            self,
            value,
    ):
        self.store = bool(
            value
        )


class FakeProject:
    def __init__(self):
        self.hostConfig = FakeHostConfig()
        self.requestedHostNames = []

    def getHostConfig(
            self,
            hostName,
    ):
        self.requestedHostNames.append(
            hostName
        )

        return self.hostConfig


class FakeProtocolWithHost(
        Protocol
):
    def _defineParams(
            self,
            form,
    ):
        pass

    def __init__(self):
        super().__init__()

        self.setObjId(
            48
        )

        self.setHostName(
            "localhost"
        )


def test_RuntimeContextRestoresHostConfig():
    mapper = object.__new__(
        PostgresqlRuntimeMapper
    )

    mapper.projectId = 342
    mapper.project = FakeProject()

    protocol = (
        FakeProtocolWithHost()
    )

    result = (
        mapper._attachRuntimeContext(
            protocol
        )
    )

    assert result is protocol
    assert (
            protocol.getMapper()
            is mapper
    )

    assert (
            protocol.getProject()
            is mapper.project
    )

    assert (
        mapper.project
        .hostConfig
        .store
        is False
    )

    assert (
        protocol.getHostConfig()
        is mapper.project.hostConfig
    )

    assert (
        mapper.project.requestedHostNames
        == [
            "localhost",
        ]
    )


def test_PostgresqlProtocolHostConfigIsRestored():
    mapper = object.__new__(
        PostgresqlRuntimeMapper
    )

    mapper.projectId = 342
    mapper.project = FakeProject()

    protocol = (
        FakeProtocolWithHost()
    )

    attached = (
        mapper
        ._attachProtocolHostConfig(
            protocol
        )
    )

    assert attached is True

    assert (
        protocol.getHostConfig()
        is mapper.project.hostConfig
    )

    assert (
        mapper.project.requestedHostNames
        == [
            "localhost",
        ]
    )


def test_ProtocolContextDoesNotPersistTransientQueueParams():
    mapper = object.__new__(
        PostgresqlRuntimeMapper
    )

    mapper.projectId = 342

    protocol = FakeProtocolWithHost()
    protocol._useQueue.set(1)

    protocol.setQueueParams([
        "gpu",
        {
            "JOB_TIME": "72",
            "JOB_MEMORY": "64000",
        },
    ])

    context = mapper._buildProtocolContext(
        protocol
    )

    values = context["values"]

    assert "_useQueue" in values
    assert "_queueName" not in values
    assert "_queueParams" not in values

    queueName, queueParams = protocol.getQueueParams()

    assert queueName == "gpu"
    assert queueParams == {
        "JOB_TIME": "72",
        "JOB_MEMORY": "64000",
    }


def test_StoredTransientQueueParamsAreNotHydrated():
    mapper = buildMapper()
    protocol = FakeProtocolWithHost()

    protocol.setQueueParams([
        "current",
        {
            "JOB_TIME": "72",
        },
    ])

    mapper._applyStoredProtocolParams(
        protocol,
        {
            "_queueName": "stale",
            "_queueParams": '["stale", {"JOB_TIME": "24"}]',
        },
    )

    queueName, queueParams = protocol.getQueueParams()

    assert queueName == "current"
    assert queueParams == {
        "JOB_TIME": "72",
    }

    assert not hasattr(
        protocol,
        "_queueName",
    )






