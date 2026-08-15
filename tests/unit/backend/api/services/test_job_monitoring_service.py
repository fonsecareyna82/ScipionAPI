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
from datetime import datetime, timezone

import app.backend.api.services.job_monitoring_service as jobMonitoringModule

from app.backend.api.services.job_monitoring_service import (
    JobMonitoringService,
)


class MapperStub:
    def __init__(
            self,
            recentRows,
            protocolRows=None,
            activeRows=None,
    ):
        self.recentRows = list(recentRows)
        self.protocolRows = dict(protocolRows or {})
        self.activeRows = list(activeRows or [])
        self.recentLimits = []

    def listRecentProtocolExecutions(
            self,
            limit=25,
    ):
        self.recentLimits.append(limit)
        return list(self.recentRows)

    def listActiveProtocolExecutions(
            self,
    ):
        return list(
            self.activeRows
        )

    def getProtocolByProtocolId(
            self,
            protocolId,
            projectId,
    ):
        return self.protocolRows.get(
            (
                int(projectId),
                int(protocolId),
            )
        )


def test_JobMonitoringOverviewCombinesCeleryAndPostgresql(
        monkeypatch,
):
    createdAt = datetime(
        2026,
        8,
        15,
        8,
        0,
        tzinfo=timezone.utc,
    )

    updatedAt = datetime(
        2026,
        8,
        15,
        9,
        0,
        tzinfo=timezone.utc,
    )

    recentRows = [
        {
            "projectId": 2,
            "projectName": "/projects/TestXmippClassifyPca",
            "protocolId": "391",
            "protocolClassName": "XmippProtClassifyPcaStreaming",
            "status": "running",
            "createdAt": createdAt,
            "updatedAt": updatedAt,
            "runtimeMetadata": {
                "pid": 170136,
                "jobIds": [
                    "4812",
                ],
                "elapsedTimeSeconds": 12.5,
            },
        },
    ]

    protocolRows = {
        (
            2,
            391,
        ): {
            "projectId": 2,
            "protocolId": "391",
            "protocolClassName": "XmippProtClassifyPcaStreaming",
            "status": "running",
            "params": {
                "_scipionWebRuntime": {
                    "pid": 170136,
                    "jobIds": [
                        "4812",
                    ],
                },
            },
        },
    }

    mapper = MapperStub(
        recentRows=recentRows,
        protocolRows=protocolRows,
        activeRows=recentRows,
    )

    service = JobMonitoringService(
        celeryAppInstance=object()
    )

    monkeypatch.setattr(
        jobMonitoringModule.time,
        "time",
        lambda: 1020.0,
    )

    monkeypatch.setattr(
        service,
        "_getCelerySnapshot",
        lambda: {
            "available": True,
            "error": None,
            "stats": {
                "protocols@blackwell": {
                    "pool": {
                        "max-concurrency": 4,
                    },
                },
                "plugins@blackwell": {
                    "pool": {
                        "max-concurrency": 1,
                    },
                },
            },
            "active": {
                "protocols@blackwell": [
                    {
                        "id": "task-391",
                        "name": "app.tasks.executeProtocolTask",
                        "args": [
                            2,
                            391,
                            "restart",
                        ],
                        "hostname": "protocols@blackwell",
                        "time_start": 1000.0,
                        "worker_pid": 169916,
                        "delivery_info": {
                            "routing_key": "protocols",
                        },
                    },
                ],
                "plugins@blackwell": [],
            },
            "reserved": {
                "protocols@blackwell": [],
                "plugins@blackwell": [],
            },
        },
    )

    monkeypatch.setattr(
        service,
        "_getCeleryTaskState",
        lambda taskId: (
            "PROGRESS",
            "Launching protocol...",
        ),
    )

    result = service.getOverview(
        mapper=mapper,
        recentLimit=10,
    )

    assert mapper.recentLimits == [
        10,
    ]

    assert result["celeryAvailable"] is True
    assert result["celeryError"] is None

    assert result["workers"] == [
        {
            "name": "protocols@blackwell",
            "queues": [
                "protocols",
            ],
            "online": True,
            "concurrency": 4,
            "active": 1,
            "reserved": 0,
        },
        {
            "name": "plugins@blackwell",
            "queues": [
                "plugins",
            ],
            "online": True,
            "concurrency": 1,
            "active": 0,
            "reserved": 0,
        },
    ]

    assert len(
        result["activeJobs"]
    ) == 1

    activeJob = result[
        "activeJobs"
    ][0]

    assert activeJob[
        "taskId"
    ] == "task-391"

    assert activeJob[
        "projectId"
    ] == 2

    assert activeJob[
        "projectName"
    ] == "/projects/TestXmippClassifyPca"

    assert activeJob[
        "protocolId"
    ] == "391"

    assert activeJob[
        "runMode"
    ] == "restart"

    assert activeJob[
        "celeryState"
    ] == "PROGRESS"

    assert activeJob[
        "step"
    ] == "Launching protocol..."

    assert activeJob[
        "protocolStatus"
    ] == "running"

    assert activeJob[
        "worker"
    ] == "protocols@blackwell"

    assert activeJob[
        "queue"
    ] == "protocols"

    assert activeJob[
        "workerPid"
    ] == 169916

    assert activeJob[
        "protocolPid"
    ] == 170136

    assert activeJob[
        "jobIds"
    ] == [
        "4812",
    ]

    assert activeJob[
        "elapsedSeconds"
    ] == 20.0

    assert len(
        result["recentJobs"]
    ) == 1

    recentJob = result[
        "recentJobs"
    ][0]

    assert recentJob[
        "status"
    ] == "running"

    assert recentJob[
        "runtimePid"
    ] == 170136

    assert recentJob[
        "jobIds"
    ] == [
        "4812",
    ]

    assert recentJob[
        "elapsedTimeSeconds"
    ] == 12.5


