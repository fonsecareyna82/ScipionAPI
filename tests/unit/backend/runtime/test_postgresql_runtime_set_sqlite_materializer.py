from pathlib import Path
import tempfile

from pyworkflow.object import Float, Object, Set, String

from app.backend.runtime.postgresql_runtime_set_sqlite_materializer import (
    PostgresqlRuntimeSetSqliteMaterializer,
)
from app.backend.mapper.postgresql_scipion_item_hydrator import (
    setPostgresqlRuntimeParentReference,
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


def _openSet(
        setClass,
        fileName,
        prefix="",
):
    result = setClass()

    result.setClassesDict(
        CLASSES
    )

    result._mapperPath.set(
        "%s, %s"
        % (
            fileName,
            prefix,
        )
    )

    result.load()
    result.loadAllProperties()

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


def _createRootSource(
        fileName,
):
    sourceSet = ExampleSet(
        filename=str(fileName),
        classesDict=CLASSES,
    )

    sourceSet._samplingRate.set(
        1.5
    )

    item = ExampleItem()

    item.setObjId(
        7
    )

    item._name.set(
        "particle-7"
    )

    sourceSet.append(
        item
    )

    sourceSet.write()

    return sourceSet


def _createEmptySource(
        fileName,
):
    sourceSet = ExampleSet(
        filename=str(fileName),
        classesDict=CLASSES,
    )

    sourceSet._samplingRate.set(
        2.0
    )

    return sourceSet


def _createNestedSource(
        fileName,
):
    parentSet = ExampleParentSet(
        filename=str(fileName),
        classesDict=CLASSES,
    )

    nestedSet = ExampleNestedSet()

    nestedSet.setClassesDict(
        CLASSES
    )

    nestedSet.setObjId(
        7
    )

    nestedSet._name.set(
        "series-7"
    )

    nestedSet._mapperPath.set(
        "%s, Nested7"
        % fileName
    )

    nestedSet.load()

    child = ExampleChildItem()

    child.setObjId(
        3
    )

    child._value.set(
        "child-3"
    )

    nestedSet.append(
        child
    )

    parentSet.append(
        nestedSet
    )

    nestedSet.write(
        properties=False
    )

    parentSet.write()

    # The nested mapper shares the parent's SQLite connection.
    # Detach it before the local nestedSet variable is destroyed.
    nestedSet._mapper = None

    return parentSet

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

    sourceItem = sourceSet.getFirstItem()
    sourceItem._objParent = owner

    sourceSet.iterItems = (
        lambda *args, **kwargs:
        iter([sourceItem])
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


def test_MaterializeNeverReusesPersistentLegacySqlite(
        tmp_path,
):
    sourcePath = (
        tmp_path
        / "source.sqlite"
    )

    owner = FakePathOwner(
        tmp_path
        / "extra"
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
            "fileName": str(
                sourcePath
            ),
            "_mapperPath": [
                str(sourcePath),
                "",
            ],
        },
    )

    materializer = (
        PostgresqlRuntimeSetSqliteMaterializer()
    )

    try:
        targetPath = (
            materializer.materialize(
                sourceSet
            )
        )

        assert (
            targetPath
            != str(
                sourcePath.resolve()
            )
        )

        assert (
            materializer
            ._isManagedTemporaryPath(
                targetPath
            )
            is True
        )

        assert Path(
            targetPath
        ).is_file()

        assert (
            str(
                Path(targetPath)
            )
            .startswith(
                str(
                    Path(
                        tempfile.gettempdir()
                    )
                    / materializer
                    .DIRECTORY_NAME
                )
            )
        )

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

    sourceNestedSet = sourceSet.getFirstItem()
    sourceNestedSet._objParent = sourceSet

    sourceSet.iterItems = (
        lambda *args, **kwargs:
        iter([sourceNestedSet])
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
                nestedSet._mapper = None
            compatibilitySet.close()
    finally:
        if sourceNestedSet is not None:
            sourceNestedSet._mapper = None

        sourceSet.close()


def test_OpenWritableReturnsNativeAppendableSet(
        tmp_path,
):
    sourcePath = (
        tmp_path
        / "resume-output.sqlite"
    )

    owner = FakePathOwner(
        tmp_path
        / "extra"
    )

    sourceSet = _createRootSource(
        sourcePath
    )

    _configureRuntimeSource(
        sourceSet=sourceSet,
        owner=owner,
        nativeSetClass=ExampleSet,
        runtimeInfo={
            "setId": 51,
            "className": "ExampleSet",
            "itemClassName": "ExampleItem",
        },
        runtimeProperties={
            "fileName": str(
                sourcePath
            ),
        },
    )

    sourceSet.setObjId(
        500
    )

    sourceSet.setName(
        "outputSet"
    )

    sourceSet.close()

    materializer = (
        PostgresqlRuntimeSetSqliteMaterializer()
    )

    writableSet = (
        materializer.openWritable(
            sourceSet
        )
    )

    try:
        assert isinstance(
            writableSet,
            ExampleSet,
        )

        assert writableSet.getObjId() == (
            500
        )

        assert writableSet.getObjName() == (
            "outputSet"
        )

        assert writableSet.getSize() == 1
        assert writableSet.getSamplingRate() == 1.5

        newItem = ExampleItem()
        newItem.setObjId(
            8
        )

        newItem._name.set(
            "particle-8"
        )

        writableSet.append(
            newItem
        )

        writableSet.write()

        assert writableSet.getSize() == 2

    finally:
        writableSet.close()

    reopenedSet = _openSet(
        ExampleSet,
        sourcePath,
    )

    try:
        assert reopenedSet.getSize() == 2

        restoredItem = (
            reopenedSet.getItem(
                "id",
                8,
            )
        )

        assert restoredItem._name.get() == (
            "particle-8"
        )

    finally:
        reopenedSet.close()


def test_MaterializerFindsOwnerThroughRuntimeParentReference(
        tmp_path,
):
    owner = FakePathOwner(
        tmp_path
        / "extra"
    )

    rootSet = ExampleParentSet()
    rootSet._objParent = owner

    nestedSet = ExampleNestedSet()

    setPostgresqlRuntimeParentReference(
        runtimeObject=nestedSet,
        parent=rootSet,
    )

    materializer = (
        PostgresqlRuntimeSetSqliteMaterializer()
    )

    assert (
        materializer._findPathOwner(
            nestedSet
        )
        is owner
    )

def test_PersistentCachedMaterializedPathIsIgnored(
        tmp_path,
):
    sourcePath = (
        tmp_path
        / "cached-output.sqlite"
    )

    owner = FakePathOwner(
        tmp_path
        / "extra"
    )

    sourceSet = _createRootSource(
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

    sourceSet._postgresqlMaterializedFileName = (
        str(sourcePath)
    )

    materializer = (
        PostgresqlRuntimeSetSqliteMaterializer()
    )

    try:
        targetPath = (
            materializer.materialize(
                sourceSet
            )
        )

        assert (
            targetPath
            != str(
                sourcePath.resolve()
            )
        )

        assert (
            materializer
            ._isManagedTemporaryPath(
                targetPath
            )
            is True
        )

    finally:
        sourceSet.close()


