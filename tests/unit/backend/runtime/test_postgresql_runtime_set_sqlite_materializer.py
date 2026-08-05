from pathlib import Path
import tempfile
import pytest

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


def test_MaterializeRefreshesRuntimeStateBeforeReturningCachedPath(
        tmp_path,
):
    sourcePath = tmp_path / "cached-runtime-state-source.sqlite"

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
    )

    refreshCalls = []

    def refreshRuntimeState():
        refreshCalls.append(True)
        sourceSet._samplingRate.set(1.5)
        return sourceSet

    sourceSet.refreshPostgresqlRuntimeState = refreshRuntimeState

    materializer = PostgresqlRuntimeSetSqliteMaterializer()

    try:
        targetPath = materializer.materialize(
            sourceSet
        )

        assert refreshCalls == [True]

        sourceSet._samplingRate.set(None)

        cachedPath = materializer.materialize(
            sourceSet
        )

        assert cachedPath == targetPath
        assert refreshCalls == [True, True]
        assert sourceSet.getSamplingRate() == 1.5

    finally:
        sourceSet.close()


def test_MaterializeUsesStableItemIdStreamingCursor(
        tmp_path,
):
    sourcePath = (
        tmp_path
        / "streaming-cursor-source.sqlite"
    )

    owner = FakePathOwner(
        tmp_path / "extra"
    )

    sourceSet = _createEmptySource(
        sourcePath
    )

    # Deliberately reverse the source timestamps.
    # The compatibility cursor must depend on the
    # item id, not on these values.
    firstSourceCreation = (
        "2099-01-01 "
        "00:00:00.000001+00:00"
    )

    secondSourceCreation = (
        "1980-01-01 "
        "00:00:00.000001+00:00"
    )

    firstItem = ExampleItem()
    firstItem.setObjId(7)
    firstItem.setObjCreation(
        firstSourceCreation
    )
    firstItem._name.set(
        "particle-7"
    )

    secondItem = ExampleItem()
    secondItem.setObjId(8)
    secondItem.setObjCreation(
        secondSourceCreation
    )
    secondItem._name.set(
        "particle-8"
    )

    sourceSet.iterItems = (
        lambda *args, **kwargs:
        iter([
            firstItem,
            secondItem,
        ])
    )

    _configureRuntimeSource(
        sourceSet=sourceSet,
        owner=owner,
        nativeSetClass=ExampleSet,
        runtimeInfo={
            "setId": 71,
            "className": "ExampleSet",
            "itemClassName": "ExampleItem",
        },
    )

    materializer = (
        PostgresqlRuntimeSetSqliteMaterializer()
    )

    targetPath = materializer.materialize(
        sourceSet
    )

    firstCursor = (
        materializer
        ._buildStableStreamingCreation(7)
    )

    secondCursor = (
        materializer
        ._buildStableStreamingCreation(8)
    )

    compatibilitySet = _openSet(
        ExampleSet,
        targetPath,
    )

    try:
        assert (
                compatibilitySet.getSize()
                == 2
        )

        allRows = [
            (
                item.getObjId(),
                item.getObjCreation(),
            )
            for item in (
                compatibilitySet
                .iterItems(
                    orderBy="creation",
                    direction="ASC",
                )
            )
        ]

        assert allRows == [
            (
                7,
                firstCursor,
            ),
            (
                8,
                secondCursor,
            ),
        ]

        assert (
            firstCursor
            != firstSourceCreation
        )

        assert (
            secondCursor
            != secondSourceCreation
        )

        newRows = [
            (
                item.getObjId(),
                item.getObjCreation(),
            )
            for item in (
                compatibilitySet
                .iterItems(
                    orderBy="creation",
                    direction="ASC",
                    where=(
                            'creation>'
                            '"%s"'
                            % firstCursor
                    ),
                )
            )
        ]

        assert newRows == [
            (
                8,
                secondCursor,
            ),
        ]

    finally:
        compatibilitySet.close()
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


def test_MaterializeCompletesMissingAttributesFromFirstItemSchema(
        tmp_path,
):
    sourcePath = tmp_path / "heterogeneous-source.sqlite"

    owner = FakePathOwner(
        tmp_path / "extra"
    )

    sourceSet = _createEmptySource(
        sourcePath
    )

    firstItem = ExampleItem()
    firstItem.setObjId(1)
    firstItem._name.set("first")
    firstItem._metadata = ExampleChildItem()
    firstItem._metadata._value.set("present")

    secondItem = ExampleItem()
    secondItem.setObjId(2)
    secondItem._name.set("second")

    sourceSet.iterItems = (
        lambda *args, **kwargs:
        iter([
            firstItem,
            secondItem,
        ])
    )

    _configureRuntimeSource(
        sourceSet=sourceSet,
        owner=owner,
        nativeSetClass=ExampleSet,
        runtimeInfo={
            "setId": 501,
            "className": "ExampleSet",
            "itemClassName": "ExampleItem",
        },
    )

    materializer = PostgresqlRuntimeSetSqliteMaterializer()

    targetPath = materializer.materialize(
        sourceSet
    )

    compatibilitySet = _openSet(
        ExampleSet,
        targetPath,
    )

    try:
        itemsById = {
            item.getObjId(): item
            for item in compatibilitySet
        }

        assert itemsById[1]._name.get() == "first"
        assert itemsById[1]._metadata._value.get() == "present"

        assert itemsById[2]._name.get() == "second"
        assert itemsById[2]._metadata is not None
        assert itemsById[2]._metadata._value.get() is None

    finally:
        compatibilitySet.close()
        sourceSet.close()

