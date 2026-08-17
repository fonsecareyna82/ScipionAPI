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
from types import SimpleNamespace

import pytest

from app.backend.runtime.protocol_graph_repository import (
    ProtocolGraphRepository,
)


class FakeCursor:
    def __init__(self, rowcount=0):
        self.rowcount = int(rowcount)


class FakeDb:
    def __init__(self):
        self.events = []
        self.executeCalls = []
        self.fetchAllCalls = []
        self.inTransaction = False
        self.executeHandler = None
        self.fetchAllHandler = None

    @contextmanager
    def transaction(self):
        assert self.inTransaction is False
        self.inTransaction = True
        self.events.append("begin")

        try:
            yield
        except Exception:
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")
        finally:
            self.inTransaction = False

    def execute(self, query, params=None, commit=True):
        call = {
            "query": query,
            "params": params,
            "commit": commit,
            "inTransaction": self.inTransaction,
        }
        self.executeCalls.append(call)

        if self.executeHandler is not None:
            return self.executeHandler(
                query=query,
                params=params,
                commit=commit,
            )

        return FakeCursor()

    def fetchAll(self, query, params=None):
        call = {
            "query": query,
            "params": params,
            "inTransaction": self.inTransaction,
        }
        self.fetchAllCalls.append(call)

        if self.fetchAllHandler is not None:
            return self.fetchAllHandler(
                query=query,
                params=params,
            )

        return []


def makeMapper():
    return SimpleNamespace(
        db=FakeDb()
    )


def patchSuccessfulDelete(
        monkeypatch,
        repository,
        mapper,
        *,
        selectedRows=None,
        affectedChildren=None,
        externalDescendants=None,
        runtimeObjectIds=None,
        runtimeSetObjectIds=None,
        deletedCount=None,
):
    selectedRows = selectedRows or [
        {
            "protocolDbId": 101,
            "protocolId": "10",
            "status": "finished",
        },
        {
            "protocolDbId": 102,
            "protocolId": "11",
            "status": "saved",
        },
    ]
    affectedChildren = list(
        affectedChildren
        if affectedChildren is not None
        else [103]
    )
    externalDescendants = list(
        externalDescendants
        if externalDescendants is not None
        else []
    )
    runtimeObjectIds = list(
        runtimeObjectIds
        if runtimeObjectIds is not None
        else [9001, 9002]
    )
    runtimeSetObjectIds = list(
        runtimeSetObjectIds
        if runtimeSetObjectIds is not None
        else [9001]
    )
    deletedCount = (
        len(selectedRows)
        if deletedCount is None
        else int(deletedCount)
    )

    calls = []

    def assertInTransaction(stage):
        assert mapper.db.inTransaction is True
        calls.append(stage)

    def lockSelected(**kwargs):
        assertInTransaction("lock_selected")
        return list(selectedRows)

    def loadAffected(**kwargs):
        assertInTransaction("load_affected")
        return list(affectedChildren)

    def lockProtocols(**kwargs):
        assertInTransaction(
            (
                "lock_protocols",
                tuple(kwargs.get("protocolDbIds") or []),
            )
        )
        return list(kwargs.get("protocolDbIds") or [])

    def loadExternal(**kwargs):
        assertInTransaction("load_external")
        return list(externalDescendants)

    def loadRuntimeIdentities(**kwargs):
        assertInTransaction("load_runtime_identities")
        return {
            "runtimeObjectIds": list(runtimeObjectIds),
            "runtimeSetObjectIds": list(runtimeSetObjectIds),
        }

    def deleteRelations(**kwargs):
        assertInTransaction(
            (
                "delete_relations",
                tuple(kwargs.get("runtimeObjectIds") or []),
            )
        )
        return 3

    def deleteProtocols(**kwargs):
        assertInTransaction("delete_protocols")
        assert kwargs["commit"] is False
        return deletedCount

    def refreshParents(**kwargs):
        assertInTransaction("refresh_parents")
        assert kwargs["commit"] is False
        return {
            "refreshed": [
                {
                    "childProtocolDbId": childDbId,
                    "parentProtocolDbIds": [],
                    "parentProtocolIds": [],
                    "dependenciesSaved": 0,
                }
                for childDbId in affectedChildren
            ],
            "count": len(affectedChildren),
        }

    monkeypatch.setattr(
        repository,
        "_lockProtocolRowsForDelete",
        lockSelected,
    )
    monkeypatch.setattr(
        repository,
        "loadAffectedChildProtocolDbIdsForDeletedParents",
        loadAffected,
    )
    monkeypatch.setattr(
        repository,
        "_lockProtocolDbIds",
        lockProtocols,
    )
    monkeypatch.setattr(
        repository,
        "loadExternalDescendantsForDeleteValidation",
        loadExternal,
    )
    monkeypatch.setattr(
        repository,
        "_loadProtocolRuntimeIdentities",
        loadRuntimeIdentities,
    )
    monkeypatch.setattr(
        repository,
        "_deleteRuntimeRelationsForIdentities",
        deleteRelations,
    )
    monkeypatch.setattr(
        repository,
        "deleteProtocolsByDbIds",
        deleteProtocols,
    )
    monkeypatch.setattr(
        repository,
        "refreshParentsForChildren",
        refreshParents,
    )

    return calls


