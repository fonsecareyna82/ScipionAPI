import pytest
from fastapi import HTTPException

from app.backend.api.services import custom_code


class _Protocol:
    def __init__(self, className):
        self.className = className

    def getClassName(self):
        return self.className


def _held(monkeypatch, isSystem, permissions):
    access = pytest.importorskip("app.backend.mapper.access_mapper")
    monkeypatch.setattr(access.AccessPostgresqlMapper, "__init__", lambda self, db: None)
    monkeypatch.setattr(access.AccessPostgresqlMapper, "getUserPermissions",
                        lambda self, userId: {"isSystem": isSystem, "permissions": permissions})


def test_ACustomOperationNeedsThePermission(monkeypatch):
    mapper = type("Mapper", (), {"db": None})()
    _held(monkeypatch, False, ["projects.create"])
    with pytest.raises(HTTPException) as refused:
        custom_code.checkLaunch(mapper, 3, [_Protocol("ProtImportMovies"), _Protocol("ProtCustomOperation")])
    assert refused.value.status_code == 403
    # Other protocols, an internal launch, the permission or an administrator
    custom_code.checkLaunch(mapper, 3, [_Protocol("ProtImportMovies")])
    custom_code.checkLaunch(mapper, None, [_Protocol("ProtCustomOperation")])
    _held(monkeypatch, False, ["protocols.customCode"])
    custom_code.checkLaunch(mapper, 3, [_Protocol("ProtCustomOperation")])
    _held(monkeypatch, True, [])
    custom_code.checkLaunch(mapper, 3, [_Protocol("ProtCustomOperation")])
