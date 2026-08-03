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

import app.backend.runtime.runtime_artifact_report_service as artifactReportModule
from app.backend.runtime.runtime_artifact_report_service import RuntimeArtifactReportService


class ForbiddenDb:
    def fetchOne(self, *args, **kwargs):
        raise AssertionError(
            "RuntimeArtifactReportService must not call db.fetchOne()"
        )

    def fetchAll(self, *args, **kwargs):
        raise AssertionError(
            "RuntimeArtifactReportService must not call db.fetchAll()"
        )

    def execute(self, *args, **kwargs):
        raise AssertionError(
            "RuntimeArtifactReportService must not call db.execute()"
        )


class MapperStub:
    def __init__(self):
        self.db = ForbiddenDb()


class ProtocolStub:
    def __init__(self, workingDir):
        self.workingDir = str(
            workingDir
        )

    def getWorkingDir(self):
        return self.workingDir

    def getDbPath(self):
        return "run.db"


def test_ArtifactReportDelegatesPostgresqlReads(
        monkeypatch,
        tmp_path,
):
    workingDir = (
        tmp_path
        / "Runs"
        / "000019_Test"
    )

    logsDir = workingDir / "logs"

    logsDir.mkdir(
        parents=True,
        exist_ok=True,
    )

    outputSqlite = (
        workingDir
        / "output.sqlite"
    )

    outputSqlite.write_bytes(
        b"output"
    )

    (
        logsDir
        / "steps.sqlite"
    ).write_bytes(
        b"steps"
    )

    repositoryCalls = []

    class ProtocolGraphRepositoryStub:
        def loadProtocolRuntimeArtifactRows(
                self,
                mapper,
                projectId,
                protocolId,
        ):
            repositoryCalls.append({
                "mapper": mapper,
                "projectId": projectId,
                "protocolId": protocolId,
            })

            return {
                "sets": [
                    {
                        "id": 71,
                        "projectId": 7,
                        "protocolDbId": 31,
                        "objectId": 81,
                        "outputName": "outputTiltSeries",
                        "setClassName": "SetOfTiltSeries",
                        "itemClassName": "TiltSeries",
                        "properties": {
                            "fileName": "output.sqlite",
                            "itemsCount": 4,
                        },
                    },
                ],
                "objects": [
                    {
                        "name": "outputVolume",
                        "path": "outputVolume",
                        "className": "Volume",
                        "scipionObjId": 91,
                    },
                ],
                "setCountsById": {
                    71: {
                        "rootItemsCount": 4,
                        "tablesCount": 2,
                        "tableItemsCount": 8,
                    },
                },
            }

    monkeypatch.setattr(
        artifactReportModule,
        "ProtocolGraphRepository",
        ProtocolGraphRepositoryStub,
    )

    mapper = MapperStub()

    result = RuntimeArtifactReportService().buildPostgresqlRuntimeArtifactReport(
        mapper=mapper,
        projectId=7,
        protocolId=19,
        protocol=ProtocolStub(
            workingDir
        ),
        resolveScipionProtocolIdCallback=lambda **kwargs: 19,
        getCurrentProjectPathCallback=lambda: str(tmp_path),
    )

    assert repositoryCalls == [
        {
            "mapper": mapper,
            "projectId": 7,
            "protocolId": 19,
        },
    ]

    assert result["postgresqlOutputs"] == {
        "sets": [
            {
                "id": 71,
                "projectId": 7,
                "protocolDbId": 31,
                "objectId": 81,
                "outputName": "outputTiltSeries",
                "setClassName": "SetOfTiltSeries",
                "itemClassName": "TiltSeries",
                "properties": {
                    "fileName": "output.sqlite",
                    "itemsCount": 4,
                },
            },
        ],
        "objects": [
            {
                "name": "outputVolume",
                "path": "outputVolume",
                "className": "Volume",
                "scipionObjId": 91,
            },
        ],
        "outputsPersisted": True,
    }

    outputItems = result[
        "legacyArtifactsByRole"
    ]["outputSqlites"]

    assert len(outputItems) == 1

    viewerReadiness = outputItems[0][
        "viewerReadiness"
    ]

    assert viewerReadiness == {
        "ready": True,
        "reason": "postgresql_reader_available",
        "reader": "PostgresqlTiltSeriesReader",
        "setClassName": "SetOfTiltSeries",
        "itemClassName": "TiltSeries",
        "itemsCount": 4,
        "rootItemsCount": 4,
        "tablesCount": 2,
        "tableItemsCount": 8,
    }

    source = inspect.getsource(
        RuntimeArtifactReportService.buildPostgresqlRuntimeArtifactReport
    )

    assert "loadProtocolRuntimeArtifactRows(" in source
    assert ".db.fetchOne(" not in source
    assert ".db.fetchAll(" not in source
    assert ".db.execute(" not in source
    assert ".db.transaction(" not in source