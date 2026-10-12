"""Real PostgreSQL checks for atomic bulk writes and independent read cursors."""

from datetime import datetime, timezone

import psycopg2
import pytest

from app.backend.mapper.postgresql_set_runtime_mapper import PostgresqlSetRuntimeMapper


@pytest.fixture
def bulkMapper(postgresqlIntegrationDb, monkeypatch, request):
    db = postgresqlIntegrationDb
    # Connection-local tables exercise the production SQL without sharing
    # fixture data or leaving persisted outputs behind.
    db.execute('''
        CREATE TEMP TABLE scipion_set_items (
            id BIGSERIAL PRIMARY KEY, "setId" BIGINT, "scipionItemId" BIGINT,
            enabled BOOLEAN, label TEXT, comment TEXT, creation TIMESTAMPTZ,
            "values" JSONB, "createdAt" TIMESTAMPTZ DEFAULT NOW(),
            "updatedAt" TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT ux_scipion_set_items_set_item UNIQUE ("setId", "scipionItemId")
        )
    ''')
    db.execute('''
        CREATE TEMP TABLE scipion_set_table_items (
            id BIGSERIAL PRIMARY KEY, "tableId" BIGINT, "parentItemId" BIGINT,
            "scipionItemId" BIGINT, enabled BOOLEAN, label TEXT, comment TEXT,
            creation TIMESTAMPTZ, "values" JSONB,
            "createdAt" TIMESTAMPTZ DEFAULT NOW(), "updatedAt" TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT ux_scipion_set_table_items_table_item UNIQUE ("tableId", "scipionItemId")
        )
    ''')
    monkeypatch.setattr(PostgresqlSetRuntimeMapper, "_loadColumns", lambda self: {})
    scope = (dict(tableId=71, parentItemId=8) if getattr(request, "param", "root") == "logical"
             else dict(setId=31, rootTableId=71))
    mapper = PostgresqlSetRuntimeMapper(db=db, itemBuilder=dict, itemSerializer=dict,
                                       writable=True, **scope)
    counters = []
    monkeypatch.setattr(mapper, "_refreshSetCounters", lambda: counters.append("refreshed"))
    mapper.BULK_APPEND_SIZE = 2
    return mapper, db, counters


def serialized(itemId, score="new"):
    return dict(scipionItemId=itemId, enabled=False, label="étiquette ' \n",
                comment=None, creation=datetime(2025, 1, 2, tzinfo=timezone.utc),
                values={"_score": score, "nested": [None, True, "café"], "optional": None})


def rows(db, table):
    return db.fetchAll('''SELECT "scipionItemId", enabled, label, comment, creation, "values"
                          FROM %s ORDER BY "scipionItemId"''' % table)


def test_RootBulkUpsertKeepsCanonicalAndLogicalRowsIdentical(bulkMapper):
    mapper, db, counters = bulkMapper
    for score in ("old", "new"):
        mapper._pendingAppendItems = [serialized(1, score), serialized(2, score)]
        mapper._flushPendingAppends()
        canonical = rows(db, "scipion_set_items")
        assert canonical == rows(db, "scipion_set_table_items")
        assert canonical[0]["values"] == serialized(1, score)["values"]
        assert canonical[0]["creation"] == serialized(1)["creation"]
        assert canonical[0]["label"] == serialized(1)["label"]
        assert canonical[0]["enabled"] is False
        assert canonical[0]["comment"] is None
    assert len(counters) == 2
    assert mapper._pendingAppendItems == []


@pytest.mark.parametrize("bulkMapper", ["root", "logical"], indirect=True)
def test_LaterChunkFailureRollsBackBothTablesAndRetainsBufferForRetry(bulkMapper):
    mapper, db, counters = bulkMapper
    with db.transaction():
        mapper._bulkUpsertSerializedItems([serialized(1, "old")])
    db.execute('''ALTER TABLE scipion_set_table_items ADD CONSTRAINT injected_failure
                  CHECK ("scipionItemId" <> 3)''')
    pending = [serialized(index) for index in (1, 2, 3)]
    mapper._pendingAppendItems = list(pending)

    with pytest.raises(psycopg2.errors.CheckViolation):
        mapper._flushPendingAppends()

    assert mapper._pendingAppendItems == pending
    assert counters == []
    logical = rows(db, "scipion_set_table_items")
    assert len(logical) == 1
    assert logical[0]["values"]["_score"] == "old"
    canonical = rows(db, "scipion_set_items")
    assert canonical == (logical if mapper.setId is not None else [])

    db.execute('ALTER TABLE scipion_set_table_items DROP CONSTRAINT injected_failure')
    assert mapper._flushPendingAppends()
    logical = rows(db, "scipion_set_table_items")
    assert [row["scipionItemId"] for row in logical] == [1, 2, 3]
    assert all(row["values"]["_score"] == "new" for row in logical)
    assert rows(db, "scipion_set_items") == (logical if mapper.setId is not None else [])
    assert mapper._pendingAppendItems == []
    assert counters == ["refreshed"]


def test_IteratorPreservesOriginalResultAcrossSameConnectionCommits(bulkMapper):
    mapper, db, _ = bulkMapper
    with db.transaction():
        mapper._bulkUpsertSerializedItems([serialized(index, "old") for index in (1, 2, 3)])
    items = mapper.selectAll(orderBy="id", direction="DESC", limit=(2, 1))
    # SQL executes at selectAll(), before any objects are requested.
    with db.transaction():
        mapper._bulkUpsertSerializedItems([serialized(1), serialized(4)])
    assert db.fetchOne("SELECT 1 AS unrelated")["unrelated"] == 1
    result = list(items)
    assert [item["scipionItemId"] for item in result] == [2, 1]
    assert all(item["values"]["_score"] == "old" for item in result)
    assert [item["scipionItemId"] for item in mapper.selectAll()] == [1, 2, 3, 4]
    assert db._cursors == [db.cursor]


@pytest.mark.parametrize("consume", [False, True])
def test_SetIteratorCloseReleasesCursorEvenBeforeFirstItem(bulkMapper, consume):
    mapper, db, _ = bulkMapper
    with db.transaction():
        mapper._bulkUpsertSerializedItems([serialized(1), serialized(2)])
    items = mapper.selectAll()
    assert len(db._cursors) == 2
    if consume:
        assert next(items)["scipionItemId"] == 1
    items.close()
    assert db._cursors == [db.cursor]
