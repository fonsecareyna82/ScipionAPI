"""Staged COPY writes store exactly what bound VALUES parameters store."""
import json
from datetime import date, datetime, timezone

import pytest

from app.backend.mapper.postgresql import canStageCopyRows

COLUMNS = ('"setId" integer, "scipionItemId" integer, enabled boolean, label text, '
           'comment text, creation timestamptz, "values" jsonb')
TRICKY_TEXT = 'tab\there "quoted" back\\slash \\N é\nline\r\\t'


def _rows():
    values = {"_text": TRICKY_TEXT, "_escape": "a\\nb", "_unicode": "π ☃", "_float": 1e-200,
              "_none": None, "_nested": {"k": [1, True, None]}}
    return [
        (1, 1, True, TRICKY_TEXT, None, None, json.dumps(values)),
        (1, 2, False, "", "", datetime(2026, 1, 2, 3, 4, 5, 6), json.dumps({})),
        (1, 3, True, None, "\\N", datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc), "{}"),
        (1, 4, True, "\\", "\t", date(2026, 5, 6), json.dumps(values, separators=(",", ":"))),
    ]


@pytest.fixture
def stagedTables(postgresqlIntegrationDb):
    db = postgresqlIntegrationDb
    for name in ("staged_target_values", "staged_target_copy"):
        db.execute("DROP TABLE IF EXISTS %s" % name)
        db.execute("CREATE TABLE %s (%s)" % (name, COLUMNS))
    try:
        yield db
    finally:
        for name in ("staged_target_values", "staged_target_copy"):
            db.execute("DROP TABLE IF EXISTS %s" % name)


def _stored(db, table):
    return db.fetchAll('SELECT "setId", "scipionItemId", enabled, label, comment, creation, "values" '
                       'FROM %s ORDER BY "scipionItemId"' % table)


def test_StagedRowsMatchBoundValuesExactly(stagedTables):
    db = stagedTables
    rows = _rows()
    assert canStageCopyRows(rows)
    db.executeValues("INSERT INTO staged_target_values VALUES %s", rows,
                     template="(%s, %s, %s, %s, %s, %s, %s::jsonb)")
    with db.transaction():
        db.executeFromStagedRows("INSERT INTO staged_target_copy SELECT * FROM staged_rows_test",
                                 rows, stageTable="staged_rows_test", stageColumns=COLUMNS, commit=False)
        # A second batch in the same transaction only sees its own rows.
        db.executeFromStagedRows("INSERT INTO staged_target_copy SELECT * FROM staged_rows_test",
                                 [(1, 5, True, "x", None, None, "{}")], stageTable="staged_rows_test",
                                 stageColumns=COLUMNS, commit=False)
    stored = _stored(db, "staged_target_copy")
    assert [dict(row) for row in stored[:4]] == [dict(row) for row in _stored(db, "staged_target_values")]
    assert [row["scipionItemId"] for row in stored] == [1, 2, 3, 4, 5]


def test_StagedWriteFailureRollsBackItsTransaction(stagedTables):
    db = stagedTables
    with pytest.raises(Exception):
        with db.transaction():
            db.executeFromStagedRows("INSERT INTO staged_target_copy SELECT * FROM staged_rows_test",
                                     _rows(), stageTable="staged_rows_test", stageColumns=COLUMNS, commit=False)
            db.execute("SELECT * FROM missing_relation_for_rollback", commit=False)
    assert _stored(db, "staged_target_copy") == []


def test_OnlyExactlyEncodableRowsAreStaged():
    assert canStageCopyRows([(1, True, None, "text", datetime(2026, 1, 1), date(2026, 1, 1))])
    assert not canStageCopyRows([(1.5,)])
    assert not canStageCopyRows([("nul\x00",)])
    assert not canStageCopyRows([(object(),)])
