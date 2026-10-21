"""The streaming monitor queries on PostgreSQL."""
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from app.backend.mapper.protocol_activity_mapper import LIVE_PROJECTS_SQL

from app.backend.mapper.streaming_monitor_mapper import (
    CLASSES_SQL, DEPENDENCIES_SQL, FIRST_ROW_SQL, GET_SETTINGS_SQL, INPUT_REFS_SQL, ITEMS_BY_IDS_SQL, LATEST_ROWS_SQL, MIC_COUNTS_SQL, OUTPUT_SETS_SQL, SAVE_SETTINGS_SQL, SERIES_ITEMS_SQL, SET_RATES_SQL,
)


@pytest.fixture
def connection(postgresqlMigratedEnv):
    env = postgresqlMigratedEnv
    engine = create_engine(URL.create(
        "postgresql+psycopg2", username=env["databaseUser"], password=env["databasePass"],
        host=env["postgresHost"], port=int(env["postgresPort"]), database=env["databaseName"]))
    schema = "streaming_monitor_test_" + uuid4().hex
    try:
        with engine.connect() as conn:
            try:
                conn.exec_driver_sql('CREATE SCHEMA "' + schema + '"')
                conn.exec_driver_sql('SET search_path TO "' + schema + '"')
                conn.exec_driver_sql('''CREATE TABLE protocols (id serial PRIMARY KEY, "projectId" int, "protocolId" text,
                    "protocolClassName" text, status text, params jsonb)''')
                conn.exec_driver_sql('''CREATE TABLE scipion_sets (id serial PRIMARY KEY, "projectId" int,
                    "protocolDbId" int, "outputName" text, "setClassName" text, "itemClassName" text,
                    properties jsonb, "updatedAt" timestamptz)''')
                conn.exec_driver_sql('''CREATE TABLE protocol_input_refs (id serial PRIMARY KEY, "projectId" int,
                    "protocolId" text, "parentProtocolId" text, "parentOutputName" text)''')
                conn.exec_driver_sql('''CREATE TABLE scipion_set_items (id serial PRIMARY KEY, "setId" int,
                    "scipionItemId" int, enabled boolean, label text, creation timestamptz,
                    "values" jsonb, "createdAt" timestamptz NOT NULL DEFAULT NOW())''')
                conn.exec_driver_sql('''CREATE TABLE protocol_dependencies (id serial PRIMARY KEY, "projectId" int,
                    "parentProtocolDbId" int, "childProtocolDbId" int)''')
                conn.exec_driver_sql('''CREATE TABLE scipion_set_tables (id serial PRIMARY KEY, "setId" int,
                    "parentItemId" int, "tableKind" text, properties jsonb)''')
                conn.exec_driver_sql('''CREATE TABLE project_monitor_settings ("projectId" int PRIMARY KEY,
                    settings jsonb NOT NULL DEFAULT '{}', "updatedBy" int,
                    "updatedAt" timestamptz NOT NULL DEFAULT NOW())''')
                yield conn
            finally:
                conn.rollback()
                conn.exec_driver_sql('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE')
                conn.commit()
    finally:
        engine.dispose()


def test_outputs_and_inputs_of_the_project(connection):
    now = datetime.now(timezone.utc)
    connection.exec_driver_sql('''INSERT INTO protocols (id, "projectId", "protocolId", "protocolClassName", status, params)
        VALUES (1, 7, '2', 'ProtMotionCorr', 'RUNNING', '{"runName": "motioncor"}'),
               (2, 7, '3', 'ProtCTFFind', 'running', '{}'),
               (3, 8, '9', 'ProtOther', 'running', '{}')''')
    connection.exec_driver_sql('''INSERT INTO scipion_sets (id, "projectId", "protocolDbId", "outputName", "setClassName",
        "itemClassName", properties, "updatedAt") VALUES
        (20, 7, 1, 'outputMicrographs', 'SetOfMicrographs', 'Micrograph', '{"itemsCount": 5}', %s),
        (30, 7, 2, 'outputCTF', 'SetOfCTF', 'CTFModel', '{"itemsCount": 4}', %s),
        (31, 7, 2, 'reserved', 'SetOfCTF', 'CTFModel', '{"runtimeReserved": true}', %s),
        (90, 8, 3, 'outputCTF', 'SetOfCTF', 'CTFModel', '{}', %s)''', (now, now, now, now))
    connection.exec_driver_sql('''INSERT INTO protocol_input_refs ("projectId", "protocolId", "parentProtocolId",
        "parentOutputName") VALUES (7, '3', '2', 'outputMicrographs'), (7, '2', NULL, NULL)''')

    outputs = connection.exec_driver_sql(OUTPUT_SETS_SQL, (7,)).mappings().all()
    refs = connection.exec_driver_sql(INPUT_REFS_SQL, (7,)).mappings().all()

    assert sorted((row["setId"], row["label"], row["status"]) for row in outputs) == [
        (20, "motioncor", "running"), (30, "ProtCTFFind", "running")]
    assert [dict(row) for row in refs] == [
        {"protocolId": "3", "parentProtocolId": "2", "parentOutputName": "outputMicrographs"}]


