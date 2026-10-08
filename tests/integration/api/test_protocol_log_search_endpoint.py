import pytest

URL = "/projects/1/protocols/7/logs/search"


def test_SearchLogsRejectsMissingProject(projectClient, fakeProjectService):
    fakeProjectService.projectDbRowResult = None
    response = projectClient.get(URL, params={"channel": "stdout", "query": "error"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"


@pytest.mark.parametrize("params", [
    {"channel": "unknown", "query": "error"},
    {"channel": "stdout", "query": "  "},
    {"channel": "stdout", "query": "error", "startOffset": -1},
])
def test_SearchLogsValidatesInputs(projectClient, fakeProjectService, params, monkeypatch):
    calls = []
    monkeypatch.setattr(fakeProjectService, "searchProtocolLogsService", lambda **kw: calls.append(kw), raising=False)
    response = projectClient.get(URL, params=params)
    assert response.status_code == 422
    assert calls == []


def test_SearchLogsDelegatesWithMapperAndPagination(projectClient, fakeProjectService, monkeypatch):
    calls = []
    result = {"matches": [{"offset": 12, "text": "ERROR here"}],
              "nextOffset": 24, "sizeBytes": 100, "done": False}
    def search(**kw):
        calls.append(kw)
        return result
    monkeypatch.setattr(fakeProjectService, "searchProtocolLogsService", search, raising=False)
    response = projectClient.get(URL, params={
        "channel": "stderr", "query": "error",
        "startOffset": 12, "maxMatches": 15, "maxScanBytes": 8192,
    })
    assert response.status_code == 200
    assert response.json() == result
    assert len(calls) == 1
    assert calls[0]["projectId"] == 1
    assert calls[0]["protocolId"] == 7
    assert calls[0]["channel"] == "stderr"
    assert calls[0]["query"] == "error"
    assert calls[0]["startOffset"] == 12
    assert calls[0]["maxMatches"] == 15
    assert calls[0]["maxScanBytes"] == 8192
    assert calls[0]["mapper"] is not None
    assert calls[0]["protocolIdIsScipionId"] is True
