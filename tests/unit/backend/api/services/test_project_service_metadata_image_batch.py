"""A batch of image cells opens its table once and reads its rows in one window, not once per cell."""
import importlib

import pytest
from PIL import Image


@pytest.fixture
def module(authTestEnv):
    module = importlib.import_module("app.backend.api.services.project_service")
    module._METADATA_IMAGE_CACHE.clear()
    yield module
    module._METADATA_IMAGE_CACHE.clear()


class Renderer:
    def render(self, value, rowValues):
        return Image.new("L", (8, 8), color=int(value) % 255)


class Column:
    def getRenderer(self):
        return Renderer()

    def getName(self):
        return "_filename"


class Row:
    def __init__(self, index):
        self.index = index

    def getValues(self):
        return [self.index]


class Table:
    def getColumns(self):
        return [Column()]

    def setSortingColumn(self, column):
        pass

    def setSortingAsc(self, asc):
        pass

    def getColumnIndexFromLabel(self, label):
        return 0

    def getName(self):
        return "objects"

    def getAlias(self):
        return "objects"


class ObjectManager:
    _fileName = "postgresql://set"
    _dao = None

    def __init__(self):
        self.reads = []

    def getRows(self, tableName, start, count):
        self.reads.append((start, count))
        return [Row(index) for index in range(start, start + count)]


def test_a_batch_opens_its_table_once_and_reads_its_rows_in_one_window(module, monkeypatch):
    objectManager = ObjectManager()
    opened = []

    def openTable(*args, **kwargs):
        opened.append(args)
        return objectManager, Table()

    service = object.__new__(module.ProjectService)
    service.currentProject = None
    monkeypatch.setattr(service, "_openMetadataTable", openTable)

    answer = service.renderMetadataImageCellsBatchService(
        7, 22, "outputParticles", "objects", [(None, index, "_filename") for index in range(100, 140)], size=8)

    assert len(answer["items"]) == 40 and not answer["errors"]
    assert len(opened) == 1
    assert objectManager.reads == [(100, 40)]


def test_cells_too_far_apart_each_read_their_own_row(module, monkeypatch):
    objectManager = ObjectManager()
    service = object.__new__(module.ProjectService)
    service.currentProject = None
    monkeypatch.setattr(service, "_openMetadataTable", lambda *args, **kwargs: (objectManager, Table()))

    service.renderMetadataImageCellsBatchService(7, 22, "outputParticles", "objects",
                                                 [(None, 0, "_filename"), (None, 100000, "_filename")], size=8)

    assert objectManager.reads == [(0, 1), (100000, 1)]
