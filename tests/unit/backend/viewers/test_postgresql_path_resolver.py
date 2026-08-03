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
from pathlib import Path

from app.backend.viewers.postgresql_path_resolver import PostgresqlProjectPathResolver


def test_PostgresqlProjectPathResolverResolvesProjectRelativePath(tmp_path):
    projectPath = tmp_path / "project"
    filePath = projectPath / "Runs" / "000001_Test" / "extra" / "volume.mrc"
    filePath.parent.mkdir(parents=True)
    filePath.write_bytes(b"fake")

    class FakeDb:
        def fetchOne(self, query, params):
            return {"name": str(projectPath)}

    resolver = PostgresqlProjectPathResolver(
        db=FakeDb(),
        projectId=1,
    )

    assert resolver.resolveExistingPath(
        "Runs/000001_Test/extra/volume.mrc"
    ) == str(filePath.resolve())


def test_PostgresqlProjectPathResolverKeepsAbsolutePath(tmp_path):
    filePath = tmp_path / "volume.mrc"
    filePath.write_bytes(b"fake")

    class FakeDb:
        def fetchOne(self, query, params):
            raise AssertionError("absolute paths should not require project lookup")

    resolver = PostgresqlProjectPathResolver(
        db=FakeDb(),
        projectId=1,
    )

    assert resolver.resolveExistingPath(str(filePath)) == str(filePath.resolve())