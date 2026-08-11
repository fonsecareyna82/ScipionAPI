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
import threading

import pytest

from app.backend.mapper import postgresql as postgresqlModule
from app.backend.mapper.postgresql import PostgresqlDb


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.closed = False
        self._row = None
        self.executeError = None
        self.fetchallError = None

    def execute(self, query, params=None):
        if self.closed:
            raise RuntimeError("Cursor is closed")

        if self.executeError is not None:
            raise self.executeError

        self._row = {
            "query": query,
            "connectionId": id(self.connection),
            "cursorId": id(self),
        }

        if str(query).startswith("thread-"):
            self.connection.barrier.wait(timeout=5)

    def fetchone(self):
        return dict(self._row)

    def fetchall(self):
        if self.fetchallError is not None:
            raise self.fetchallError

        return [dict(self._row)]

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, barrier):
        self.barrier = barrier
        self.closed = False
        self.cursors = []
        self.commits = 0
        self.rollbacks = 0
        self.commitError = None

    def cursor(self, cursor_factory=None):
        cursor = FakeCursor(self)
        self.cursors.append(cursor)

        return cursor

    def commit(self):
        self.commits += 1

        if self.commitError is not None:
            raise self.commitError

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class FakeConnectionFactory:
    def __init__(self, barrier):
        self.barrier = barrier
        self.connections = []
        self.lock = threading.Lock()

    def __call__(self, **kwargs):
        connection = FakeConnection(self.barrier)

        with self.lock:
            self.connections.append(connection)

        return connection


def test_PostgresqlDbUsesIndependentResourcesPerThread(monkeypatch):
    barrier = threading.Barrier(2)
    connectionFactory = FakeConnectionFactory(barrier)

    monkeypatch.setattr(
        postgresqlModule.psycopg2,
        "connect",
        connectionFactory,
    )

    db = PostgresqlDb(
        dbName="scipion",
        user="scipion",
        password="secret",
    )

    results = {}
    errors = []

    def fetchRow(query):
        try:
            results[query] = db.fetchOne(query)

        except Exception as error:
            errors.append(error)

    firstThread = threading.Thread(
        target=fetchRow,
        args=("thread-first",),
    )

    secondThread = threading.Thread(
        target=fetchRow,
        args=("thread-second",),
    )

    firstThread.start()
    secondThread.start()

    firstThread.join(timeout=10)
    secondThread.join(timeout=10)

    assert not firstThread.is_alive()
    assert not secondThread.is_alive()
    assert errors == []

    assert results["thread-first"]["query"] == "thread-first"
    assert results["thread-second"]["query"] == "thread-second"

    assert (
        results["thread-first"]["connectionId"]
        != results["thread-second"]["connectionId"]
    )

    assert (
        results["thread-first"]["cursorId"]
        != results["thread-second"]["cursorId"]
    )

    # Main thread plus the two worker threads.
    assert len(connectionFactory.connections) == 3

    db.close()

    assert all(
        connection.closed
        for connection in connectionFactory.connections
    )


def test_PostgresqlDbReleasesTransientThreadResources(monkeypatch):
    barrier = threading.Barrier(1)
    connectionFactory = FakeConnectionFactory(barrier)

    monkeypatch.setattr(
        postgresqlModule.psycopg2,
        "connect",
        connectionFactory,
    )

    db = PostgresqlDb(
        dbName="scipion",
        user="scipion",
        password="secret",
    )

    mainConnection = connectionFactory.connections[0]

    try:
        errors = []

        def runTransientQuery(index):
            try:
                db.fetchOne(
                    "worker-%s" % index
                )

            except Exception as error:
                errors.append(error)

            finally:
                db.closeCurrentThreadResources()

        for index in range(25):
            thread = threading.Thread(
                target=runTransientQuery,
                args=(index,),
            )

            thread.start()
            thread.join(timeout=5)

            assert not thread.is_alive()

        assert errors == []

        # Main thread connection remains available.
        assert mainConnection.closed is False

        # Twenty-five transient threads opened connections,
        # but all of them were released immediately.
        assert len(connectionFactory.connections) == 26

        assert all(
            connection.closed
            for connection in connectionFactory.connections[1:]
        )

        # PostgresqlDb no longer retains dead-thread resources.
        assert db._connections == [
            mainConnection,
        ]

        assert len(db._cursors) == 1

        # The main thread continues using its original connection.
        assert db.conn is mainConnection

    finally:
        db.close()

    assert mainConnection.closed is True


