from app.backend.runtime.protocol_log_service import RuntimeProtocolLogService


def test_SearchFindsMatchesOutsideRecentlyLoadedTail(tmp_path):
    path = tmp_path / "stdout.log"
    path.write_text("needle at start\n" + "other\n" * 3000 + "NEEDLE at end\n")
    result = RuntimeProtocolLogService.searchProtocolLogFile(
        str(path), "needle", startOffset=0, maxMatches=10, maxScanBytes=200000
    )
    assert len(result["matches"]) == 2
    assert result["matches"][0]["offset"] == 0
    assert result["matches"][1]["offset"] > 10000
    assert result["done"] is True


def test_SearchUsesByteOffsetsForUtf8AndResumesWithoutDuplicates(tmp_path):
    path = tmp_path / "stdout.log"
    path.write_text("áéí\nMATCH one\ntexto\nMATCH two\n", encoding="utf-8")
    a = RuntimeProtocolLogService.searchProtocolLogFile(
        str(path), "match", startOffset=0, maxMatches=1, maxScanBytes=500
    )
    b = RuntimeProtocolLogService.searchProtocolLogFile(
        str(path), "match", startOffset=a["nextOffset"], maxMatches=1, maxScanBytes=500
    )
    assert a["matches"][0]["offset"] == len("áéí\n".encode("utf-8"))
    assert b["matches"][0]["offset"] > a["matches"][0]["offset"]
    assert b["done"] is True


def test_SearchIsBoundedAndReturnsResumeCursor(tmp_path):
    path = tmp_path / "stdout.log"
    path.write_bytes(b"line without match\n" * 4000)
    a = RuntimeProtocolLogService.searchProtocolLogFile(
        str(path), "needle", startOffset=0, maxMatches=10, maxScanBytes=1024
    )
    assert a["matches"] == []
    assert 0 < a["nextOffset"] < path.stat().st_size
    assert a["done"] is False
    b = RuntimeProtocolLogService.searchProtocolLogFile(
        str(path), "needle", startOffset=a["nextOffset"], maxMatches=10, maxScanBytes=1024
    )
    assert b["nextOffset"] > a["nextOffset"]


def test_SearchRejectsEmptyQuery(tmp_path):
    path = tmp_path / "stdout.log"
    path.write_text("anything\n")
    import pytest
    with pytest.raises(ValueError):
        RuntimeProtocolLogService.searchProtocolLogFile(str(path), "  ")
