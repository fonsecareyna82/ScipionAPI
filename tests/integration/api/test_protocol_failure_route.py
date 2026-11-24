"""The route of why a protocol failed is served by the app that starts (not only defined in a router)."""
import importlib
import sys
import types

import pytest


@pytest.fixture
def app(monkeypatch):
    """The app main builds, with its real routers; only the preparation of the installation's environment
    (its .env, Scipion's variables) is left out, so it builds where there is no installation (the CI)."""
    bootstrap = types.ModuleType("app.backend.bootstrap")
    bootstrap.bootstrapEnv = lambda: None
    environment = types.ModuleType("app.backend.api.services.environment")
    environment.prepareEnvironment = lambda: None
    environment.removeCustomEnvironmentVariables = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "app.backend.bootstrap", bootstrap)
    monkeypatch.setitem(sys.modules, "app.backend.api.services.environment", environment)
    monkeypatch.delitem(sys.modules, "app.backend.main", raising=False)
    built = importlib.import_module("app.backend.main").app
    sys.modules.pop("app.backend.main", None)
    return built


def test_TheFailureRouteIsMounted(app):

    paths = {getattr(route, "path", "") for route in app.routes}
    paths |= {getattr(route, "path", "") for mount in app.routes for route in getattr(mount, "routes", [])}
    assert any(path.endswith("/projects/{projectId}/protocols/{protocolId}/failure") for path in paths), sorted(
        path for path in paths if "summary" in path)


def test_TheSignInRoutesAreMounted(app):

    paths = {getattr(route, "path", "") for mount in app.routes for route in getattr(mount, "routes", [])}
    for path in ("/auth/providers", "/auth/oidc/{key}/start", "/auth/oidc/{key}/callback", "/auth/oidc/exchange",
                 "/settings/sign-in-providers", "/settings/sign-in-providers/{providerId}",
                 "/settings/sign-in-providers/{providerId}/test"):
        assert path in paths, path