def test_JobMonitoringKeepsPostgresqlHistoryWhenCeleryUnavailable(
        monkeypatch,
):
    createdAt = datetime(
        2026,
        8,
        15,
        8,
        0,
        tzinfo=timezone.utc,
    )

    updatedAt = datetime(
        2026,
        8,
        15,
        9,
        0,
        tzinfo=timezone.utc,
    )

    mapper = MapperStub(
        recentRows=[
            {
                "projectId": 1,
                "projectName": "/projects/TestWarpTemplateMatching",
                "protocolId": "70792",
                "protocolClassName": "ProtImportVolumes",
                "status": "finished",
                "createdAt": createdAt,
                "updatedAt": updatedAt,
                "runtimeMetadata": {
                    "elapsedTimeSeconds": 17.0,
                },
            },
        ]
    )

    service = JobMonitoringService(
        celeryAppInstance=object()
    )

    monkeypatch.setattr(
        jobMonitoringModule.time,
        "time",
        lambda: 1020.0,
    )

    monkeypatch.setattr(
        service,
        "_getCelerySnapshot",
        lambda: {
            "available": False,
            "error": "No Celery workers responded.",
            "stats": {},
            "active": {},
            "reserved": {},
        },
    )

    result = service.getOverview(
        mapper=mapper,
        recentLimit=5,
    )

    assert mapper.recentLimits == [
        5,
    ]

    assert result[
        "celeryAvailable"
    ] is False

    assert result[
        "celeryError"
    ] == "No Celery workers responded."

    assert result[
        "workers"
    ] == []

    assert result[
        "activeJobs"
    ] == []

    assert len(
        result["recentJobs"]
    ) == 1

    assert result[
        "recentJobs"
    ][0]["protocolId"] == "70792"

    assert result[
        "recentJobs"
    ][0]["status"] == "finished"

    assert result[
        "recentJobs"
    ][0]["elapsedTimeSeconds"] == 17.0