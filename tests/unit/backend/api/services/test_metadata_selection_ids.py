"""The row indexes of a selection by index, as the metadata viewer keeps it (ranges, or all but ranges)."""
from app.backend.api.services.project_service import ProjectService


def test_SelectedRangesAreMergedAndClipped():
    ranges = [{"start": 5, "end": 9}, {"start": 0, "end": 1}, {"start": 8, "end": 12}, {"start": 40, "end": 60}]
    assert ProjectService.selectedRowIndexes("none", ranges, 50) == [(0, 2), (5, 13), (40, 50)]


def test_SelectAllButSomeRowsIsTheComplement():
    assert ProjectService.selectedRowIndexes("all", [], 219000) == [(0, 219000)]
    assert ProjectService.selectedRowIndexes("all", [{"start": 0, "end": 9}, {"start": 100, "end": 199}], 300) \
        == [(10, 100), (200, 300)]
    assert ProjectService.selectedRowIndexes("all", [{"start": 0, "end": 299}], 300) == []
