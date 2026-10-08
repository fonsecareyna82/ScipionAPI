from app.backend.runtime.protocol_log_service import RuntimeProtocolLogService


def test_ReadLogWindowStartsNearEndWithoutReadingWholeHistory(tmp_path):
    path = tmp_path / "stdout.log"
    path.write_bytes(b"first line\nsecond line\nthird line\nfourth line\n")
    size = path.stat().st_size
    result = RuntimeProtocolLogService.readProtocolLogWindow(
        str(path), endOffset=size, maxBytes=23,
    )
    assert result["sizeBytes"] == size
    assert result["endOffset"] == size
    assert result["startOffset"] > 0
    assert result["content"] == "third line\nfourth line\n"


def test_ReadLogWindowCanJumpDirectlyToBeginning(tmp_path):
    path = tmp_path / "stdout.log"
    path.write_bytes(b"first\nsecond\nhird\n")
    result = RuntimeProtocolLogService.readProtocolLogWindow(
        str(path), endOffset=13, maxBytes=13,
    )
    assert result["startOffset"] == 0
    assert result["endOffset"] == 13
    assert result["content"] == "first\nsecond\n"


def test_ReadLogWindowHandlesMissingLog(tmp_path):
    result = RuntimeProtocolLogService.readProtocolLogWindow(
        str(tmp_path / "missing.log"), endOffset=None, maxBytes=1024,
    )
    assert result["content"] == ""
    assert result["startOffset"] == 0
    assert result["endOffset"] == 0
    assert result["sizeBytes"] == 0