def test_PostgresqlDbExecuteRollsBackWhenStatementFails(monkeypatch):
    barrier = threading.Barrier(1)
    connectionFactory = FakeConnectionFactory(barrier)

    monkeypatch.setattr(
        postgresqlModule.psycopg2,
        "connect",
        connectionFactory,
    )

    db = PostgresqlDb(
        dbName="scipion",
        user="scipion",
        password="secret",
    )

    connection = connectionFactory.connections[0]
    cursor = connection.cursors[0]
    cursor.executeError = RuntimeError("statement failed")

    try:
        with pytest.raises(
                RuntimeError,
                match="statement failed",
        ):
            db.execute("BROKEN SQL")

        assert connection.commits == 0
        assert connection.rollbacks == 1

    finally:
        db.close()


def test_PostgresqlDbExecuteRollsBackWhenCommitFails(monkeypatch):
    barrier = threading.Barrier(1)
    connectionFactory = FakeConnectionFactory(barrier)

    monkeypatch.setattr(
        postgresqlModule.psycopg2,
        "connect",
        connectionFactory,
    )

    db = PostgresqlDb(
        dbName="scipion",
        user="scipion",
        password="secret",
    )

    connection = connectionFactory.connections[0]
    connection.commitError = RuntimeError("commit failed")

    try:
        with pytest.raises(
                RuntimeError,
                match="commit failed",
        ):
            db.execute(
                "UPDATE example SET value = 1"
            )

        assert connection.commits == 1
        assert connection.rollbacks == 1

    finally:
        db.close()


def test_PostgresqlDbFetchOneRollsBackWhenStatementFails(monkeypatch):
    barrier = threading.Barrier(1)
    connectionFactory = FakeConnectionFactory(barrier)

    monkeypatch.setattr(
        postgresqlModule.psycopg2,
        "connect",
        connectionFactory,
    )

    db = PostgresqlDb(
        dbName="scipion",
        user="scipion",
        password="secret",
    )

    connection = connectionFactory.connections[0]
    cursor = connection.cursors[0]
    cursor.executeError = RuntimeError("statement failed")

    try:
        with pytest.raises(
                RuntimeError,
                match="statement failed",
        ):
            db.fetchOne("BROKEN SELECT")

        assert connection.commits == 0
        assert connection.rollbacks == 1

    finally:
        db.close()


def test_PostgresqlDbFetchAllRollsBackWhenFetchFails(monkeypatch):
    barrier = threading.Barrier(1)
    connectionFactory = FakeConnectionFactory(barrier)

    monkeypatch.setattr(
        postgresqlModule.psycopg2,
        "connect",
        connectionFactory,
    )

    db = PostgresqlDb(
        dbName="scipion",
        user="scipion",
        password="secret",
    )

    connection = connectionFactory.connections[0]
    cursor = connection.cursors[0]
    cursor.fetchallError = RuntimeError("fetch failed")

    try:
        with pytest.raises(
                RuntimeError,
                match="fetch failed",
        ):
            db.fetchAll("SELECT * FROM example")

        assert connection.commits == 0
        assert connection.rollbacks == 1

    finally:
        db.close()


