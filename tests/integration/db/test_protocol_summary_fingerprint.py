"""The fingerprint of what a protocol's summary reads: it moves with every change the summary can show."""
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import URL

from app.backend.mapper.protocol_summary_mapper import PROTOCOL_SUMMARY_FINGERPRINT_SQL


@pytest.fixture
def connection(postgresqlMigratedEnv):
    env = postgresqlMigratedEnv
    engine = create_engine(URL.create(
        "postgresql+psycopg2", username=env["databaseUser"], password=env["databasePass"],
        host=env["postgresHost"], port=int(env["postgresPort"]), database=env["databaseName"]))
    schema = "summary_fingerprint_test_" + uuid4().hex
    try:
        with engine.connect() as conn:
            try:
                conn.exec_driver_sql('CREATE SCHEMA "' + schema + '"')
                conn.exec_driver_sql('SET search_path TO "' + schema + '"')
                conn.exec_driver_sql('''CREATE TABLE protocols (id serial PRIMARY KEY, "projectId" int,
                    "protocolId" text, status text, params json, "updatedAt" timestamptz DEFAULT NOW())''')
                conn.exec_driver_sql('''CREATE TABLE scipion_objects (id serial PRIMARY KEY, "projectId" int,
                    "protocolDbId" int, "parentObjectId" int, value text, "updatedAt" timestamptz DEFAULT NOW())''')
                conn.exec_driver_sql('''CREATE TABLE scipion_sets (id serial PRIMARY KEY, "projectId" int,
                    "protocolDbId" int, properties jsonb, "updatedAt" timestamptz DEFAULT NOW())''')
                conn.exec_driver_sql('''CREATE TABLE protocol_input_refs (id serial PRIMARY KEY, "projectId" int,
                    "protocolDbId" int, "inputName" text, "itemIndex" int, "parentProtocolDbId" int,
                    "parentOutputName" text)''')
                conn.exec_driver_sql('''INSERT INTO protocols (id, "projectId", "protocolId", status) VALUES
                    (1, 7, '2', 'finished'), (2, 7, '3', 'running'), (3, 7, '4', 'finished')''')
                conn.exec_driver_sql('''INSERT INTO scipion_sets (id, "projectId", "protocolDbId", properties) VALUES
                    (10, 7, 1, '{"itemsCount": 5}'), (20, 7, 2, '{"itemsCount": 3}'), (30, 7, 3, '{"itemsCount": 9}')''')
                conn.exec_driver_sql('''INSERT INTO scipion_objects (id, "projectId", "protocolDbId", value) VALUES
                    (100, 7, 2, NULL)''')
                conn.exec_driver_sql('''INSERT INTO protocol_input_refs ("projectId", "protocolDbId", "inputName",
                    "itemIndex", "parentProtocolDbId", "parentOutputName") VALUES (7, 2, 'inputMovies', 0, 1, 'outputMovies')''')
                yield conn
            finally:
                conn.rollback()
                conn.exec_driver_sql('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE')
                conn.commit()
    finally:
        engine.dispose()


def fingerprint(connection, protocolId="3"):
    row = connection.exec_driver_sql(PROTOCOL_SUMMARY_FINGERPRINT_SQL,
                                     {"projectId": 7, "protocolId": protocolId}).mappings().first()
    return row and row["fingerprint"]


@pytest.mark.parametrize("change", [
    'UPDATE protocols SET status = \'finished\' WHERE id = 2',
    'UPDATE protocols SET "updatedAt" = NOW() + INTERVAL \'1 minute\' WHERE id = 2',
    # Closing a stream changes the properties alone
    'UPDATE scipion_sets SET properties = properties || \'{"streamState": 2}\' WHERE id = 20',
    'INSERT INTO scipion_sets ("projectId", "protocolDbId", properties) VALUES (7, 2, \'{}\')',
    'UPDATE scipion_objects SET value = \'0.83\' WHERE id = 100',
    # A summary often counts its inputs: the parent's set growing changes it too
    'UPDATE scipion_sets SET properties = \'{"itemsCount": 6}\' WHERE id = 10',
    'UPDATE protocol_input_refs SET "parentOutputName" = \'outputMicrographs\'',
])
def test_the_fingerprint_moves_with_what_the_summary_reads(connection, change):
    before = fingerprint(connection)
    assert before

    connection.exec_driver_sql(change)

    assert fingerprint(connection) != before


def test_the_fingerprint_stays_while_nothing_it_reads_changes(connection):
    before = fingerprint(connection)
    # Another protocol, not a parent of this one
    connection.exec_driver_sql('UPDATE scipion_sets SET properties = \'{"itemsCount": 99}\' WHERE id = 30')
    connection.exec_driver_sql('UPDATE protocols SET status = \'failed\' WHERE id = 3')

    assert fingerprint(connection) == before
    assert fingerprint(connection, "99") is None
