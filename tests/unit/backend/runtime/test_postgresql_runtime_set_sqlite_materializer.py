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

from pyworkflow.object import Float, Object, Set, String

from app.backend.runtime.postgresql_runtime_set_sqlite_materializer import (
    PostgresqlRuntimeSetSqliteMaterializer,
)


class ExampleItem(Object):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._name = String()


class ExampleSet(Set):
    ITEM_TYPE = ExampleItem

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._samplingRate = Float()

    def getSamplingRate(self):
        return self._samplingRate.get()

    def _loadClassesDict(self):
        return CLASSES


class ExampleChildItem(Object):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._value = String()


class ExampleNestedSet(Set):
    ITEM_TYPE = ExampleChildItem

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._name = String()

    def _loadClassesDict(self):
        return CLASSES


class ExampleParentSet(Set):
    ITEM_TYPE = ExampleNestedSet

    def _loadClassesDict(self):
        return CLASSES


CLASSES = {
    "ExampleItem": ExampleItem,
    "ExampleSet": ExampleSet,
    "ExampleChildItem": ExampleChildItem,
    "ExampleNestedSet": ExampleNestedSet,
    "ExampleParentSet": ExampleParentSet,
}


class FakePathOwner(Object):
    def __init__(self, extraPath, **kwargs):
        super().__init__(**kwargs)
        self._extraPath = Path(extraPath)

    def getExtraPath(self, *paths):
        return str(self._extraPath.joinpath(*paths))


def _openSet(setClass, fileName, prefix=""):
    result = setClass()
    result.setClassesDict(CLASSES)
    result._mapperPath.set("%s, %s" % (fileName, prefix))
    result.load()
    return result


def _configureRuntimeSource(
        sourceSet,
        owner,
        nativeSetClass,
        runtimeInfo,
        runtimeProperties=None,
):
    sourceSet._objParent = owner
    sourceSet._postgresqlNativeSetClass = nativeSetClass
    sourceSet._postgresqlRuntimeInfo = dict(runtimeInfo or {})
    sourceSet._postgresqlRuntimeProperties = dict(
        runtimeProperties or {}
    )
    sourceSet._postgresqlRuntimeClasses = dict(CLASSES)
    sourceSet._postgresqlMaterializedFileName = None


def _createRootSource(fileName):
    sourceSet = ExampleSet(
        filename=str(fileName),
        classesDict=CLASSES,
    )
    sourceSet._samplingRate.set(1.5)

    item = ExampleItem()
    item.setObjId(7)
    item._name.set("particle-7")
    sourceSet.append(item)

    sourceSet.write()
    sourceSet.close()

    return _openSet(
        ExampleSet,
        str(fileName),
    )


def _createEmptySource(fileName):
    sourceSet = ExampleSet(
        filename=str(fileName),
        classesDict=CLASSES,
    )
    sourceSet._samplingRate.set(2.0)
    sourceSet.write()
    sourceSet.close()

    return _openSet(
        ExampleSet,
        str(fileName),
    )


def _createNestedSource(fileName):
    parentSet = ExampleParentSet(
        filename=str(fileName),
        classesDict=CLASSES,
    )

    nestedSet = ExampleNestedSet()
    nestedSet.setClassesDict(CLASSES)
    nestedSet.setObjId(7)
    nestedSet._name.set("series-7")
    nestedSet._mapperPath.set(
        "%s, Nested7" % fileName
    )
    nestedSet.load()

    child = ExampleChildItem()
    child.setObjId(3)
    child._value.set("child-3")
    nestedSet.append(child)
    nestedSet.write(properties=False)
    nestedSet.close()

    parentSet.append(nestedSet)
    parentSet.write()
    parentSet.close()

    return _openSet(
        ExampleParentSet,
        str(fileName),
    )