def test_PostgresqlDbNestedTransactionsCommitOnlyAtOutermostScope(
        monkeypatch,
):
    barrier = threading.Barrier(1)
    connectionFactory = FakeConnectionFactory(barrier)

    monkeypatch.setattr(
        postgresqlModule.psycopg2,
        "connect",
        connectionFactory,
    )

    db = PostgresqlDb(
        dbName="scipion",
        user="scipion",
        password="secret",
    )

    connection = connectionFactory.connections[0]

    try:
        with db.transaction():
            db.execute(
                "UPDATE first_example SET value = 1",
                commit=False,
            )

            with db.transaction():
                db.execute(
                    "UPDATE second_example SET value = 2",
                    commit=False,
                )

            assert connection.commits == 0
            assert connection.rollbacks == 0

        assert connection.commits == 1
        assert connection.rollbacks == 0

    finally:
        db.close()


def test_PostgresqlDbNestedTransactionFailureRollsBackOutermostScope(
        monkeypatch,
):
    barrier = threading.Barrier(1)
    connectionFactory = FakeConnectionFactory(barrier)

    monkeypatch.setattr(
        postgresqlModule.psycopg2,
        "connect",
        connectionFactory,
    )

    db = PostgresqlDb(
        dbName="scipion",
        user="scipion",
        password="secret",
    )

    connection = connectionFactory.connections[0]

    try:
        with pytest.raises(
                RuntimeError,
                match="nested transaction failed",
        ):
            with db.transaction():
                db.execute(
                    "UPDATE first_example SET value = 1",
                    commit=False,
                )

                with db.transaction():
                    raise RuntimeError(
                        "nested transaction failed"
                    )

        assert connection.commits == 0
        assert connection.rollbacks == 1

        with db.transaction():
            db.execute(
                "UPDATE recovery_example SET value = 3",
                commit=False,
            )

        assert connection.commits == 1
        assert connection.rollbacks == 1

    finally:
        db.close()


def test_PostgresqlDbExecuteDefersDefaultCommitInsideTransaction(
        monkeypatch,
):
    barrier = threading.Barrier(1)
    connectionFactory = FakeConnectionFactory(barrier)

    monkeypatch.setattr(
        postgresqlModule.psycopg2,
        "connect",
        connectionFactory,
    )

    db = PostgresqlDb(
        dbName="scipion",
        user="scipion",
        password="secret",
    )

    connection = connectionFactory.connections[0]

    try:
        with db.transaction():
            db.execute(
                "UPDATE example SET value = 1"
            )

            assert connection.commits == 0
            assert connection.rollbacks == 0

        assert connection.commits == 1
        assert connection.rollbacks == 0

    finally:
        db.close()


def test_PostgresqlDbExecuteReturningOneDefersCommitInsideTransaction(
        monkeypatch,
):
    barrier = threading.Barrier(1)
    connectionFactory = FakeConnectionFactory(barrier)

    monkeypatch.setattr(
        postgresqlModule.psycopg2,
        "connect",
        connectionFactory,
    )

    db = PostgresqlDb(
        dbName="scipion",
        user="scipion",
        password="secret",
    )

    connection = connectionFactory.connections[0]

    try:
        with db.transaction():
            row = db.executeReturningOne(
                "INSERT INTO example VALUES (1) RETURNING id"
            )

            assert row is not None
            assert connection.commits == 0
            assert connection.rollbacks == 0

        assert connection.commits == 1
        assert connection.rollbacks == 0

    finally:
        db.close()


def test_PostgresqlDbExecuteFailureInsideTransactionRollsBackOnlyAtBoundary(
        monkeypatch,
):
    barrier = threading.Barrier(1)
    connectionFactory = FakeConnectionFactory(barrier)

    monkeypatch.setattr(
        postgresqlModule.psycopg2,
        "connect",
        connectionFactory,
    )

    db = PostgresqlDb(
        dbName="scipion",
        user="scipion",
        password="secret",
    )

    connection = connectionFactory.connections[0]
    cursor = connection.cursors[0]
    cursor.executeError = RuntimeError("statement failed")

    try:
        with pytest.raises(
                RuntimeError,
                match="statement failed",
        ):
            with db.transaction():
                db.execute(
                    "BROKEN SQL"
                )

        assert connection.commits == 0
        assert connection.rollbacks == 1

    finally:
        db.close()




