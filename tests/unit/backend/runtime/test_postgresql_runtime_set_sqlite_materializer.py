from pathlib import Path
import sqlite3
import tempfile
import pytest

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


class ExampleLoadingNestedParentSet(
        ExampleParentSet
):
    """
    Reproduce the SetOfTiltSeries contract: inserting a nested Set
    assigns its table prefix and calls load() immediately.
    """

    def _insertItem(
            self,
            item,
    ):
        item._mapperPath.set(
            "%s,Nested%s"
            % (
                self.getFileName(),
                item.getObjId(),
            )
        )

        item.load()

        super()._insertItem(
            item
        )

        item.write(
            properties=False
        )


CLASSES = {
    "ExampleItem": ExampleItem,
    "ExampleSet": ExampleSet,
    "ExampleChildItem": ExampleChildItem,
    "ExampleNestedSet": ExampleNestedSet,
    "ExampleParentSet": ExampleParentSet,
    "ExampleLoadingNestedParentSet": ExampleLoadingNestedParentSet,
}


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
        nativeSetClass,
        runtimeInfo,
        runtimeProperties=None,
):
    sourceSet._postgresqlNativeSetClass = nativeSetClass
    sourceSet._postgresqlRuntimeInfo = dict(runtimeInfo or {})
    sourceSet._postgresqlRuntimeProperties = dict(runtimeProperties or {})
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
    sourceSet = _createRootSource(sourcePath)

    _configureRuntimeSource(
        sourceSet=sourceSet,
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

    materializer = PostgresqlRuntimeSetSqliteMaterializer()
    targetPath = materializer.materialize(sourceSet)

    try:
        assert Path(targetPath).is_file()
        assert targetPath != str(sourcePath)
        assert targetPath != "/legacy/output.sqlite"
        assert materializer.materialize(sourceSet) == targetPath
        assert sourceSet._postgresqlRuntimeProperties["fileName"] == "/legacy/output.sqlite"
        assert sourceSet._postgresqlMaterializedFileName == targetPath
        assert "materializedFileName" not in sourceSet._postgresqlRuntimeProperties

        compatibilitySet = _openSet(ExampleSet, targetPath)

        try:
            assert compatibilitySet.getSize() == 1
            assert compatibilitySet.getSamplingRate() == 1.5

            item = compatibilitySet.getFirstItem()

            assert isinstance(item, ExampleItem)
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

    sourceSet = _createRootSource(
        sourcePath
    )

    _configureRuntimeSource(
        sourceSet=sourceSet,
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

    sourceSet = _createRootSource(
        sourcePath
    )

    _configureRuntimeSource(
        sourceSet=sourceSet,
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
    sourceSet = _createEmptySource(
        sourcePath
    )

    _configureRuntimeSource(
        sourceSet=sourceSet,
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
        itemsById = {}

        for item in compatibilitySet:
            metadata = getattr(
                item,
                "_metadata",
                None,
            )

            itemsById[item.getObjId()] = {
                "name": item._name.get(),
                "metadata": (
                    metadata._value.get()
                    if metadata is not None
                    else None
                ),
            }

        assert itemsById == {
            1: {
                "name": "first",
                "metadata": "present",
            },
            2: {
                "name": "second",
                "metadata": None,
            },
        }

    finally:
        compatibilitySet.close()
        sourceSet.close()

def test_MaterializeIncludesOptionalFieldsFirstPresentInLaterItems(tmp_path, monkeypatch):
    sourceSet = _createEmptySource(tmp_path / "late-optional-source.sqlite")
    first = ExampleItem()
    first.setObjId(1)
    first._name.set("first")
    second = ExampleItem()
    second.setObjId(2)
    second._name.set("second")
    second._metadata = ExampleChildItem()
    second._metadata._value.set("late value")
    sourceSet.iterItems = lambda *args, **kwargs: iter([first, second])
    _configureRuntimeSource(sourceSet, ExampleSet, {
        "setId": 502, "className": "ExampleSet", "itemClassName": "ExampleItem",
    })
    monkeypatch.setattr(sourceSet._getMapper(), "getItemSchemaColumns", lambda: [
        {"labelProperty": "_metadata._value", "className": "String"},
        {"labelProperty": "_name", "className": "String"},
        {"labelProperty": "_metadata", "className": "ExampleChildItem"},
    ], raising=False)
    try:
        path = PostgresqlRuntimeSetSqliteMaterializer().materialize(sourceSet)
        compatibilitySet = _openSet(ExampleSet, path)
        try:
            assert compatibilitySet.getSize() == 2
            assert compatibilitySet[1]._name.get() == "first"
            assert compatibilitySet[1]._metadata._value.get() is None
            assert compatibilitySet[2]._metadata._value.get() == "late value"
            assert not hasattr(first, "_metadata")
            assert second._metadata._value.get() == "late value"
        finally:
            compatibilitySet.close()
    finally:
        sourceSet.close()


def test_MaterializeUsesPersistedScalarTypeInsteadOfConstructorDefault(tmp_path, monkeypatch):
    sourceSet = _createEmptySource(tmp_path / "changed-type-source.sqlite")
    value = ExampleItem()
    value.setObjId(1)
    value._name = Float(3.25)
    sourceSet.iterItems = lambda *args, **kwargs: iter([value])
    _configureRuntimeSource(sourceSet, ExampleSet, {
        "setId": 503, "className": "ExampleSet", "itemClassName": "ExampleItem",
    })
    sourceSet._postgresqlRuntimeClasses["Float"] = Float
    monkeypatch.setattr(sourceSet._getMapper(), "getItemSchemaColumns", lambda: [
        {"labelProperty": "_name", "className": "Float"},
    ], raising=False)
    try:
        path = PostgresqlRuntimeSetSqliteMaterializer().materialize(sourceSet)
        compatibilitySet = _openSet(ExampleSet, path)
        try:
            with sqlite3.connect(path) as snapshot:
                className, columnName = snapshot.execute(
                    "SELECT class_name, column_name FROM Classes WHERE label_property=?",
                    ("_name",),
                ).fetchone()
                assert className == "Float"
                assert snapshot.execute(
                    'SELECT "%s" FROM Objects WHERE id=1' % columnName,
                ).fetchone()[0] == 3.25
            assert value._name.get() == 3.25
        finally:
            compatibilitySet.close()
    finally:
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

    _configureRuntimeSource(
        sourceSet=sourceSet,
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


def test_PersistentCachedMaterializedPathIsIgnored(
        tmp_path,
):
    sourcePath = (
        tmp_path
        / "cached-output.sqlite"
    )

    sourceSet = _createRootSource(
        sourcePath
    )

    _configureRuntimeSource(
        sourceSet=sourceSet,
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


def test_RuntimePropertiesMaterializedPathIsIgnored(
        tmp_path,
        monkeypatch,
):
    monkeypatch.setattr(
        tempfile,
        "gettempdir",
        lambda: str(tmp_path),
    )

    sourcePath = tmp_path / "source.sqlite"
    sourceSet = _createRootSource(sourcePath)
    materializer = PostgresqlRuntimeSetSqliteMaterializer()

    stalePath = (
        Path(materializer._getCurrentWorkerDirectory())
        / "stale.sqlite"
    )

    stalePath.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    stalePath.write_bytes(b"stale")

    _configureRuntimeSource(
        sourceSet=sourceSet,
        nativeSetClass=ExampleSet,
        runtimeInfo={
            "setId": 32,
            "className": "ExampleSet",
            "itemClassName": "ExampleItem",
        },
        runtimeProperties={
            "materializedFileName": str(stalePath),
        },
    )

    try:
        targetPath = materializer.materialize(sourceSet)

        assert targetPath != str(stalePath)
        assert Path(targetPath).is_file()
        assert sourceSet._postgresqlMaterializedFileName == targetPath
        assert sourceSet._postgresqlRuntimeProperties["materializedFileName"] == str(stalePath)

        compatibilitySet = _openSet(
            ExampleSet,
            targetPath,
        )

        try:
            assert compatibilitySet.getSize() == 1
            assert compatibilitySet.getFirstItem().getObjId() == 7
        finally:
            compatibilitySet.close()
    finally:
        sourceSet.close()


def test_RecursiveMaterializationFailsFast(
        tmp_path,
):
    sourcePath = (
        tmp_path
        / "recursive-source.sqlite"
    )

    sourceSet = _createRootSource(
        sourcePath
    )

    _configureRuntimeSource(
        sourceSet=sourceSet,
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


def test_MaterializeRefreshesNestedSetsWithoutRecursiveManagedPathRefresh(
        tmp_path,
        monkeypatch,
):
    sourcePath = (
        tmp_path
        / "nested-refresh-source.sqlite"
    )

    sourceSet = _createNestedSource(
        sourcePath
    )

    _configureRuntimeSource(
        sourceSet=sourceSet,
        nativeSetClass=ExampleLoadingNestedParentSet,
        runtimeInfo={
            "setId": 4250,
            "className": "ExampleLoadingNestedParentSet",
            "itemClassName": "ExampleNestedSet",
        },
    )

    sourceSet.isPostgresqlRuntimeOutput = (
        lambda: True
    )

    originalMapper = sourceSet._getMapper()

    revisionMapper = RevisionAwareMapper(
        originalMapper,
        (
            "root",
            4250,
            1,
            7,
            "revision-1",
        ),
    )

    sourceSet._mapper = revisionMapper

    materializer = PostgresqlRuntimeSetSqliteMaterializer()

    originalLoad = Set.load

    def load(runtimeSet):
        compatibilityBuild = bool(
            getattr(
                runtimeSet,
                PostgresqlRuntimeSetSqliteMaterializer.COMPATIBILITY_BUILD_ATTRIBUTE,
                False,
            )
        )

        if compatibilityBuild:
            return originalLoad(runtimeSet)

        mapperPath = getattr(
            runtimeSet,
            "_mapperPath",
            None,
        )

        storagePath = (
            str(mapperPath[0]).strip()
            if mapperPath is not None and len(mapperPath)
            else ""
        )

        if (
                storagePath
                and PostgresqlRuntimeSetSqliteMaterializer.refreshManagedPath(
                    storagePath
                )
        ):
            return originalLoad(runtimeSet)

        return originalLoad(runtimeSet)

    monkeypatch.setattr(
        Set,
        "load",
        load,
    )

    try:
        targetPath = materializer.materialize(
            sourceSet
        )

        revisionMapper.revision = (
            "root",
            4250,
            2,
            7,
            "revision-2",
        )

        # Rebuilding an already registered nested-set snapshot must not
        # recursively refresh itself when the native parent append()
        # calls load() on its nested item.
        assert materializer.materialize(
            sourceSet
        ) == targetPath

        assert Path(
            targetPath
        ).is_file()

    finally:
        sourceSet.close()


def test_MaterializeRefreshesStreamingSnapshotWhenRevisionChanges(
        tmp_path,
):
    sourcePath = (
        tmp_path
        / "streaming-source.sqlite"
    )

    sourceSet = _createRootSource(
        sourcePath
    )

    _configureRuntimeSource(
        sourceSet=sourceSet,
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
                PostgresqlRuntimeSetSqliteMaterializer.refreshManagedPath(
                    targetPath
                )
                is True
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

        assert (
                PostgresqlRuntimeSetSqliteMaterializer.refreshManagedPath(
                    targetPath
                )
                is True
        )

        refreshedPath = targetPath

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


def test_CleanupCurrentWorkerDirectoryRemovesOnlyCurrentWorkerSnapshots(
        tmp_path,
        monkeypatch,
):
    monkeypatch.setattr(
        tempfile,
        "gettempdir",
        lambda: str(tmp_path),
    )

    workerDirectory = Path(
        PostgresqlRuntimeSetSqliteMaterializer._getCurrentWorkerDirectory()
    )

    siblingDirectory = (
        workerDirectory.parent
        / "worker-999999999"
    )

    workerDirectory.mkdir(
        parents=True,
        exist_ok=True,
    )

    siblingDirectory.mkdir(
        parents=True,
        exist_ok=True,
    )

    snapshotPath = (
        workerDirectory
        / "input.sqlite"
    )

    snapshotPath.write_bytes(
        b"snapshot"
    )

    Path(
        "%s-wal"
        % snapshotPath
    ).write_bytes(
        b"wal"
    )

    Path(
        "%s-shm"
        % snapshotPath
    ).write_bytes(
        b"shm"
    )

    Path(
        "%s-journal"
        % snapshotPath
    ).write_bytes(
        b"journal"
    )

    siblingSnapshotPath = (
        siblingDirectory
        / "input.sqlite"
    )

    siblingSnapshotPath.write_bytes(
        b"sibling"
    )

    runtimeSet = ExampleSet()
    materializer = PostgresqlRuntimeSetSqliteMaterializer()

    materializer._registerManagedPath(
        runtimeSet=runtimeSet,
        materializedPath=str(snapshotPath),
    )

    managedPath = str(
        snapshotPath.resolve()
    )

    assert (
        PostgresqlRuntimeSetSqliteMaterializer
        ._managedRuntimeSets
        .get(managedPath)
        is runtimeSet
    )

    report = PostgresqlRuntimeSetSqliteMaterializer.cleanupCurrentWorkerDirectory()

    assert report["workerDirectory"] == str(
        workerDirectory
    )

    assert report["removed"] is True
    assert report["deletedCount"] == 4
    assert report["registryEntriesRemoved"] == 1

    assert not workerDirectory.exists()

    assert siblingSnapshotPath.read_bytes() == b"sibling"

    assert (
        PostgresqlRuntimeSetSqliteMaterializer
        ._managedRuntimeSets
        .get(managedPath)
        is None
    )


def test_CleanupStaleWorkerDirectoriesRemovesOnlyDeadWorkers(
        tmp_path,
        monkeypatch,
):
    monkeypatch.setattr(
        tempfile,
        "gettempdir",
        lambda: str(tmp_path),
    )

    managedRoot = Path(
        PostgresqlRuntimeSetSqliteMaterializer._getManagedRootDirectory()
    )

    liveWorkerDirectory = Path(
        PostgresqlRuntimeSetSqliteMaterializer._getCurrentWorkerDirectory()
    )

    staleWorkerDirectory = (
        managedRoot
        / "worker-999999999"
    )

    liveWorkerDirectory.mkdir(
        parents=True,
        exist_ok=True,
    )

    staleWorkerDirectory.mkdir(
        parents=True,
        exist_ok=True,
    )

    liveSnapshot = (
        liveWorkerDirectory
        / "live.sqlite"
    )

    staleSnapshot = (
        staleWorkerDirectory
        / "stale.sqlite"
    )

    liveSnapshot.write_bytes(
        b"live"
    )

    staleSnapshot.write_bytes(
        b"stale"
    )

    report = (
        PostgresqlRuntimeSetSqliteMaterializer
        .cleanupStaleWorkerDirectories()
    )

    assert liveSnapshot.read_bytes() == b"live"
    assert not staleWorkerDirectory.exists()

    assert report["removedCount"] == 1
    assert report["removedDirectories"] == [
        str(
            staleWorkerDirectory
        )
    ]

def test_ReleaseRuntimeSetRemovesOnlyOwnedSnapshot(
        tmp_path,
        monkeypatch,
):
    monkeypatch.setattr(
        tempfile,
        "gettempdir",
        lambda: str(tmp_path),
    )

    materializer = PostgresqlRuntimeSetSqliteMaterializer()

    workerDirectory = Path(
        materializer._getCurrentWorkerDirectory()
    )

    workerDirectory.mkdir(
        parents=True,
        exist_ok=True,
    )

    firstPath = workerDirectory / "first.sqlite"
    secondPath = workerDirectory / "second.sqlite"

    firstPath.write_bytes(b"first")
    secondPath.write_bytes(b"second")

    firstSet = ExampleSet()
    secondSet = ExampleSet()

    firstSet._postgresqlMaterializedFileName = str(firstPath)
    firstSet._postgresqlMaterializedRevision = "revision-1"

    secondSet._postgresqlMaterializedFileName = str(secondPath)
    secondSet._postgresqlMaterializedRevision = "revision-2"

    materializer._registerManagedPath(
        runtimeSet=firstSet,
        materializedPath=str(firstPath),
    )

    materializer._registerManagedPath(
        runtimeSet=secondSet,
        materializedPath=str(secondPath),
    )

    report = materializer.releaseRuntimeSet(
        firstSet
    )

    assert report["removed"] is True
    assert not firstPath.exists()
    assert secondPath.exists()

    assert firstSet._postgresqlMaterializedFileName is None
    assert firstSet._postgresqlMaterializedRevision is None

    assert (
        PostgresqlRuntimeSetSqliteMaterializer
        ._managedRuntimeSets
        .get(str(firstPath.resolve()))
        is None
    )

    assert (
        PostgresqlRuntimeSetSqliteMaterializer
        ._managedRuntimeSets
        .get(str(secondPath.resolve()))
        is secondSet
    )


def test_CleanupCurrentWorkerDirectoryRefusesSymbolicLink(
        tmp_path,
        monkeypatch,
):
    monkeypatch.setattr(
        tempfile,
        "gettempdir",
        lambda: str(tmp_path),
    )

    workerDirectory = Path(
        PostgresqlRuntimeSetSqliteMaterializer._getCurrentWorkerDirectory()
    )

    outsideDirectory = (
        tmp_path
        / "outside"
    )

    outsideDirectory.mkdir(
        parents=True,
        exist_ok=True,
    )

    sentinelPath = (
        outsideDirectory
        / "sentinel.sqlite"
    )

    sentinelPath.write_bytes(
        b"do-not-delete"
    )

    workerDirectory.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    workerDirectory.symlink_to(
        outsideDirectory,
        target_is_directory=True,
    )

    with pytest.raises(
            RuntimeError,
            match="symbolic PostgreSQL SQLite worker directory",
    ):
        PostgresqlRuntimeSetSqliteMaterializer.cleanupCurrentWorkerDirectory()

    assert sentinelPath.read_bytes() == b"do-not-delete"
    assert workerDirectory.is_symlink()


def test_TableWideStableCreationMatchesThePerItemCursor(tmp_path):
    materializer = PostgresqlRuntimeSetSqliteMaterializer()
    itemIds = [0, 1, 999999, 1000000, 86400000001, 2 ** 31,
               materializer.MAX_TABLE_CREATION_ITEM_ID]
    connection = sqlite3.connect(str(tmp_path / "creation.sqlite"))
    connection.execute("CREATE TABLE Class001_Objects (id INTEGER PRIMARY KEY, creation DATE)")
    connection.executemany("INSERT INTO Class001_Objects VALUES (?, datetime('now'))",
                           [(itemId,) for itemId in itemIds])
    db = type("Db", (), {"executeCommand": staticmethod(connection.execute),
                         "tablePrefix": "Class001_"})()
    targetSet = type("TargetSet", (), {"_getMapper": lambda self: type("M", (), {"db": db})()})()
    materializer._setTableStableStreamingCreations(targetSet)
    stored = dict(connection.execute("SELECT id, creation FROM Class001_Objects"))
    assert stored == {itemId: materializer._buildStableStreamingCreation(itemId) for itemId in itemIds}
    item = ExampleItem()
    for itemId, deferred in ((5, True), (-1, False), (None, False),
                             (materializer.MAX_TABLE_CREATION_ITEM_ID + 1, False)):
        item.setObjId(itemId)
        assert materializer._canDeferStableStreamingCreation(item) is deferred


def test_PlannedMissingAttributesMatchTheRecursiveCompletion():
    from pwem import objects as emobj
    from pyworkflow.object import Pointer

    def schemaParticle():
        particle = emobj.Particle()
        particle.setCTF(emobj.CTFModel())
        particle.setCoordinate(emobj.Coordinate())
        particle._reference = Pointer()
        return particle

    materializer = PostgresqlRuntimeSetSqliteMaterializer()
    schema = schemaParticle()
    plan = materializer._planMissingItemAttributes(schema)
    for build in (emobj.Particle, schemaParticle):
        walked, planned = build(), build()
        for target in (walked, planned):
            target._ctfModel = None
        materializer._completeMissingItemAttributes(walked, schema)
        materializer._completeMissingItemAttributesFromPlan(planned, plan)
        assert planned.getObjDict(includeClass=True) == walked.getObjDict(includeClass=True)
        assert sorted(vars(planned)) == sorted(vars(walked))


def test_MaterializeLogsEachWrittenCopyWithItsRequester(tmp_path, caplog):
    sourceSet = _createRootSource(tmp_path / "source.sqlite")
    _configureRuntimeSource(
        sourceSet=sourceSet,
        nativeSetClass=ExampleSet,
        runtimeInfo={"setId": 31, "className": "ExampleSet", "itemClassName": "ExampleItem"},
        runtimeProperties={},
    )
    materializer = PostgresqlRuntimeSetSqliteMaterializer()
    loggerName = "app.backend.runtime.postgresql_runtime_set_sqlite_materializer"

    def requestingCode():
        return materializer.materialize(sourceSet)

    with caplog.at_level("INFO", logger=loggerName):
        requestingCode()
        requestingCode()  # Up-to-date copy: nothing is written, nothing logged.
    records = [record.getMessage() for record in caplog.records if record.name == loggerName]
    assert len(records) == 1
    assert records[0].startswith("Wrote a file copy of ExampleSet")
    assert "setId=31" in records[0] and "1 items" in records[0]
    assert records[0].endswith("in requestingCode")
    assert "test_postgresql_runtime_set_sqlite_materializer.py:" in records[0]
