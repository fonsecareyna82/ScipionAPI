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
import pyworkflow as pw

from app.backend.project.postgresql_project import (
    PostgresqlProject,
)


class ProtocolStub:
    def __init__(
            self,
            status="running",
    ):
        self.status = status

    def getObjId(self):
        return 20

    def getStatus(self):
        return self.status


class RuntimeMapperStub:
    def __init__(
            self,
            refreshedStatus=None,
            error=None,
    ):
        self.refreshedStatus = (
            refreshedStatus
        )

        self.error = error
        self.updatedProtocols = []

    def updateFrom(
            self,
            protocol,
    ):
        self.updatedProtocols.append(
            protocol
        )

        if self.error is not None:
            raise self.error

        if self.refreshedStatus is not None:
            protocol.status = (
                self.refreshedStatus
            )


def buildProject(
        mapper,
):
    project = object.__new__(
        PostgresqlProject
    )

    project.mapper = mapper
    project.postgresqlProjectId = 3

    project.usingPostgresqlRuntimeMapper = (
        lambda: True
    )

    return project


def test_UpdateProtocolReadsStatusFromPostgresqlOnly():
    mapper = RuntimeMapperStub(
        refreshedStatus="finished"
    )

    project = buildProject(
        mapper
    )

    protocol = ProtocolStub(
        status="running"
    )

    result = project._updateProtocol(
        protocol,
        checkPid=True,
    )

    assert result == pw.PROTOCOL_UPDATED

    assert protocol.getStatus() == (
        "finished"
    )

    assert mapper.updatedProtocols == [
        protocol,
    ]


def test_UpdateProtocolDoesNotChangeUnchangedStatus():
    mapper = RuntimeMapperStub(
        refreshedStatus="scheduled"
    )

    project = buildProject(
        mapper
    )

    protocol = ProtocolStub(
        status="scheduled"
    )

    result = project._updateProtocol(
        protocol,
        checkPid=True,
    )

    assert (
        result
        == pw.NOT_UPDATED_UNNECESSARY
    )

    assert protocol.getStatus() == (
        "scheduled"
    )


def test_UpdateProtocolRefreshFailureDoesNotMarkProtocolFailed():
    mapper = RuntimeMapperStub(
        error=RuntimeError(
            "PostgreSQL read failed"
        )
    )

    project = buildProject(
        mapper
    )

    protocol = ProtocolStub(
        status="running"
    )

    result = project._updateProtocol(
        protocol,
        checkPid=True,
    )

    assert result == pw.NOT_UPDATED_ERROR

    assert protocol.getStatus() == (
        "running"
    )