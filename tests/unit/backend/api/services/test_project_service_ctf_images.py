"""The micrograph and the PSD of a CTF row: rendered once per file version, revalidated by ETag."""
import importlib
from types import SimpleNamespace

import pytest
from fastapi.responses import Response


@pytest.fixture
def module(authTestEnv):
    module = importlib.import_module("app.backend.api.services.project_service")
    module._CTF_IMAGE_CACHE.clear()
    yield module
    module._CTF_IMAGE_CACHE.clear()


@pytest.fixture
def rendered(module, monkeypatch, tmp_path):
    """A micrograph file, the renders it went through, and a service rendering it."""
    image = tmp_path / "mic_001.mrc"
    image.write_bytes(b"micrograph")
    renders = []

    class Resolver:
        def __init__(self, db, projectId):
            pass

        def resolveExistingPath(self, path):
            return str(image)

    class Preview:
        def __init__(self, **kwargs):
            pass

        def renderImageFromFilePath(self, **kwargs):
            renders.append(kwargs)
            return Response(content=b"png-%d" % len(renders), media_type="image/png")

    monkeypatch.setattr("app.backend.viewers.postgresql_path_resolver.PostgresqlProjectPathResolver", Resolver)
    monkeypatch.setattr(module, "OutputsPreview", Preview)
    service = object.__new__(module.ProjectService)
    service.currentProject = None
    render = lambda **kwargs: service._renderCtfPostgresqlImage(
        projectId=7, rawPath="Runs/mic_001.mrc", defaultIndex=None, size=1024, fmt="png", inline=True, quality=80,
        mapper=SimpleNamespace(db=None), **kwargs)
    return SimpleNamespace(image=image, renders=renders, render=render)


def test_a_row_shown_again_does_not_render_its_micrograph_again(rendered):
    first = rendered.render()
    again = rendered.render()

    assert len(rendered.renders) == 1 and again.body == first.body
    assert first.headers["etag"] == again.headers["etag"]
    assert "max-age" in first.headers["cache-control"]


def test_a_browser_with_the_image_is_answered_not_modified(rendered):
    etag = rendered.render().headers["etag"]

    assert rendered.render(ifNoneMatch=etag).status_code == 304
    assert len(rendered.renders) == 1


def test_a_file_written_again_is_rendered_again(rendered):
    first = rendered.render()
    rendered.image.write_bytes(b"micrograph written again, longer")

    second = rendered.render()

    assert len(rendered.renders) == 2 and second.headers["etag"] != first.headers["etag"]
