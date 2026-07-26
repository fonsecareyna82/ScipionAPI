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


