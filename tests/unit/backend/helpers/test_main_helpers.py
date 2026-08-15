from pathlib import Path


def test_NormalizeMountPathAddsLeadingSlash(mainModule):
    assert mainModule._normalizeMountPath("api") == "/api"


def test_NormalizeMountPathRemovesTrailingSlash(mainModule):
    assert mainModule._normalizeMountPath("/api/") == "/api"


def test_NormalizeMountPathKeepsRoot(mainModule):
    assert mainModule._normalizeMountPath("/") == "/"


def test_NormalizeMountPathDefaultsToApi(mainModule):
    assert mainModule._normalizeMountPath("") == "/api"


def test_ShouldServeWebFalse(mainModule, monkeypatch):
    monkeypatch.setenv("SERVE_WEB", "0")
    assert mainModule._shouldServeWeb() is False


def test_ShouldServeWebTrue(mainModule, monkeypatch):
    monkeypatch.setenv("SERVE_WEB", "1")
    assert mainModule._shouldServeWeb() is True


def test_ResolveWebDistPathReturnsEmptyPathWhenUnset(mainModule, monkeypatch):
    monkeypatch.delenv("WEB_DIST_PATH", raising=False)
    assert mainModule._resolveWebDistPath() == Path("")


def test_ResolveWebDistPathResolvesAbsolutePath(mainModule, monkeypatch, tmp_path):
    webDistPath = tmp_path / "dist"
    webDistPath.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("WEB_DIST_PATH", str(webDistPath))

    assert mainModule._resolveWebDistPath() == webDistPath.resolve()