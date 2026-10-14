# RED 53: generic keyset paging of items inside persisted Scipion Sets.
#
# This stage tests the PostgreSQL metadata *discovery* contract only.
# The executable item-pointer reference is deliberately a separate contract:
# its syntax must be proven against Scipion Pointer + PostgreSQL runtime first.
# No runtime protocol reconstruction or bulk hydration is allowed here.

import pytest

from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


class FakeReadOnlyDb:
    def __init__(self, rows):
        self.rows = list(rows)
        self.fetchAllCalls = []
        self.executeCalls = []
        self.transactionCalls = 0

    def fetchAll(self, query, params=None):
        self.fetchAllCalls.append((query, params))
        return list(self.rows)

    def execute(self, *args, **kwargs):
        self.executeCalls.append((args, kwargs))
        raise AssertionError("Pointer item discovery must be read-only")

    def transaction(self):
        self.transactionCalls += 1
        raise AssertionError("Pointer item discovery must not start transactions")


def item(scipion_id, label, *, enabled=True, item_class="Volume"):
    return {
        "scipionItemId": scipion_id,
        "label": label,
        "enabled": enabled,
        "itemClassName": item_class,
    }


def test_GetStoredSetItemsExistingReadRemainsAvailable_RED53_baseline():
    """Existing readers retain their old interface (baseline PASS)."""
    db = FakeReadOnlyDb([item(4, "Reference")])
    mapper = ScipionSetPostgresqlMapper(db=db)

    result = mapper.getStoredSetItems(setId=12, limit=2, offset=0)

    assert result == [item(4, "Reference")]
    assert len(db.fetchAllCalls) == 1
    query, params = db.fetchAllCalls[0]
    assert "FROM scipion_set_items" in query
    assert params == (12, 2, 0)
    assert db.executeCalls == []


def test_ListPointerSelectableSetItemsPageReturnsStableIdsAndNextCursor_RED53():
    db = FakeReadOnlyDb([
        item(12, "Reference"),
        item(34, "Refined", enabled=False),
        item(90, "Next page"),
    ])
    mapper = ScipionSetPostgresqlMapper(db=db)

    page = mapper.listPointerSelectableSetItemsPage(
        projectId=7,
        protocolDbId=205,
        outputName="outputVolumes",
        cursor=None,
        limit=2,
    )

    assert page == {
        "items": [
            {"scipionItemId": 12, "name": "Reference", "enabled": True, "itemClassName": "Volume"},
            {"scipionItemId": 34, "name": "Refined", "enabled": False, "itemClassName": "Volume"},
        ],
        "nextCursor": "34",
    }


def test_ListPointerSelectableSetItemsPageContinuesByItemIdNotOffset_RED53():
    db = FakeReadOnlyDb([item(35, "Volume B"), item(90, "Volume C")])
    mapper = ScipionSetPostgresqlMapper(db=db)

    page = mapper.listPointerSelectableSetItemsPage(
        projectId=7,
        protocolDbId=205,
        outputName="outputVolumes",
        cursor="34",
        limit=2,
    )

    assert [entry["scipionItemId"] for entry in page["items"]] == [35, 90]
    assert page["nextCursor"] is None
    assert len(db.fetchAllCalls) == 1
    query, params = db.fetchAllCalls[0]
    assert '"scipionItemId" > %s' in query
    assert " OFFSET " not in " ".join(query.upper().split())
    assert params[-1] == 3  # Fetch limit+1 to know whether another page exists.
    assert 34 in params  # The cursor is interpreted as a numeric persistent item ID.


def test_ListPointerSelectableSetItemsPageEmptySetIsSafe_RED53():
    db = FakeReadOnlyDb([])
    mapper = ScipionSetPostgresqlMapper(db=db)

    page = mapper.listPointerSelectableSetItemsPage(
        projectId=7,
        protocolDbId=205,
        outputName="outputEmptySet",
        limit=50,
    )

    assert page == {"items": [], "nextCursor": None}
    assert len(db.fetchAllCalls) == 1


def test_ListPointerSelectableSetItemsPageRejectsBadCursorsAndLimits_RED53():
    db = FakeReadOnlyDb([])
    mapper = ScipionSetPostgresqlMapper(db=db)

    for kwargs in (
        {"cursor": "34; DELETE FROM scipion_set_items"},
        {"cursor": "-1"},
        {"limit": 0},
        {"limit": 500},
    ):
        with pytest.raises(ValueError):
            mapper.listPointerSelectableSetItemsPage(
                projectId=7,
                protocolDbId=205,
                outputName="outputVolumes",
                **kwargs,
            )

    assert db.fetchAllCalls == []
    assert db.executeCalls == []


def test_ListPointerSelectableSetItemsPageIsScopedBoundedAndMetadataOnly_RED53():
    db = FakeReadOnlyDb([item(41, "One volume")])
    mapper = ScipionSetPostgresqlMapper(db=db)

    page = mapper.listPointerSelectableSetItemsPage(
        projectId=7,
        protocolDbId=205,
        outputName="outputVolumes",
        limit=50,
    )

    assert page["items"][0]["scipionItemId"] == 41
    assert len(db.fetchAllCalls) == 1
    query, params = db.fetchAllCalls[0]
    normalized = " ".join(query.split())
    assert "FROM scipion_sets" in normalized
    assert "JOIN scipion_set_items" in normalized
    assert '"projectId" = %s' in normalized
    assert '"protocolDbId" = %s' in normalized
    assert '"outputName" = %s' in normalized
    assert "runtimeReserved" in normalized
    assert "ORDER BY" in normalized
    assert '"scipionItemId"' in normalized
    assert "LIMIT %s" in normalized
    assert "OFFSET" not in normalized
    # JSONB object graphs are NOT needed for the small selector list.
    assert '"values"' not in normalized
    assert "SELECT *" not in normalized.upper()
    assert params[:3] == (7, 205, "outputVolumes")
    assert params[-1] == 51
    assert db.executeCalls == []
    assert db.transactionCalls == 0
