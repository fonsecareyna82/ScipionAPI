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
import pytest

from app.backend.mapper.postgresql import (
    PROTOCOL_LAUNCH_USER_LOCK_NAMESPACE,
    PostgresqlFlatMapper,
)


class FakeDb:
    def __init__(self):
        self.fetchOneCalls = []
        self.executeCalls = []
        self.activeCount = 0

    def fetchOne(
            self,
            query,
            params=None,
    ):
        normalizedQuery = " ".join(
            str(query).split()
        )

        self.fetchOneCalls.append({
            "query": normalizedQuery,
            "params": params,
        })

        return {
            "count": self.activeCount,
        }

    def execute(
            self,
            query,
            params=None,
            commit=True,
    ):
        normalizedQuery = " ".join(
            str(query).split()
        )

        self.executeCalls.append({
            "query": normalizedQuery,
            "params": params,
            "commit": commit,
        })

        return None


def buildMapper():
    mapper = object.__new__(
        PostgresqlFlatMapper
    )

    mapper.db = FakeDb()

    return mapper


def test_CountActiveProtocolExecutionsForUser():
    mapper = buildMapper()
    mapper.db.activeCount = 2

    count = mapper.countActiveProtocolExecutionsForUser(
        7
    )

    assert count == 2

    assert len(
        mapper.db.fetchOneCalls
    ) == 1

    call = mapper.db.fetchOneCalls[0]

    assert "'scheduled'" in call["query"]
    assert "'launched'" in call["query"]
    assert "'running'" in call["query"]
    assert "'_scipionWebRuntime'" in call["query"]
    assert "'launchedByUserId'" in call["query"]
    assert '"projectId"' in call["query"]
    assert '"protocolId"' in call["query"]

    assert call["params"] == (
        "7",
    )


def test_ProtocolLaunchUserLockAcquiresAndReleases():
    mapper = buildMapper()

    with mapper.protocolLaunchUserLock(
        7
    ):
        assert len(
            mapper.db.executeCalls
        ) == 1

        assert (
            "pg_advisory_lock"
            in mapper.db.executeCalls[0]["query"]
        )

    assert len(
        mapper.db.executeCalls
    ) == 2

    assert (
        "pg_advisory_unlock"
        in mapper.db.executeCalls[1]["query"]
    )

    assert mapper.db.executeCalls[0]["params"] == (
        PROTOCOL_LAUNCH_USER_LOCK_NAMESPACE,
        7,
    )

    assert mapper.db.executeCalls[1]["params"] == (
        PROTOCOL_LAUNCH_USER_LOCK_NAMESPACE,
        7,
    )


def test_ProtocolLaunchUserLockReleasesAfterError():
    mapper = buildMapper()

    with pytest.raises(
            RuntimeError,
            match="boom",
    ):
        with mapper.protocolLaunchUserLock(
            7
        ):
            raise RuntimeError(
                "boom"
            )

    assert len(
        mapper.db.executeCalls
    ) == 2

    assert (
        "pg_advisory_unlock"
        in mapper.db.executeCalls[1]["query"]
    )