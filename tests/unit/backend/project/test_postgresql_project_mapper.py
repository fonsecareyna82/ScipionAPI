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
import inspect

import app.backend.project.postgresql_project as projectModule

from app.backend.project.postgresql_project import (
    PostgresqlProject,
)


class FakeRuntimeMapper:
    def __init__(self, **kwargs):
        self.kwargs = dict(kwargs)
        self.closeCalls = 0

    def close(self):
        self.closeCalls += 1


def buildProject(
        tmpPath,
):
    project = object.__new__(
        PostgresqlProject
    )

    project.path = str(
        tmpPath
    )

    project.postgresqlProjectId = 7
    project.postgresqlFlatMapper = object()

    project.mapper = None
    project._postgresqlRuntimeMapper = None

    return project


def test_ConstructorDoesNotExposeReadFallback():
    parameters = inspect.signature(
        PostgresqlProject.__init__
    ).parameters

    assert "enableReadFallback" not in parameters


def test_CreateMapperAlwaysUsesPostgresqlRuntime(
        monkeypatch,
        tmp_path,
):
    project = buildProject(
        tmpPath=tmp_path,
    )

    createdRuntimeMappers = []

    def buildRuntimeMapper(**kwargs):
        runtimeMapper = FakeRuntimeMapper(
            **kwargs
        )

        createdRuntimeMappers.append(
            runtimeMapper
        )

        return runtimeMapper

    def failSqliteMapper(*args, **kwargs):
        raise AssertionError(
            "PostgresqlProject must not create SQLite mappers"
        )

    monkeypatch.setattr(
        projectModule,
        "PostgresqlRuntimeMapper",
        buildRuntimeMapper,
    )

    monkeypatch.setattr(
        projectModule.ScipionProject,
        "createMapper",
        failSqliteMapper,
    )

    runtimeMapper = project.createMapper(
        tmp_path / "logs" / "run.db"
    )

    assert len(createdRuntimeMappers) == 1

    assert runtimeMapper.kwargs == {
        "flatMapper": project.postgresqlFlatMapper,
        "projectId": 7,
        "project": project,
    }

    assert project._postgresqlRuntimeMapper is (
        runtimeMapper
    )

    assert not hasattr(
        project,
        "_normalizeSqlitePath",
    )


def test_LoadDbIgnoresLegacyRuntimeDatabasePath(
        monkeypatch,
        tmp_path,
):
    project = buildProject(
        tmpPath=tmp_path,
    )

    runtimeMapper = FakeRuntimeMapper()
    createMapperCalls = []

    def createMapper(sqliteFn):
        createMapperCalls.append(
            sqliteFn
        )
        return runtimeMapper

    monkeypatch.setattr(
        project,
        "createMapper",
        createMapper,
    )

    project._loadDb(
        tmp_path / "logs" / "run.db"
    )

    assert createMapperCalls == [
        None,
    ]
    assert project.mapper is runtimeMapper


def test_CloseMapperClosesRuntimeMapper(
        tmp_path,
):
    project = buildProject(
        tmpPath=tmp_path,
    )

    runtimeMapper = FakeRuntimeMapper()

    project.mapper = runtimeMapper
    project._postgresqlRuntimeMapper = (
        runtimeMapper
    )

    project.closeMapper()

    assert runtimeMapper.closeCalls == 1

    assert project.mapper is None

    assert (
        project._postgresqlRuntimeMapper
        is None
    )