def test_IterSourceItemsLazilyLoadsPostgresqlMapper(
        tmp_path,
):
    sourcePath = (
        tmp_path
        / "lazy-runtime-source.sqlite"
    )

    sourceSet = _createRootSource(
        sourcePath
    )

    owner = FakePathOwner(
        tmp_path
        / "extra"
    )

    _configureRuntimeSource(
        sourceSet=sourceSet,
        owner=owner,
        nativeSetClass=ExampleSet,
        runtimeInfo={
            "setId": 61,
            "className": "ExampleSet",
            "itemClassName": "ExampleItem",
        },
    )

    sourceSet.isPostgresqlRuntimeOutput = (
        lambda: True
    )

    originalMapper = (
        sourceSet._getMapper()
    )

    originalGetMapper = (
        sourceSet._getMapper
    )

    mapperLoadCalls = []

    def getMapperLazily():
        mapperLoadCalls.append(
            True
        )

        sourceSet._mapper = (
            originalMapper
        )

        return originalMapper

    # Reproduce the real nested TiltSeries state:
    #
    # _mapper is deliberately None, but _getMapper()
    # can lazily reconstruct it.
    sourceSet._mapper = None

    sourceSet._getMapper = (
        getMapperLazily
    )

    materializer = (
        PostgresqlRuntimeSetSqliteMaterializer()
    )

    try:
        items = list(
            materializer._iterSourceItems(
                sourceSet
            )
        )

        assert mapperLoadCalls == [
            True,
        ]

        assert (
            sourceSet._mapper
            is originalMapper
        )

        assert len(items) == 1

        assert isinstance(
            items[0],
            ExampleItem,
        )

        assert (
            items[0].getObjId()
            == 7
        )

    finally:
        sourceSet._getMapper = (
            originalGetMapper
        )

        sourceSet._mapper = (
            originalMapper
        )

        sourceSet.close()


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


def test_RecursiveMaterializationFailsFast(
        tmp_path,
):
    sourcePath = (
        tmp_path
        / "recursive-source.sqlite"
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
            "setId": 91,
            "className": "ExampleSet",
            "itemClassName": "ExampleItem",
        },
    )

    sourceSet.isPostgresqlRuntimeOutput = (
        lambda: True
    )

    materializer = (
        PostgresqlRuntimeSetSqliteMaterializer()
    )

    mapper = sourceSet._getMapper()
    originalSelectAll = mapper.selectAll

    def recursiveSelectAll(
            *args,
            **kwargs,
    ):
        materializer.materialize(
            sourceSet
        )

        return originalSelectAll(
            *args,
            **kwargs,
        )

    mapper.selectAll = (
        recursiveSelectAll
    )

    try:
        with pytest.raises(
                RuntimeError,
                match=(
                    "Recursive PostgreSQL SQLite "
                    "materialization detected"
                ),
        ):
            materializer.materialize(
                sourceSet
            )

    finally:
        mapper.selectAll = (
            originalSelectAll
        )

        sourceSet.close()



class RevisionAwareMapper:
    def __init__(
            self,
            delegate,
            revision,
    ):
        self.delegate = delegate
        self.revision = revision

    def getRevisionToken(self):
        return self.revision

    def __getattr__(
            self,
            name,
    ):
        return getattr(
            self.delegate,
            name,
        )


def test_MaterializeRefreshesStreamingSnapshotWhenRevisionChanges(
        tmp_path,
):
    sourcePath = (
        tmp_path
        / "streaming-source.sqlite"
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
    )

    sourceSet.isPostgresqlRuntimeOutput = (
        lambda: True
    )

    originalMapper = (
        sourceSet._getMapper()
    )

    revisionMapper = (
        RevisionAwareMapper(
            originalMapper,
            (
                "root",
                31,
                1,
                7,
                "revision-1",
            ),
        )
    )

    sourceSet._mapper = (
        revisionMapper
    )

    materializer = (
        PostgresqlRuntimeSetSqliteMaterializer()
    )

    copyCalls = []

    originalCopySetItems = (
        materializer._copySetItems
    )

    def copySetItems(
            *args,
            **kwargs,
    ):
        copyCalls.append(
            True
        )

        return originalCopySetItems(
            *args,
            **kwargs,
        )

    materializer._copySetItems = (
        copySetItems
    )

    try:
        targetPath = (
            materializer.materialize(
                sourceSet
            )
        )

        assert copyCalls == [
            True,
        ]

        # Unchanged revision keeps the cached snapshot.
        assert (
            materializer.materialize(
                sourceSet
            )
            == targetPath
        )

        assert copyCalls == [
            True,
        ]

        secondItem = ExampleItem()

        secondItem.setObjId(
            8
        )

        secondItem._name.set(
            "particle-8"
        )

        sourceSet.append(
            secondItem
        )

        sourceSet.write()

        revisionMapper.revision = (
            "root",
            31,
            2,
            8,
            "revision-2",
        )

        refreshedPath = (
            materializer.materialize(
                sourceSet
            )
        )

        # Keep a stable compatibility filename.
        assert (
            refreshedPath
            == targetPath
        )

        # But rebuild its contents.
        assert copyCalls == [
            True,
            True,
        ]

        compatibilitySet = _openSet(
            ExampleSet,
            refreshedPath,
        )

        try:
            assert (
                compatibilitySet.getSize()
                == 2
            )

            assert [
                item._name.get()
                for item
                in compatibilitySet
            ] == [
                "particle-7",
                "particle-8",
            ]

        finally:
            compatibilitySet.close()

    finally:
        sourceSet.close()