def test_rates_series_and_shifts_of_the_items(connection):
    now = datetime.now(timezone.utc)
    rows = [
        # setId, itemId, creation
        (30, 1, now - timedelta(minutes=25)),
        (30, 2, now - timedelta(minutes=15)),
        (30, 3, now - timedelta(minutes=5)),
        (30, 4, None),  # Without creation the row time counts
        (21, 3, now),
    ]
    for setId, itemId, creation in rows:
        values = {"_defocusU": 1000.0 * itemId} if setId == 30 else {"_alignment._xshifts": "0,1"}
        connection.exec_driver_sql('''INSERT INTO scipion_set_items ("setId", "scipionItemId", enabled, label, creation,
            "values") VALUES (%s, %s, TRUE, %s, %s, %s)''', (setId, itemId, "mic_%d" % itemId, creation,
                                                            json.dumps(values)))

    window = timedelta(minutes=10)
    rates = {row["setId"]: row for row in connection.exec_driver_sql(
        SET_RATES_SQL, (now - window, now - 2 * window, now - window, [30, 21], 10)).mappings().all()}
    sampled = connection.exec_driver_sql(
        SET_RATES_SQL, (now - window, now - 2 * window, now - window, [30], 2)).mappings().one()
    rowIds = {itemId: rowId for rowId, itemId in connection.exec_driver_sql(
        'SELECT id, "scipionItemId" FROM scipion_set_items WHERE "setId" = 30').all()}
    series = connection.exec_driver_sql(SERIES_ITEMS_SQL, (30, rowIds[1], 2)).mappings().all()
    first = connection.exec_driver_sql(FIRST_ROW_SQL, (30,)).mappings().one()
    shifts = connection.exec_driver_sql(ITEMS_BY_IDS_SQL, (21, [3, 4])).mappings().all()

    assert (rates[30]["lastWindow"], rates[30]["previousWindow"]) == (2, 1)
    assert rates[30]["oldest"] == now - timedelta(minutes=25) and rates[30]["sampled"] == 4
    # Only the newest items are looked at: items 4 (no creation, its row time) and 3
    assert sampled["sampled"] == 2 and sampled["lastWindow"] == 2
    assert [(row["scipionItemId"], row["values"]["_defocusU"]) for row in series] == [(2, 2000.0), (3, 3000.0)]
    assert [row["rowId"] for row in series] == [rowIds[2], rowIds[3]] and first["firstRowId"] == rowIds[1]
    latest = connection.exec_driver_sql(LATEST_ROWS_SQL, (30, 2)).mappings().all()
    assert [row["scipionItemId"] for row in latest] == [4, 3]
    assert [(row["scipionItemId"], row["values"]) for row in shifts] == [(3, {"_alignment._xshifts": "0,1"})]


def test_thresholds_are_kept_once_per_project(connection):
    for thresholds, userId in (({"maxResolution": 6.0}, 3), ({"maxAstigmatism": None}, 4)):
        connection.exec_driver_sql(SAVE_SETTINGS_SQL, (7, json.dumps({"thresholds": thresholds}), userId))

    row = connection.exec_driver_sql(GET_SETTINGS_SQL, (7,)).mappings().one()
    count = connection.exec_driver_sql("SELECT COUNT(*) FROM project_monitor_settings").scalar()

    assert row["settings"] == {"thresholds": {"maxAstigmatism": None}} and count == 1
    assert connection.exec_driver_sql(GET_SETTINGS_SQL, (8,)).first() is None


