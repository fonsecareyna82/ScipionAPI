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
from contextlib import contextmanager
import pytest
from app.backend.mapper.postgresql import PostgresqlFlatMapper


class FakeCursor:
    def __init__(self, rowcount=0):
        self.rowcount = int(rowcount)


class FakeDb:
    def __init__(self):
        self.executeReturningOneCalls = []
        self.executeCalls = []
        self.failOnExecuteCall = None
        self.transactionCalls = 0
        self.transactionCommits = 0
        self.transactionRollbacks = 0
        self.executeResult = FakeCursor(rowcount=3)

        self.executeReturningOneResult = {
            "index": 2,
            "name": "processStep",
            "status": "finished",
        }

    def execute(
            self,
            query,
            params,
            commit=True,
    ):
        self.executeCalls.append({
            "query": query,
            "params": params,
            "commit": commit,
        })

        if (
                self.failOnExecuteCall is not None
                and len(self.executeCalls) == self.failOnExecuteCall
        ):
            raise RuntimeError("execute failed")

        return self.executeResult

    @contextmanager
    def transaction(self):
        self.transactionCalls += 1

        try:
            yield self
            self.transactionCommits += 1

        except Exception:
            self.transactionRollbacks += 1
            raise

    def executeReturningOne(
            self,
            query,
            params,
    ):
        self.executeReturningOneCalls.append(
            {
                "query": query,
                "params": params,
            },
        )

        return self.executeReturningOneResult


def test_UpdateProtocolStepStatusUpdatesSelectedStepAndReturnsRow():
    mapper = object.__new__(PostgresqlFlatMapper)
    mapper.db = FakeDb()

    result = mapper.updateProtocolStepStatus(
        projectId=1,
        protocolId=10,
        stepIndex=2,
        stepStatus="finished",
    )

    assert result == {
        "index": 2,
        "name": "processStep",
        "status": "finished",
    }
    assert (
            len(
                mapper.db
                .executeReturningOneCalls
            )
            == 1
    )

    call = (
        mapper.db
        .executeReturningOneCalls[0]
    )
    assert "UPDATE protocol_steps" in call["query"]
    assert "SET status = %s" in call["query"]
    assert '"updatedAt" = NOW()' in call["query"]
    assert 'WHERE "projectId" = %s' in call["query"]
    assert 'AND "protocolId" = %s' in call["query"]
    assert 'AND "stepIndex" = %s' in call["query"]
    assert '"stepIndex" AS index' in call["query"]
    assert call["params"] == ("finished", 1, "10", 2)


def test_PrepareProtocolStepsForContinueResetsStoredExecutionState():
    mapper = object.__new__(PostgresqlFlatMapper)
    mapper.db = FakeDb()

    result = mapper.prepareProtocolStepsForContinue(
        projectId=7,
        protocolId=31,
        statusValue="saved",
        event="continue_resume",
    )

    assert result == 3
    assert len(mapper.db.executeCalls) == 1

    call = mapper.db.executeCalls[0]

    assert "UPDATE protocol_steps" in call["query"]
    assert 'SET status = %s' in call["query"]
    assert '"initTime" = NULL' in call["query"]
    assert '"endTime" = NULL' in call["query"]
    assert '"elapsedSeconds" = 0' in call["query"]
    assert "error = NULL" in call["query"]
    assert "event = %s" in call["query"]
    assert '"updatedAt" = NOW()' in call["query"]
    assert 'WHERE "projectId" = %s' in call["query"]
    assert 'AND "protocolId" = %s' in call["query"]

    assert call["params"] == (
        "saved",
        "continue_resume",
        7,
        "31",
    )


def test_AbortRunningProtocolStepsUpdatesOnlyRunningRows():
    mapper = object.__new__(PostgresqlFlatMapper)
    mapper.db = FakeDb()

    result = mapper.abortRunningProtocolSteps(
        projectId=7,
        protocolDbId=101,
        statusValue="aborted",
        errorMessage="Protocol stopped by user.",
    )

    assert result == 3
    assert len(mapper.db.executeCalls) == 1

    call = mapper.db.executeCalls[0]

    assert "UPDATE protocol_steps" in call["query"]
    assert "SET status = %s" in call["query"]
    assert '"endTime" = COALESCE' in call["query"]
    assert "error = CASE" in call["query"]
    assert "BTRIM(error) = ''" in call["query"]
    assert '"updatedAt" = NOW()' in call["query"]
    assert 'WHERE "projectId" = %s' in call["query"]
    assert 'AND "protocolDbId" = %s' in call["query"]
    assert "AND LOWER(status) = 'running'" in call["query"]

    assert call["params"] == (
        "aborted",
        "Protocol stopped by user.",
        7,
        101,
    )


def test_ReplaceProtocolStepsRollsBackWholeReplacementWhenStepFails():
    mapper = object.__new__(PostgresqlFlatMapper)
    mapper.db = FakeDb()
    mapper.db.failOnExecuteCall = 2

    steps = [
        {
            "index": 0,
            "name": "firstStep",
            "status": "running",
        },
        {
            "index": 1,
            "name": "secondStep",
            "status": "running",
        },
    ]

    with pytest.raises(
            RuntimeError,
            match="execute failed",
    ):
        mapper.replaceProtocolSteps(
            projectId=7,
            protocolDbId=101,
            protocolId=31,
            steps=steps,
        )

    assert mapper.db.transactionCalls == 1
    assert mapper.db.transactionCommits == 0
    assert mapper.db.transactionRollbacks == 1

    assert len(mapper.db.executeCalls) == 2
    assert mapper.db.executeCalls[0]["commit"] is False
    assert mapper.db.executeCalls[1]["commit"] is False
    assert "INSERT INTO protocol_steps" in mapper.db.executeCalls[0]["query"]
    assert "INSERT INTO protocol_steps" in mapper.db.executeCalls[1]["query"]