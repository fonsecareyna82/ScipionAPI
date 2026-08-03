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

from app.backend.runtime.output_relation_repair_service import (
    RuntimeOutputRelationRepairService,
)


class ExampleNativeSet:
    pass


class FakeNativeRuntimeOutput:
    _postgresqlNativeSetClass = (
        ExampleNativeSet
    )

    def __init__(self):
        self._setOfTiltSeries = None
        self.writeCalls = []

    def isPostgresqlRuntimeOutput(
            self,
    ):
        return True

    def getSetOfTiltSeries(
            self,
    ):
        return self._setOfTiltSeries

    def setSetOfTiltSeries(
            self,
            value,
    ):
        self._setOfTiltSeries = value

    def write(
            self,
            properties=True,
    ):
        self.writeCalls.append(
            properties
        )

        raise AssertionError(
            "Native PostgreSQL runtime outputs "
            "must not be written to SQLite"
        )


class FakeGenericPostgresqlProxy:
    def isPostgresqlRuntimeOutput(
            self,
    ):
        return True


class FakeLegacyOutput:
    pass


class FakeProtocolGraphRepository:
    def getPostgresqlRuntimeOutputInfo(
            self,
            mapper,
            projectId,
            parentProtocolDbId,
            outputName,
    ):
        return {
            "exists": True,
            "setId": 31,
            "runtimeObjectId": 401,
            "className": (
                "SetOfCTFTomoSeries"
            ),
            "itemClassName": (
                "CTFTomoSeries"
            ),
            "properties": {},
        }


def test_RequiresFallbackOnlyForGenericProxy():
    service = (
        RuntimeOutputRelationRepairService()
    )

    assert service.requiresFallbackOutput(
        None
    )

    assert service.requiresFallbackOutput(
        FakeGenericPostgresqlProxy()
    )

    assert not service.requiresFallbackOutput(
        FakeNativeRuntimeOutput()
    )

    assert not service.requiresFallbackOutput(
        FakeLegacyOutput()
    )


def test_RepairLinksNativePostgresqlOutputsWithoutFallback():
    service = (
        RuntimeOutputRelationRepairService()
    )

    service.protocolGraphRepository = (
        FakeProtocolGraphRepository()
    )

    sourceOutput = (
        FakeNativeRuntimeOutput()
    )

    relatedOutput = (
        FakeNativeRuntimeOutput()
    )

    parentProtocol = SimpleNamespace(
        outputCtf=sourceOutput,
        outputTiltSeries=relatedOutput,
    )

    def failParentProtocolResolution(
            **kwargs,
    ):
        raise AssertionError(
            "Parent protocol must not be "
            "reloaded for native outputs"
        )

    def failMapperRepair(
            **kwargs,
    ):
        raise AssertionError(
            "Native PostgreSQL runtime mapper "
            "must not be repaired with legacy SQLite"
        )

    report = service.repairMissingOutputRelation(
        mapper=object(),
        projectId=1,
        parentProtocol=parentProtocol,
        parentProtocolDbId=10,
        parentScipionProtocolId=100,
        outputName="outputCtf",
        outputObj=sourceOutput,
        inputRefRows=[],
        currentInputName="inputCtf",
        relationRule={
            "name": "set_of_tilt_series",
            "getterName": (
                "getSetOfTiltSeries"
            ),
            "setterName": (
                "setSetOfTiltSeries"
            ),
        },
        getParentProtocolCallback=(
            failParentProtocolResolution
        ),
        repairOutputMapperCallback=(
            failMapperRepair
        ),
        relatedOutputCandidate={
            "parentProtocolId": 100,
            "parentProtocolDbId": 10,
            "outputName": (
                "outputTiltSeries"
            ),
            "outputInfo": {
                "exists": True,
                "setId": 32,
                "runtimeObjectId": 402,
                "className": (
                    "SetOfTiltSeries"
                ),
                "itemClassName": (
                    "TiltSeries"
                ),
                "properties": {},
            },
        },
        persistRepairedRelation=False,
    )

    assert report["checked"] is True
    assert report["repaired"] is True

    assert (
        report["reason"]
        == "linked_runtime_output_relation"
    )

    assert (
        sourceOutput.getSetOfTiltSeries()
        is relatedOutput
    )

    assert sourceOutput.writeCalls == []

    assert (
        report[
            "sourceOutputMapperRepairSkipped"
        ]
        == "native_postgresql_runtime_output"
    )

    assert (
        report[
            "relatedOutputMapperRepairSkipped"
        ]
        == "native_postgresql_runtime_output"
    )

    assert (
        report[
            "relationPropertiesWritten"
        ]
        is False
    )

    assert (
        report[
            "relationPropertiesWriteSkipped"
        ]
        == "postgresql_runtime_output_read_only"
    )

    assert (
        "sourceOutputLoadedFromFallback"
        not in report
    )

    assert (
        "relatedOutputLoadedFromFallback"
        not in report
    )