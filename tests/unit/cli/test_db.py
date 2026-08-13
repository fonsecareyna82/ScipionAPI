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
import pytest

import scipionapi_cli.db as dbModule


def _baseEnv():
    return {
        "DATABASE_NAME": "scipion_db",
        "DATABASE_USER": "scipion_user",
        "DATABASE_PASS": "secret",
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
    }


def test_EnsureDatabaseAndRoleRejectsUnmanagedExistingResources(
    monkeypatch,
):
    env = _baseEnv()

    monkeypatch.setattr(
        dbModule,
        "_resolveAdminConnection",
        lambda _env: (
            ["psql"],
            {},
        ),
    )

    def fakeScalar(
        _psqlBase,
        _commandEnv,
        sql,
        _timeout,
    ):
        if "pg_database" in sql:
            return "1"

        if "pg_roles" in sql:
            return "1"

        return ""

    monkeypatch.setattr(
        dbModule,
        "_runPsqlScalar",
        fakeScalar,
    )

    executedSql = []

    monkeypatch.setattr(
        dbModule,
        "_runPsqlExec",
        lambda _base, _env, sql, _timeout:
            executedSql.append(sql),
    )

    with pytest.raises(
        RuntimeError,
        match="bootstrap stopped for safety",
    ):
        dbModule.ensureDatabaseAndRole(env)

    assert executedSql == []


def test_EnsureDatabaseAndRoleAllowsManagedExistingResources(
    monkeypatch,
):
    env = _baseEnv()
    env[
        "SCIPIONAPI_MANAGED_DATABASE"
    ] = "1"

    monkeypatch.setattr(
        dbModule,
        "_resolveAdminConnection",
        lambda _env: (
            ["psql"],
            {},
        ),
    )

    monkeypatch.setattr(
        dbModule,
        "_runPsqlScalar",
        lambda *_args: "1",
    )

    executedSql = []

    monkeypatch.setattr(
        dbModule,
        "_runPsqlExec",
        lambda _base, _env, sql, _timeout:
            executedSql.append(sql),
    )

    dbModule.ensureDatabaseAndRole(env)

    assert any(
        "ALTER ROLE scipion_user"
        in sql
        for sql in executedSql
    )

    assert any(
        "ALTER DATABASE scipion_db"
        in sql
        for sql in executedSql
    )


