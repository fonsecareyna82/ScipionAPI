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
from pyworkflow.object import (
    Object,
    Set,
    String,
)

from app.backend.mapper.postgresql_runtime_mapper import (
    PostgresqlRuntimeMapper,
)


class SnapshotItem(Object):
    def __init__(
            self,
            **kwargs,
    ):
        super().__init__(
            **kwargs
        )

        self._name = String()


class SnapshotSet(Set):
    ITEM_TYPE = SnapshotItem


CLASSES = {
    "SnapshotItem": SnapshotItem,
    "SnapshotSet": SnapshotSet,
}


def test_NewNativeSetIsReopenedBeforePostgresqlSnapshot(
        tmp_path,
):
    setPath = (
        tmp_path
        / "output.sqlite"
    )

    outputSet = SnapshotSet(
        filename=str(setPath),
        classesDict=CLASSES,
    )

    item = SnapshotItem()
    item.setObjId(1)
    item._name.set(
        "item-1"
    )

    outputSet.append(
        item
    )

    originalMapper = (
        outputSet._mapper
    )

    try:
        assert (
            originalMapper.doCreateTables
            is False
        )

        assert not hasattr(
            originalMapper,
            "_objColumns",
        )

        runtimeMapper = object.__new__(
            PostgresqlRuntimeMapper
        )

        report = (
            runtimeMapper
            ._prepareNativeSetForPostgresqlSnapshot(
                outputSet
            )
        )

        assert report["reopened"] is True

        assert outputSet._mapper is not (
            originalMapper
        )

        assert hasattr(
            outputSet._mapper,
            "_objColumns",
        )

        restoredItem = (
            outputSet.getFirstItem()
        )

        assert restoredItem.getObjId() == 1
        assert restoredItem._name.get() == (
            "item-1"
        )

    finally:
        outputSet.close()


def test_PostgresqlRuntimeSetIsNotReopened():
    outputSet = SnapshotSet()

    outputSet.isPostgresqlRuntimeOutput = (
        lambda: True
    )

    runtimeMapper = object.__new__(
        PostgresqlRuntimeMapper
    )

    report = (
        runtimeMapper
        ._prepareNativeSetForPostgresqlSnapshot(
            outputSet
        )
    )

    assert report == {
        "reopened": False,
        "reason": (
            "postgresql_runtime_set"
        ),
    }