def test_NormalizePositiveIntIdsDeduplicatesAndSkipsInvalidValues():
    repository = ProtocolGraphRepository()

    assert repository._normalizePositiveIntIds(
        [
            "10",
            10,
            11,
            0,
            -1,
            None,
            "",
            "bad",
            12.0,
        ]
    ) == [
        10,
        11,
        12,
    ]


def test_LoadAffectedChildrenUsesRefsDependenciesAndParentIds():
    mapper = makeMapper()
    repository = ProtocolGraphRepository()

    mapper.db.fetchAllHandler = (
        lambda **kwargs: [
            {"protocolDbId": 201},
            {"protocolDbId": 202},
        ]
    )

    result = (
        repository
        .loadAffectedChildProtocolDbIdsForDeletedParents(
            mapper=mapper,
            projectId=7,
            parentProtocolDbIds=[
                101,
                "102",
                101,
                0,
            ],
            parentProtocolIds=[
                10,
                "11",
                10,
            ],
        )
    )

    assert result == [
        201,
        202,
    ]

    call = mapper.db.fetchAllCalls[0]
    normalizedQuery = " ".join(
        str(call["query"]).split()
    )

    assert "FROM protocol_input_refs" in normalizedQuery
    assert "FROM protocol_dependencies" in normalizedQuery
    assert 'p."parentIds"' in normalizedQuery
    assert call["params"] == (
        7,
        [101, 102],
        7,
        [101, 102],
        7,
        [10, 11],
        7,
        [101, 102],
    )


def test_LoadSubworkflowUsesDependenciesAndInputRefs():
    mapper = makeMapper()
    repository = ProtocolGraphRepository()

    mapper.db.fetchAllHandler = lambda **kwargs: [
        {
            "protocolDbId": 1305,
            "protocolId": "410",
            "level": 0,
        },
        {
            "protocolDbId": 1306,
            "protocolId": "411",
            "level": 1,
        },
        {
            "protocolDbId": 1307,
            "protocolId": "412",
            "level": 2,
        },
    ]

    result = repository.loadSubworkflowRows(
        mapper=mapper,
        projectId=7,
        rootProtocolDbId=1305,
    )

    assert [row["protocolId"] for row in result] == [
        "410",
        "411",
        "412",
    ]

    call = mapper.db.fetchAllCalls[0]
    normalizedQuery = " ".join(str(call["query"]).split())

    assert "FROM protocol_dependencies" in normalizedQuery
    assert "FROM protocol_input_refs" in normalizedQuery

    assert call["params"] == (
        7,
        7,
        7,
        1305,
        7,
    )


