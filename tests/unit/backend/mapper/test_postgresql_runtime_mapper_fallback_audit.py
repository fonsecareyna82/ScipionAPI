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
import logging

from app.backend.mapper.postgresql_runtime_mapper import (
    PostgresqlRuntimeMapper,
)


class FakeReadFallbackMapper:
    def __init__(self):
        self.selectedIds = []

    def selectById(self, objId):
        self.selectedIds.append(objId)
        return object()


def buildMapper(monkeypatch, enabled):
    if enabled:
        monkeypatch.setenv(
            "SCIPION_POSTGRESQL_FALLBACK_AUDIT",
            "1",
        )
    else:
        monkeypatch.delenv(
            "SCIPION_POSTGRESQL_FALLBACK_AUDIT",
            raising=False,
        )

    mapper = object.__new__(
        PostgresqlRuntimeMapper
    )

    mapper.projectId = 4
    mapper._initializeFallbackAudit()

    return mapper


def test_FallbackAuditIsDisabledByDefault(
        monkeypatch,
):
    mapper = buildMapper(
        monkeypatch,
        enabled=False,
    )

    mapper._recordReadFallback(
        "selectById",
        objectId=100,
    )

    assert mapper.getFallbackAuditReport() == {
        "projectId": 4,
        "totalCalls": 0,
        "items": [],
    }


def test_FallbackAuditAggregatesCallsByOperationAndCaller(
        monkeypatch,
):
    mapper = buildMapper(
        monkeypatch,
        enabled=True,
    )

    mapper._recordReadFallback(
        "selectById",
        objectId=100,
    )

    mapper._recordReadFallback(
        "selectById",
        objectId=200,
    )

    report = mapper.getFallbackAuditReport()

    assert report["projectId"] == 4
    assert report["totalCalls"] == 2
    assert len(report["items"]) == 1

    item = report["items"][0]

    assert item["operation"] == "selectById"
    assert item["count"] == 2
    assert item["context"] == {
        "objectId": 100,
    }

    assert (
        "test_FallbackAuditAggregatesCallsByOperationAndCaller"
        in item["caller"]
    )


def test_SelectByIdFallbackUsesExplicitAuditOperation(
        monkeypatch,
):
    mapper = buildMapper(
        monkeypatch,
        enabled=True,
    )

    fallbackMapper = FakeReadFallbackMapper()
    mapper.readFallbackMapper = fallbackMapper

    result = mapper._selectByIdFromReadFallback(
        100,
        auditOperation=(
            "selectRuntimeProtocolById."
            "compatibilityMirror"
        ),
    )

    assert result is not None
    assert fallbackMapper.selectedIds == [100]

    report = mapper.getFallbackAuditReport()

    assert report["totalCalls"] == 1
    assert report["items"][0]["operation"] == (
        "selectRuntimeProtocolById."
        "compatibilityMirror"
    )

    assert report["items"][0]["context"] == {
        "objectId": 100,
    }


def test_FallbackAuditLogsAndClearsSummary(
        monkeypatch,
        caplog,
):
    mapper = buildMapper(
        monkeypatch,
        enabled=True,
    )

    mapper._recordReadFallback(
        "selectAll",
        iterate=False,
    )

    with caplog.at_level(logging.WARNING):
        mapper._logFallbackAuditSummary()

    assert (
        "POSTGRESQL_RUNTIME_FALLBACK summary"
        in caplog.text
    )

    assert mapper.getFallbackAuditReport() == {
        "projectId": 4,
        "totalCalls": 0,
        "items": [],
    }