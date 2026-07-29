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
import pyworkflow.object as pwobject

from pyworkflow.mapper.sqlite import SqliteMapper
from pyworkflow.object import Pointer, Set, String
from pyworkflow.protocol.protocol import (
    LegacyProtocol,
    Protocol,
)

from app.backend.mapper.postgresql_runtime_mapper import (
    PostgresqlRuntimeMapper,
)


class ExampleProtocol(Protocol):
    pass


class ExampleSet(Set):
    ITEM_TYPE = String


def _createClasses():
    classes = pwobject.Dict(
        default=LegacyProtocol
    )

    classes.update(
        pwobject.OBJECTS_DICT
    )

    classes.update({
        "ExampleProtocol": ExampleProtocol,
        "ExampleSet": ExampleSet,
    })

    return classes


def test_RuntimeOutputIsInsertedAndResolvedThroughProtocolPointer(
        tmp_path,
):
    executionDbPath = (
        tmp_path
        / "run.db"
    )

    outputDbPath = (
        tmp_path
        / "output.sqlite"
    )

    sqliteMapper = SqliteMapper(
        str(executionDbPath),
        dictClasses=_createClasses(),
    )

    runtimeMapper = object.__new__(
        PostgresqlRuntimeMapper
    )

    runtimeMapper.projectId = 1

    parentProtocol = ExampleProtocol()
    parentProtocol.setObjId(2)

    childProtocol = ExampleProtocol()
    childProtocol.setObjId(3)

    childProtocol.inputMovies = Pointer(
        parentProtocol,
        extended="outputMovies",
    )

    outputMovies = ExampleSet(
        filename=str(outputDbPath)
    )

    outputMovies.setObjId(
        1_000_000_050
    )

    outputMovies.setName(
        "outputMovies"
    )

    outputMovies._objParent = (
        parentProtocol
    )

    outputMovies._objParentId = (
        parentProtocol.getObjId()
    )

    try:
        runtimeMapper.materializeProtocolInSqliteMapper(
            protocol=parentProtocol,
            sqliteMapper=sqliteMapper,
        )

        runtimeMapper.materializeProtocolInSqliteMapper(
            protocol=childProtocol,
            sqliteMapper=sqliteMapper,
        )

        sqliteMapper.db.cursor.execute(
            """
            SELECT MAX(id) AS max_id
              FROM Objects
             WHERE id >= ?
            """,
            (
                3_000_000_000,
            ),
        )

        row = sqliteMapper.db.cursor.fetchone()

        maxInternalId = (
            row["max_id"]
            if hasattr(row, "keys")
            else row[0]
        )

        assert maxInternalId is not None
        assert maxInternalId >= 3_000_000_000
        assert (
            sqliteMapper.db.selectObjectById(
                1_000_000_050
            )
            is None
        )

        runtimeMapper._storeRuntimeObjectInSqliteMapper(
            runtimeObject=outputMovies,
            sqliteMapper=sqliteMapper,
        )

        sqliteMapper.commit()

        runtimeMapper._clearSqliteMapperCaches(
            sqliteMapper
        )

        storedParent = sqliteMapper.selectById(
            2
        )

        assert hasattr(
            storedParent,
            "outputMovies",
        )

        assert (
            storedParent
            .outputMovies
            .getObjId()
            == 1_000_000_050
        )

        storedChild = sqliteMapper.selectById(
            3
        )

        assert (
            storedChild
            .inputMovies
            .get()
            is not None
        )

        assert (
            storedChild
            .inputMovies
            .get()
            .getObjId()
            == 1_000_000_050
        )

    finally:
        sqliteMapper.close()