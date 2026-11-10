"""The route of why a protocol failed is served by the app that starts (not only defined in a router)."""


def test_TheFailureRouteIsMounted():
    from app.backend.main import app

    paths = {getattr(route, "path", "") for route in app.routes}
    paths |= {getattr(route, "path", "") for mount in app.routes for route in getattr(mount, "routes", [])}
    assert any(path.endswith("/projects/{projectId}/protocols/{protocolId}/failure") for path in paths), sorted(
        path for path in paths if "summary" in path)