def test_DeleteRuntimeRelationsMatchesEveryRuntimeIdentityColumn():
    mapper = makeMapper()
    repository = ProtocolGraphRepository()

    mapper.db.executeHandler = (
        lambda **kwargs: FakeCursor(
            rowcount=4
        )
    )

    deleted = (
        repository
        ._deleteRuntimeRelationsForIdentities(
            mapper=mapper,
            projectId=9,
            runtimeObjectIds=[
                10,
                9001,
                9002,
                9001,
            ],
        )
    )

    assert deleted == 4

    call = mapper.db.executeCalls[0]
    normalizedQuery = " ".join(
        str(call["query"]).split()
    )

    assert "DELETE FROM scipion_relations" in normalizedQuery
    assert '"creatorObjId" = ANY(%s)' in normalizedQuery
    assert '"parentObjId" = ANY(%s)' in normalizedQuery
    assert '"childObjId" = ANY(%s)' in normalizedQuery
    assert call["params"] == (
        9,
        [10, 9001, 9002],
        [10, 9001, 9002],
        [10, 9001, 9002],
    )
    assert call["commit"] is False


def test_DeleteProtocolsAndRefreshChildrenRunsInsideOneTransaction(
        monkeypatch,
):
    mapper = makeMapper()
    repository = ProtocolGraphRepository()

    calls = patchSuccessfulDelete(
        monkeypatch,
        repository,
        mapper,
    )

    result = (
        repository
        .deleteProtocolsAndRefreshChildren(
            mapper=mapper,
            projectId=1,
            protocolDbIds=[
                101,
                "102",
                101,
            ],
            blockedStatusTexts={
                "running",
                "launched",
                "scheduled",
            },
        )
    )

    assert mapper.db.events == [
        "begin",
        "commit",
    ]

    assert result == {
        "deletedProtocolIds": [
            "10",
            "11",
        ],
        "deletedProtocolDbIds": [
            101,
            102,
        ],
        "deletedCount": 2,
        "runtimeObjectIds": [
            9001,
            9002,
        ],
        "runtimeSetObjectIds": [
            9001,
        ],
        "relationsDeleted": 3,
        "affectedChildren": [
            103,
        ],
        "parentsRefresh": {
            "refreshed": [
                {
                    "childProtocolDbId": 103,
                    "parentProtocolDbIds": [],
                    "parentProtocolIds": [],
                    "dependenciesSaved": 0,
                },
            ],
            "count": 1,
        },
    }

    assert "delete_relations" in [
        call
        if isinstance(call, str)
        else call[0]
        for call in calls
    ]
    assert calls.index("delete_protocols") < (
        calls.index("refresh_parents")
    )

    relationCall = next(
        call
        for call in calls
        if (
            isinstance(call, tuple)
            and call[0] == "delete_relations"
        )
    )

    assert relationCall[1] == (
        10,
        11,
        9001,
        9002,
    )


def test_DeleteRollsBackWhenASelectedProtocolDisappears(
        monkeypatch,
):
    mapper = makeMapper()
    repository = ProtocolGraphRepository()

    monkeypatch.setattr(
        repository,
        "_lockProtocolRowsForDelete",
        lambda **kwargs: [
            {
                "protocolDbId": 101,
                "protocolId": "10",
                "status": "finished",
            },
        ],
    )

    deleteCalled = False

    def failIfDeleteCalled(**kwargs):
        nonlocal deleteCalled
        deleteCalled = True
        return 0

    monkeypatch.setattr(
        repository,
        "deleteProtocolsByDbIds",
        failIfDeleteCalled,
    )

    with pytest.raises(
            RuntimeError,
            match="protocol rows disappeared",
    ):
        repository.deleteProtocolsAndRefreshChildren(
            mapper=mapper,
            projectId=1,
            protocolDbIds=[
                101,
                102,
            ],
            blockedStatusTexts={
                "running",
            },
        )

    assert mapper.db.events == [
        "begin",
        "rollback",
    ]
    assert deleteCalled is False


