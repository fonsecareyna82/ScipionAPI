"""Big JSON answers of the routes that list thousands of rows go gzip compressed when the client takes it."""
import gzip
import importlib
import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def project_router(authTestEnv):
    return importlib.import_module("app.backend.api.routers.project_router")


def request(acceptEncoding):
    return SimpleNamespace(headers={"accept-encoding": acceptEncoding})


def test_a_big_answer_is_compressed_for_a_client_taking_gzip(project_router):
    payload = {"ctfs": [{"ctfId": str(i), "micrographName": "mic_%05d.mrc" % i, "defocusU": 20000.5} for i in range(5000)]}

    response = project_router._compressedJson(request("gzip, deflate, br"), payload)

    assert response.headers["content-encoding"] == "gzip"
    assert json.loads(gzip.decompress(response.body)) == payload
    assert len(response.body) < len(json.dumps(payload)) / 5


def test_a_small_answer_or_a_client_without_gzip_gets_plain_json(project_router):
    small = project_router._compressedJson(request("gzip"), {"ctfs": [], "total": 0})
    plain = project_router._compressedJson(request(""), {"ctfs": [{"ctfId": str(i)} for i in range(10000)]})

    assert "content-encoding" not in small.headers and json.loads(small.body) == {"ctfs": [], "total": 0}
    assert "content-encoding" not in plain.headers
