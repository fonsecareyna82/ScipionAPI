"""The protocol activity query on PostgreSQL: runs that ended, by the end of their last step."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from app.backend.api.services.workspace_service import ENDED_STATUSES
from app.backend.mapper.protocol_activity_mapper import PROTOCOL_ACTIVITY_SQL


@pytest.fixture
def connection(postgresqlMigratedEnv):
    env = postgresqlMigratedEnv
    engine = create_engine(URL.create(
        "postgresql+psycopg2", username=env["databaseUser"], password=env["databasePass"],
        host=env["postgresHost"], port=int(env["postgresPort"]), database=env["databaseName"]))
    schema = "workspace_activity_test_" + uuid4().hex
    try:
        with engine.connect() as conn:
            try:
                conn.exec_driver_sql('CREATE SCHEMA "' + schema + '"')
                conn.exec_driver_sql('SET search_path TO "' + schema + '"')
                conn.exec_driver_sql('CREATE TABLE projects (id serial PRIMARY KEY, name text)')
                conn.exec_driver_sql('''CREATE TABLE protocols (id serial PRIMARY KEY, "projectId" int, "protocolId" text,
                    "protocolClassName" text, status text, params jsonb, "updatedAt" timestamptz)''')
                conn.exec_driver_sql('CREATE TABLE protocol_steps (id serial PRIMARY KEY, "protocolDbId" int, "endTime" timestamptz)')
                yield conn
            finally:
                conn.rollback()
                conn.exec_driver_sql('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE')
                conn.commit()
    finally:
        engine.dispose()


def test_ended_runs_come_from_their_last_step(connection):
    now = datetime.now(timezone.utc)
    connection.exec_driver_sql("INSERT INTO projects (id, name) VALUES (7, '/p/A')")
    connection.exec_driver_sql('''INSERT INTO protocols (id, "projectId", "protocolId", "protocolClassName", status, params, "updatedAt") VALUES
        (1, 7, '4', 'ProtA', 'finished', '{"runName": "ctf"}', %s),
        (2, 7, '5', 'ProtB', 'finished', '{}', %s),
        (3, 7, '6', 'ProtC', 'running', '{}', %s)''', (now, now, now))
    # Protocol 4 ended long ago and was only edited now; protocol 5 ended now.
    connection.exec_driver_sql('INSERT INTO protocol_steps ("protocolDbId", "endTime") VALUES (1, %s), (2, %s)',
                               (now - timedelta(hours=2), now))
    rows = connection.exec_driver_sql(PROTOCOL_ACTIVITY_SQL, ([7], list(ENDED_STATUSES), now - timedelta(minutes=1), 50)).mappings().all()
    assert [(row["protocolId"], row["label"]) for row in rows] == [("5", "ProtB")]