def test_DeleteRollsBackWhenSelectedProtocolBecomesActive(
        monkeypatch,
):
    mapper = makeMapper()
    repository = ProtocolGraphRepository()

    monkeypatch.setattr(
        repository,
        "_lockProtocolRowsForDelete",
        lambda **kwargs: [
            {
                "protocolDbId": 101,
                "protocolId": "10",
                "status": "running",
            },
        ],
    )

    with pytest.raises(
            RuntimeError,
            match="became active",
    ):
        repository.deleteProtocolsAndRefreshChildren(
            mapper=mapper,
            projectId=1,
            protocolDbIds=[
                101,
            ],
            blockedStatusTexts={
                "running",
                "launched",
                "scheduled",
            },
        )

    assert mapper.db.events == [
        "begin",
        "rollback",
    ]


def test_DeleteRollsBackWhenExternalDescendantBecomesBlocked(
        monkeypatch,
):
    mapper = makeMapper()
    repository = ProtocolGraphRepository()

    patchSuccessfulDelete(
        monkeypatch,
        repository,
        mapper,
        selectedRows=[
            {
                "protocolDbId": 101,
                "protocolId": "10",
                "status": "finished",
            },
        ],
        affectedChildren=[
            103,
        ],
        externalDescendants=[
            {
                "protocolDbId": 103,
                "protocolId": "12",
                "status": "saved",
                "setsCount": 1,
                "objectsCount": 0,
            },
        ],
    )

    with pytest.raises(
            RuntimeError,
            match="Blocked descendants",
    ):
        repository.deleteProtocolsAndRefreshChildren(
            mapper=mapper,
            projectId=1,
            protocolDbIds=[
                101,
            ],
            blockedStatusTexts={
                "running",
                "launched",
                "scheduled",
            },
        )

    assert mapper.db.events == [
        "begin",
        "rollback",
    ]


def test_DeleteRollsBackWhenDeleteRowcountDoesNotMatch(
        monkeypatch,
):
    mapper = makeMapper()
    repository = ProtocolGraphRepository()

    patchSuccessfulDelete(
        monkeypatch,
        repository,
        mapper,
        deletedCount=1,
    )

    with pytest.raises(
            RuntimeError,
            match="affected 1 rows, expected 2",
    ):
        repository.deleteProtocolsAndRefreshChildren(
            mapper=mapper,
            projectId=1,
            protocolDbIds=[
                101,
                102,
            ],
            blockedStatusTexts={
                "running",
                "launched",
                "scheduled",
            },
        )

    assert mapper.db.events == [
        "begin",
        "rollback",
    ]


def test_RefreshParentsForChildrenUsesExistingGraphWithoutNestedTransaction(
        monkeypatch,
):
    mapper = makeMapper()
    repository = ProtocolGraphRepository()

    dependencyCalls = []
    parentIdCalls = []

    monkeypatch.setattr(
        repository,
        "loadParentGraphForChildProtocol",
        lambda **kwargs: {
            "parentProtocolDbIds": [
                201,
                202,
            ],
            "parentProtocolIds": [
                20,
                21,
            ],
        },
    )

    def replaceDependencies(**kwargs):
        dependencyCalls.append(kwargs)
        return 2

    def updateParentIds(**kwargs):
        parentIdCalls.append(kwargs)
        return 1

    monkeypatch.setattr(
        repository,
        "replaceDependenciesForProtocol",
        replaceDependencies,
    )
    monkeypatch.setattr(
        repository,
        "updateProtocolParentIds",
        updateParentIds,
    )

    with mapper.db.transaction():
        result = (
            repository
            .refreshParentsForChildren(
                mapper=mapper,
                projectId=1,
                childProtocolDbIds=[
                    301,
                    301,
                    "bad",
                ],
                commit=False,
            )
        )

    assert mapper.db.events == [
        "begin",
        "commit",
    ]
    assert result == {
        "refreshed": [
            {
                "childProtocolDbId": 301,
                "parentProtocolDbIds": [
                    201,
                    202,
                ],
                "parentProtocolIds": [
                    20,
                    21,
                ],
                "dependenciesSaved": 2,
            },
        ],
        "count": 1,
    }

    assert dependencyCalls[0]["commit"] is False
    assert parentIdCalls[0]["commit"] is False