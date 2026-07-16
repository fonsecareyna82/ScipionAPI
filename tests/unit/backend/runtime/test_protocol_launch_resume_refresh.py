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

import app.backend.runtime.protocol_launch_service as launchModule

from app.backend.runtime.protocol_launch_service import (
    RuntimeProtocolLaunchService,
)


class FakeProtocol:
    def useQueue(self):
        return False

    def getObjId(self):
        return 10


class FakeStatusSyncService:
    def getStoredElapsedTimeSeconds(
            self,
            **kwargs,
    ):
        return 0.0


def test_LaunchRefreshesRuntimeProtocolBeforeApplyingParams(
        monkeypatch,
):
    operations = []

    monkeypatch.setattr(
        launchModule,
        "RuntimeProtocolStatusSyncService",
        FakeStatusSyncService,
    )

    service = RuntimeProtocolLaunchService()

    service._validateProtocol = lambda **kwargs: None
    service._syncBeforeLaunchIfNeeded = (
        lambda **kwargs: None
    )

    service._executeProtocol = (
        lambda **kwargs: {
            "launched": True,
        }
    )

    def refreshProtocol(**kwargs):
        operations.append(
            "refresh"
        )

        return {
            "refreshed": True,
        }

    def saveProtocol(*args, **kwargs):
        operations.append(
            "save"
        )

        return (
            FakeProtocol(),
            [],
        )

    result = service.launchProtocol(
        mapper=SimpleNamespace(),
        projectId=7,
        protocolId=10,
        protocolClassName="FakeProtocol",
        params={},
        executeMode="launch",
        currentProject=SimpleNamespace(),
        saveProtocolCallback=saveProtocol,
        stopProtocolCallback=lambda *args, **kwargs: None,
        usesPostgresqlRuntimeCallback=lambda: True,
        preparePostgresqlRuntimePointerOutputsForLaunchCallback=(
            lambda **kwargs: {
                "errors": [],
                "skipped": False,
            }
        ),
        syncProjectProtocolsAndDependenciesCallback=(
            lambda *args, **kwargs: {}
        ),
        deletePersistedProtocolOutputsForRuntimeProtocolsCallback=(
            lambda **kwargs: {}
        ),
        syncPostgresqlRuntimeProtocolCallback=(
            lambda **kwargs: {}
        ),
        refreshPostgresqlRuntimeProtocolForResumeCallback=(
            refreshProtocol
        ),
    )

    assert result == {
        "launched": True,
    }

    assert operations == [
        "refresh",
        "save",
    ]


def test_RestartDoesNotRefreshRuntimeProtocol(
        monkeypatch,
):
    operations = []

    monkeypatch.setattr(
        launchModule,
        "RuntimeProtocolStatusSyncService",
        FakeStatusSyncService,
    )

    service = RuntimeProtocolLaunchService()

    service._validateProtocol = lambda **kwargs: None
    service._syncBeforeLaunchIfNeeded = (
        lambda **kwargs: None
    )

    service._executeProtocol = (
        lambda **kwargs: {
            "launched": True,
        }
    )

    service.launchProtocol(
        mapper=SimpleNamespace(),
        projectId=7,
        protocolId=10,
        protocolClassName="FakeProtocol",
        params={},
        executeMode="restart",
        currentProject=SimpleNamespace(),
        saveProtocolCallback=(
            lambda *args, **kwargs: (
                FakeProtocol(),
                [],
            )
        ),
        stopProtocolCallback=lambda *args, **kwargs: None,
        usesPostgresqlRuntimeCallback=lambda: True,
        preparePostgresqlRuntimePointerOutputsForLaunchCallback=(
            lambda **kwargs: {
                "errors": [],
                "skipped": False,
            }
        ),
        syncProjectProtocolsAndDependenciesCallback=(
            lambda *args, **kwargs: {}
        ),
        deletePersistedProtocolOutputsForRuntimeProtocolsCallback=(
            lambda **kwargs: {}
        ),
        syncPostgresqlRuntimeProtocolCallback=(
            lambda **kwargs: {}
        ),
        refreshPostgresqlRuntimeProtocolForResumeCallback=(
            lambda **kwargs: operations.append(
                "refresh"
            )
        ),
    )

    assert operations == []