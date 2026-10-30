"""Every API route needs a signed-in user, except the few that cannot have one yet."""
import importlib
import re
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
    """The routes of every router of every router module, as the API mounts them."""
    from fastapi import APIRouter

    # Only the router modules the API imports (a commented import is not mounted)
    mainSource = (ROUTERS_DIR.parents[1] / "main.py").read_text()
    mounted = set(re.findall(r"^from app\.backend\.api\.routers\.(\w+) import", mainSource, re.MULTILINE))
    for routerFile in sorted(ROUTERS_DIR.glob("*_router.py")):
        if routerFile.stem not in mounted:
            continue
        module = importlib.import_module("app.backend.api.routers.%s" % routerFile.stem)
        for router in [value for value in vars(module).values() if isinstance(value, APIRouter)]:
            for route in router.routes:
                if isinstance(route, APIRoute):
                    for method in route.methods:
                        yield method, route.path, set(_dependencyCalls(route.dependant))


def test_EveryRouteButTheSignInOnesNeedsAUser(authTestEnv):
    from app.backend.api.dependencies import getCurrentUser

    # A permission check needs the signed-in user too
    open_routes = {(method, path) for method, path, calls in _routes() if getCurrentUser not in calls}

    assert open_routes == PUBLIC_ROUTES


def test_ChangingPluginsNeedsThePluginsPermission(authTestEnv):
    plugin_changes = [(method, path, calls) for method, path, calls in _routes()
                      if path.startswith("/plugins") and (method != "GET" or "/devel" in path)
                      and not path.startswith("/plugins/viewers")]

    assert plugin_changes
    for method, path, calls in plugin_changes:
        assert "plugins.manage" in {getattr(call, "permission", None) for call in calls}, (method, path)


def test_EveryProjectRouteChecksTheAccessToItsProject(authTestEnv):
    from app.backend.api.project_access import MANAGE_ROUTES, PERMISSION_ROUTES, VIEW_ROUTES

    routes = list(_routes())
    projectRoutes = [(method, path, calls) for method, path, calls in routes if "{projectId}" in path]
    unchecked = [(method, path) for method, path, calls in projectRoutes
                 if not any(getattr(call, "checksProjectAccess", False) for call in calls)
                 and (method, path) not in PUBLIC_ROUTES]
    assert unchecked == []

    # Every route named in the access tables exists (a typo would silently ask for the default level)
    known = {(method, path) for method, path, _ in routes}
    assert (MANAGE_ROUTES | VIEW_ROUTES | set(PERMISSION_ROUTES)) - known == set()