def test_MaterializeCreatesReadableSqliteAndCachesPath(
        tmp_path,
):
    sourcePath = tmp_path / "source.sqlite"
    owner = FakePathOwner(
        tmp_path / "extra"
    )
    sourceSet = _createRootSource(
        sourcePath
    )

    _configureRuntimeSource(
        sourceSet=sourceSet,
        owner=owner,
        nativeSetClass=ExampleSet,
        runtimeInfo={
            "setId": 31,
            "className": "ExampleSet",
            "itemClassName": "ExampleItem",
        },
        runtimeProperties={
            "fileName": "/legacy/output.sqlite",
        },
    )

    materializer = (
        PostgresqlRuntimeSetSqliteMaterializer()
    )

    targetPath = materializer.materialize(
        sourceSet
    )

    try:
        assert Path(targetPath).is_file()
        assert targetPath != str(sourcePath)
        assert targetPath != "/legacy/output.sqlite"

        assert materializer.materialize(
            sourceSet
        ) == targetPath

        assert (
            sourceSet._postgresqlRuntimeProperties[
                "fileName"
            ]
            == "/legacy/output.sqlite"
        )
        assert (
            sourceSet._postgresqlRuntimeProperties[
                "materializedFileName"
            ]
            == targetPath
        )

        compatibilitySet = _openSet(
            ExampleSet,
            targetPath,
        )

        try:
            assert compatibilitySet.getSize() == 1
            assert compatibilitySet.getSamplingRate() == 1.5

            item = compatibilitySet.getFirstItem()

            assert isinstance(
                item,
                ExampleItem,
            )
            assert item.getObjId() == 7
            assert item._name.get() == "particle-7"
        finally:
            compatibilitySet.close()
    finally:
        sourceSet.close()


def test_MaterializeSupportsEmptySets(
        tmp_path,
):
    sourcePath = tmp_path / "empty-source.sqlite"
    owner = FakePathOwner(
        tmp_path / "extra"
    )
    sourceSet = _createEmptySource(
        sourcePath
    )

    _configureRuntimeSource(
        sourceSet=sourceSet,
        owner=owner,
        nativeSetClass=ExampleSet,
        runtimeInfo={
            "setId": 32,
            "className": "ExampleSet",
            "itemClassName": "ExampleItem",
        },
    )

    targetPath = (
        PostgresqlRuntimeSetSqliteMaterializer()
        .materialize(sourceSet)
    )

    try:
        compatibilitySet = _openSet(
            ExampleSet,
            targetPath,
        )

        try:
            assert compatibilitySet.getSize() == 0
            assert compatibilitySet.getSamplingRate() == 2.0
        finally:
            compatibilitySet.close()
    finally:
        sourceSet.close()


def test_MaterializeCopiesNestedLogicalItems(
        tmp_path,
):
    sourcePath = tmp_path / "nested-source.sqlite"
    owner = FakePathOwner(
        tmp_path / "extra"
    )
    sourceSet = _createNestedSource(
        sourcePath
    )

    _configureRuntimeSource(
        sourceSet=sourceSet,
        owner=owner,
        nativeSetClass=ExampleParentSet,
        runtimeInfo={
            "setId": 41,
            "className": "ExampleParentSet",
            "itemClassName": "ExampleNestedSet",
        },
    )

    targetPath = (
        PostgresqlRuntimeSetSqliteMaterializer()
        .materialize(sourceSet)
    )

    try:
        compatibilitySet = _openSet(
            ExampleParentSet,
            targetPath,
        )
        nestedSet = None

        try:
            assert compatibilitySet.getSize() == 1

            nestedSet = compatibilitySet.getFirstItem()

            assert isinstance(
                nestedSet,
                ExampleNestedSet,
            )
            assert nestedSet.getObjId() == 7
            assert nestedSet._name.get() == "series-7"
            assert nestedSet.getSize() == 1

            child = nestedSet.getFirstItem()

            assert isinstance(
                child,
                ExampleChildItem,
            )
            assert child.getObjId() == 3
            assert child._value.get() == "child-3"
        finally:
            if nestedSet is not None:
                nestedSet.close()
            compatibilitySet.close()
    finally:
        sourceSet.close()