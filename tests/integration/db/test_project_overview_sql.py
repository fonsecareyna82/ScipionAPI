"""The project overview and launch history queries on PostgreSQL."""
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from app.backend.api.services.project_overview import PROJECT_RUNS_SQL
from app.backend.api.services.protocol_history import INSERT_LAUNCH_SQL, LIST_LAUNCHES_SQL


@pytest.fixture
def connection(postgresqlMigratedEnv):
    env = postgresqlMigratedEnv
    engine = create_engine(URL.create(
        "postgresql+psycopg2", username=env["databaseUser"], password=env["databasePass"],
        host=env["postgresHost"], port=int(env["postgresPort"]), database=env["databaseName"]))
    schema = "project_overview_test_" + uuid4().hex
    try:
        with engine.connect() as conn:
            try:
                conn.exec_driver_sql('CREATE SCHEMA "' + schema + '"')
                conn.exec_driver_sql('SET search_path TO "' + schema + '"')
                conn.exec_driver_sql('''CREATE TABLE protocols (id serial PRIMARY KEY, "projectId" int, "protocolId" text,
                    "protocolClassName" text, status text, params jsonb, "updatedAt" timestamptz)''')
                conn.exec_driver_sql('''CREATE TABLE protocol_steps (id serial PRIMARY KEY, "protocolDbId" int, status text,
                    "initTime" timestamptz, "endTime" timestamptz)''')
                conn.exec_driver_sql('''CREATE TABLE users (id serial PRIMARY KEY, email text, "firstName" text, "lastName" text)''')
                conn.exec_driver_sql('''CREATE TABLE protocol_launches (id serial PRIMARY KEY, "projectId" int, "protocolDbId" int,
                    "protocolId" text, "userId" int, mode text, params jsonb NOT NULL DEFAULT '{}',
                    "launchedAt" timestamptz NOT NULL DEFAULT NOW())''')
                yield conn
            finally:
                conn.rollback()
                conn.exec_driver_sql('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE')
                conn.commit()
    finally:
        engine.dispose()


def test_run_times_come_from_the_steps(connection):
    now = datetime.now(timezone.utc)
    connection.exec_driver_sql('''INSERT INTO protocols (id, "projectId", "protocolId", "protocolClassName", status, params, "updatedAt") VALUES
        (1, 7, '4', 'ProtA', 'finished', '{"runName": "ctf"}', %s),
        (2, 7, 'PROJECT', 'Project', 'finished', '{}', %s),
        (3, 8, '4', 'ProtA', 'finished', '{}', %s)''', (now, now, now))
    connection.exec_driver_sql('''INSERT INTO protocol_steps ("protocolDbId", status, "initTime", "endTime") VALUES
        (1, 'finished', %s, %s), (1, 'failed', %s, %s)''',
                               (now - timedelta(hours=2), now - timedelta(hours=1), now - timedelta(hours=1), now))
    rows = connection.exec_driver_sql(PROJECT_RUNS_SQL, (7,)).mappings().all()
    assert len(rows) == 1
    row = rows[0]
    assert (row["label"], row["stepCount"], row["stepsDone"]) == ("ctf", 2, 1)
    assert row["endedAt"] - row["startedAt"] == timedelta(hours=2)


def test_launches_are_kept_and_listed_newest_first(connection):
    connection.exec_driver_sql("INSERT INTO users (id, email, \"firstName\") VALUES (3, 'ana@example.org', 'Ana')")
    for params, mode in (({"resolution": 5}, "launch"), ({"resolution": 4}, "restart")):
        connection.exec_driver_sql(INSERT_LAUNCH_SQL, (7, 1, "4", 3, mode, json.dumps(params)))
    rows = connection.exec_driver_sql(LIST_LAUNCHES_SQL, (7, "4", 50)).mappings().all()
    assert [(row["mode"], row["params"], row["firstName"]) for row in rows] == [
        ("restart", {"resolution": 4}, "Ana"), ("launch", {"resolution": 5}, "Ana")]
