"""Every API route needs a signed-in user, except the few that cannot have one yet."""
import importlib
from pathlib import Path

from fastapi.routing import APIRoute

ROUTERS_DIR = Path(__file__).resolve().parents[4] / "app" / "backend" / "api" / "routers"

# Signing in, the version shown on the login page, and downloads through a signed link
PUBLIC_ROUTES = {
    ("POST", "/auth/signup"),
    ("POST", "/auth/verify"),
    ("POST", "/auth/resend-code"),
    ("POST", "/auth/login"),
    ("POST", "/auth/refresh"),
    ("GET", "/system/version"),
    ("GET", "/system/update-check"),
    ("GET", "/projects/{projectId}/protocols/{protocolId}/fs/download-file"),
}


def _dependencyCalls(dependant):
    for dependency in dependant.dependencies:
        yield dependency.call
        yield from _dependencyCalls(dependency)


def _routes():
    """The routes of every router module, as the API mounts them."""
    for routerFile in sorted(ROUTERS_DIR.glob("*_router.py")):
        module = importlib.import_module("app.backend.api.routers.%s" % routerFile.stem)
        for route in module.router.routes:
            if isinstance(route, APIRoute):
                for method in route.methods:
                    yield method, route.path, set(_dependencyCalls(route.dependant))


def test_EveryRouteButTheSignInOnesNeedsAUser(authTestEnv):
    from app.backend.api.dependencies import getCurrentUser, requireAdmin

    open_routes = {(method, path) for method, path, calls in _routes()
                   if not calls & {getCurrentUser, requireAdmin}}

    assert open_routes == PUBLIC_ROUTES


def test_ChangingPluginsNeedsAnAdministrator(authTestEnv):
    from app.backend.api.dependencies import requireAdmin

    plugin_changes = [(method, path, calls) for method, path, calls in _routes()
                      if path.startswith("/plugins") and (method != "GET" or "/devel" in path)
                      and not path.startswith("/plugins/viewers")]

    assert plugin_changes
    for method, path, calls in plugin_changes:
        assert requireAdmin in calls, (method, path)
