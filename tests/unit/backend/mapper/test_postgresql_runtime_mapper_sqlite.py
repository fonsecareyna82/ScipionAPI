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
import importlib
import sqlite3

import pytest


class FakeProject:
    def __init__(self, projectPath, sqlitePath):
        self.path = str(projectPath)
        self.sqlitePath = str(sqlitePath)

    def getPath(self):
        return self.path

    def getDbPath(self):
        return self.sqlitePath


@pytest.fixture
def postgresqlRuntimeMapperModule(authTestEnv):
    return importlib.import_module(
        "app.backend.mapper.postgresql_runtime_mapper"
    )


def _makeRuntimeMapper(
        postgresqlRuntimeMapperModule,
        projectPath,
        sqlitePath,
):
    runtimeMapper = object.__new__(
        postgresqlRuntimeMapperModule.PostgresqlRuntimeMapper
    )

    runtimeMapper.project = FakeProject(
        projectPath=projectPath,
        sqlitePath=sqlitePath,
    )

    return runtimeMapper


def test_ExistsInProjectSqliteUsesReadOnlyUri(
        postgresqlRuntimeMapperModule,
        monkeypatch,
        tmp_path,
):
    sqlitePath = tmp_path / "legacy project.sqlite"

    with sqlite3.connect(str(sqlitePath)) as connection:
        connection.execute(
            "CREATE TABLE Objects (id INTEGER PRIMARY KEY)"
        )
        connection.execute(
            "INSERT INTO Objects (id) VALUES (?)",
            (17,),
        )

    runtimeMapper = _makeRuntimeMapper(
        postgresqlRuntimeMapperModule=postgresqlRuntimeMapperModule,
        projectPath=tmp_path,
        sqlitePath=sqlitePath,
    )

    realConnect = (
        postgresqlRuntimeMapperModule
        .sqlite3
        .connect
    )

    connectCalls = []

    def captureConnect(database, *args, **kwargs):
        connectCalls.append({
            "database": database,
            "args": args,
            "kwargs": dict(kwargs),
        })

        return realConnect(
            database,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        postgresqlRuntimeMapperModule.sqlite3,
        "connect",
        captureConnect,
    )

    assert runtimeMapper._existsInProjectSqlite(17) is True

    assert connectCalls == [{
        "database": (
            f"{sqlitePath.resolve().as_uri()}"
            "?mode=ro"
        ),
        "args": (),
        "kwargs": {
            "uri": True,
            "timeout": 5.0,
        },
    }]


def test_ExistsInProjectSqliteDoesNotCreateMissingDatabase(
        postgresqlRuntimeMapperModule,
        monkeypatch,
        tmp_path,
):
    sqlitePath = tmp_path / "missing-project.sqlite"

    runtimeMapper = _makeRuntimeMapper(
        postgresqlRuntimeMapperModule=postgresqlRuntimeMapperModule,
        projectPath=tmp_path,
        sqlitePath=sqlitePath,
    )

    monkeypatch.setattr(
        postgresqlRuntimeMapperModule.os.path,
        "isfile",
        lambda path: True,
    )

    with pytest.raises(
            RuntimeError,
            match="Could not verify protocol id 99",
    ):
        runtimeMapper._existsInProjectSqlite(99)

    assert sqlitePath.exists() is False