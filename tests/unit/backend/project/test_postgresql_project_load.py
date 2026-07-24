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
from datetime import datetime


class FakeFlatMapper:
    def __init__(self):
        self.db = object()

    def getProjectRuntimeMetadata(self, projectId):
        assert projectId == 7

        return {
            "id": projectId,
            "createdAt": datetime(2026, 7, 24, 12, 30, 0),
        }


def test_PostgresqlProjectLoadsWithoutProjectSqlite(
        authTestEnv,
        tmp_path,
        monkeypatch,
):
    module = importlib.import_module(
        "app.backend.project.postgresql_project"
    )

    project = module.PostgresqlProject(
        domain=object(),
        path=str(tmp_path),
        projectId=7,
        flatMapper=FakeFlatMapper(),
        enableWriteFallback=False,
    )

    monkeypatch.setattr(
        project,
        "_loadHosts",
        lambda hostsConf: None,
    )

    sqlitePath = tmp_path / "project.sqlite"

    assert not sqlitePath.exists()

    project.load(
        chdir=False,
        loadAllConfig=False,
    )

    assert project.usingPostgresqlRuntimeMapper()
    assert project.mapper.writeFallbackMapper is None
    assert project.getCreationTime() == datetime(
        2026,
        7,
        24,
        12,
        30,
        0,
    )

    assert not sqlitePath.exists()

    project.closeMapper()


def test_PostgresqlProjectKeepsExistingOptionalSqliteMirror(
        authTestEnv,
        tmp_path,
        monkeypatch,
):
    module = importlib.import_module(
        "app.backend.project.postgresql_project"
    )

    class FakeFallbackMapper:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    fallbackMapper = FakeFallbackMapper()
    sqlitePath = tmp_path / "project.sqlite"
    sqlitePath.touch()

    project = module.PostgresqlProject(
        domain=object(),
        path=str(tmp_path),
        projectId=7,
        flatMapper=FakeFlatMapper(),
        enableWriteFallback=True,
    )

    monkeypatch.setattr(
        project,
        "_createFallbackMapper",
        lambda **kwargs: fallbackMapper,
    )

    project._loadDb()

    assert project.usingPostgresqlRuntimeMapper()
    assert project.mapper.writeFallbackMapper is fallbackMapper

    project.closeMapper()

    assert fallbackMapper.closed is True