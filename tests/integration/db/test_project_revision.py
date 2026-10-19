"""The project revision changes with what the graph shows, and only with that."""
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from app.backend.mapper.postgresql import PROJECT_REVISION_SQL


@pytest.fixture
def protocols(postgresqlMigratedEnv):
    env = postgresqlMigratedEnv
    engine = create_engine(URL.create(
        "postgresql+psycopg2", username=env["databaseUser"],
        password=env["databasePass"], host=env["postgresHost"],
        port=int(env["postgresPort"]), database=env["databaseName"],
    ))
    schema = "project_revision_test_" + uuid4().hex
    try:
        with engine.connect() as connection:
            try:
                connection.exec_driver_sql('CREATE SCHEMA "' + schema + '"')
                connection.exec_driver_sql('SET search_path TO "' + schema + '"')
                connection.exec_driver_sql('''CREATE TABLE protocols (
                    id serial PRIMARY KEY, "projectId" integer NOT NULL, "protocolId" text NOT NULL,
                    "protocolClassName" text NOT NULL, status text NOT NULL DEFAULT 'pending', params jsonb,
                    "parentIds" integer[] NOT NULL DEFAULT ARRAY[]::integer[],
                    "childIds" integer[] NOT NULL DEFAULT ARRAY[]::integer[],
                    "updatedAt" timestamptz)''')
                yield connection
            finally:
                connection.rollback()
                connection.exec_driver_sql('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE')
                connection.commit()
    finally:
        engine.dispose()


def _revision(connection, projectId=1):
    return dict(connection.exec_driver_sql(PROJECT_REVISION_SQL, (projectId,)).mappings().one())


def test_the_revision_follows_what_the_graph_shows(protocols):
    connection = protocols
    empty = _revision(connection)
    assert empty["protocols"] == 0
    connection.exec_driver_sql('''INSERT INTO protocols ("projectId", "protocolId", "protocolClassName", status, params)
        VALUES (1, '2', 'ProtImport', 'finished', '{"runName": "import"}'),
               (1, '5', 'ProtCtf', 'saved', '{"runName": "ctf"}'),
               (2, '9', 'ProtOther', 'saved', NULL)''')
    first = _revision(connection)
    assert first["protocols"] == 2 and first["revision"] != empty["revision"]

    # Progress of a running protocol and other projects do not change it.
    connection.exec_driver_sql('''UPDATE protocols SET "updatedAt" = NOW(), params = params || '{"other": 1}' WHERE "protocolId" = '2' ''')
    connection.exec_driver_sql('''UPDATE protocols SET status = 'running' WHERE "projectId" = 2''')
    assert _revision(connection) == first

    changes = [
        '''UPDATE protocols SET status = 'launched' WHERE "protocolId" = '5' ''',
        '''UPDATE protocols SET params = '{"runName": "ctf again"}' WHERE "protocolId" = '5' ''',
        '''UPDATE protocols SET "parentIds" = ARRAY[1] WHERE "protocolId" = '5' ''',
        '''INSERT INTO protocols ("projectId", "protocolId", "protocolClassName") VALUES (1, '7', 'ProtNew')''',
        '''DELETE FROM protocols WHERE "protocolId" = '2' ''',
    ]
    seen = {first["revision"]}
    for change in changes:
        connection.exec_driver_sql(change)
        revision = _revision(connection)["revision"]
        assert revision not in seen
        seen.add(revision)