def test_projects_with_a_protocol_running(connection):
    connection.exec_driver_sql('''INSERT INTO protocols ("projectId", "protocolId", "protocolClassName", status, params)
        VALUES (7, '2', 'A', 'RUNNING', '{}'), (7, '3', 'B', 'running', '{}'), (8, '4', 'C', 'finished', '{}'),
               (9, '5', 'D', 'scheduled', '{}'), (10, '6', 'E', 'launched', '{}')''')

    rows = connection.exec_driver_sql(LIVE_PROJECTS_SQL, ([7, 8, 9], ["launched", "running", "scheduled"], 5)).all()

    assert [row[0] for row in rows] == [7, 9]


def test_items_are_counted_per_micrograph_after_a_row(connection):
    rows = [(40, {"_micId": 1, "_x": 10}), (40, {"_micId": 1, "_x": 20}), (40, {"_micId": 2, "_x": 5}),
            (50, {"_coordinate._micId": 2}), (40, {"_x": 7})]
    for setId, values in rows:
        connection.exec_driver_sql('''INSERT INTO scipion_set_items ("setId", "scipionItemId", enabled, "values")
            VALUES (%s, 1, TRUE, %s)''', (setId, json.dumps(values)))
    rowIds = [row[0] for row in connection.exec_driver_sql("SELECT id FROM scipion_set_items ORDER BY id").all()]

    counted = {row["mic"]: (row["n"], row["lastRowId"]) for row in connection.exec_driver_sql(
        MIC_COUNTS_SQL, (40, 0, 10)).mappings().all()}
    after = {row["mic"]: row["n"] for row in connection.exec_driver_sql(
        MIC_COUNTS_SQL, (40, rowIds[1], 10)).mappings().all()}
    particles = {row["mic"]: row["n"] for row in connection.exec_driver_sql(
        MIC_COUNTS_SQL, (50, 0, 10)).mappings().all()}
    chunk = sum(row["n"] for row in connection.exec_driver_sql(MIC_COUNTS_SQL, (40, 0, 2)).mappings().all())

    assert counted == {"1": (2, rowIds[1]), "2": (1, rowIds[2]), None: (1, rowIds[4])}
    assert after == {"2": 1, None: 1} and particles == {"2": 1} and chunk == 2


def test_classes_with_the_particles_of_each(connection):
    for classId, size in ((1, 40), (2, 7), (3, None)):
        values = {"_size": size} if size is not None else {}
        connection.exec_driver_sql('''INSERT INTO scipion_set_items ("setId", "scipionItemId", enabled, "values")
            VALUES (90, %s, TRUE, %s)''', (classId, json.dumps(values)))
    # The child table counter wins over _size; a class without one keeps its _size
    connection.exec_driver_sql('''INSERT INTO scipion_set_tables ("setId", "parentItemId", "tableKind", properties)
        VALUES (90, 1, 'child', '{"itemsCount": 45}'), (90, 1, 'root', '{"itemsCount": 999}'),
               (90, 3, 'child', '{"itemsCount": 2}')''')

    rows = {row["classId"]: row["particles"] for row in connection.exec_driver_sql(CLASSES_SQL, (90,)).mappings().all()}

    assert rows == {1: 45, 2: 7, 3: 2}


def test_protocol_dependencies_by_scipion_protocol_id(connection):
    connection.exec_driver_sql('''INSERT INTO protocols (id, "projectId", "protocolId", "protocolClassName", status, params)
        VALUES (1, 7, '4', 'A', 'finished', '{}'), (2, 7, '5', 'B', 'running', '{}'), (3, 8, '9', 'C', 'running', '{}')''')
    connection.exec_driver_sql('''INSERT INTO protocol_dependencies ("projectId", "parentProtocolDbId", "childProtocolDbId")
        VALUES (7, 1, 2), (8, 3, 3)''')

    rows = [dict(row) for row in connection.exec_driver_sql(DEPENDENCIES_SQL, (7,)).mappings().all()]

    assert rows == [{"parentProtocolId": "4", "protocolId": "5"}]
