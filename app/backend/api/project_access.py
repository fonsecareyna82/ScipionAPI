"""The access level each project route needs, checked before the route runs.

A route reading a project needs view access, one changing it needs work access, and renaming,
deleting or sharing the project needs manage access. Some POST routes only read (they send a list in
their body or render images), so they need view access only.
"""
from fastapi import Depends, Request

from app.backend.api.dependencies import getCurrentUser
from app.backend.api.permissions import checkPermission, checkProjectAccess

MANAGE_ROUTES = {
    ("PUT", "/projects/{projectId}"),
    ("DELETE", "/projects/{projectId}"),
    ("POST", "/projects/{projectId}/share"),
    ("DELETE", "/projects/{projectId}/share/{targetUserId}"),
    ("DELETE", "/projects/{projectId}/share/group/{targetGroupId}"),
}

# Routes that read although they are not GET
VIEW_ROUTES = {
    ("POST", "/projects/{projectId}/protocols/{protocolId}/logs/chunk"),
    ("POST", "/projects/{projectId}/protocols/{protocolId}/fs/download-link"),
    ("POST", "/projects/{projectId}/protocols/export"),
    ("POST", "/projects/{projectId}/protocols/export-workflow"),
    ("POST", "/projects/{projectId}/protocols/{protocolId}/viewers/runtime-preview"),
    ("POST", "/projects/{projectId}/protocols/{protocolId}/viewers/action"),
    ("POST", "/projects/{projectId}/protocols/{protocolId}/viewers/wizard"),
    ("POST", "/projects/{projectId}/protocols/{protocolId}/viewer/resolve"),
    ("POST", "/projects/{projectId}/protocols/{protocolId}/outputs/{outputName}/volumes/{volumeId}/slice/batch"),
    ("POST", "/projects/{projectId}/protocols/{protocolId}/outputs/{outputName}/tiltseries/{tiltSeriesId}/tilt/batch"),
    ("POST", "/projects/{projectId}/protocols/{protocolId}/outputs/{outputName}/coords3d/tomograms/{tomogramId}/gallery"),
    ("POST", "/projects/{projectId}/protocols/{protocolId}/outputs/{outputName}/metadata/tables/{tableName}/image/batch"),
    ("POST", "/projects/{projectId}/protocols/{protocolId}/outputs/{outputName}/external-viewers/{viewerId}/launch"),
    ("POST", "/projects/{projectId}/thumbnail/rebuild"),
    ("POST", "/projects/{projectId}/protocols/{protocolId}/thumbnail/rebuild"),
    ("POST", "/projects/{projectId}/output-thumbnails"),
    ("POST", "/projects/{projectId}/relations/candidates"),
    ("POST", "/projects/{projectId}/protocols/{protocolId}/outputs/{outputName}/coords2d/micrographs/thumbnails-batch"),
}

# Routes that also need a permission, whatever the project (fs/download checks files.download itself, as it
# also shows images inline)
PERMISSION_ROUTES = {
    ("POST", "/projects/"): "projects.create",
    ("POST", "/projects/import"): "projects.create",
    ("POST", "/projects/{projectId}/share"): "projects.share",
    ("POST", "/projects/{projectId}/protocols/{protocolId}/fs/download-link"): "files.download",
    ("POST", "/projects/{projectId}/uploads"): "files.upload",
    ("PUT", "/projects/{projectId}/uploads/{uploadId}"): "files.upload",
    ("POST", "/projects/{projectId}/uploads/{uploadId}/complete"): "files.upload",
}


def requiredProjectLevel(method: str, path: str) -> str:
    if (method, path) in MANAGE_ROUTES:
        return "manage"
    if method in ("GET", "HEAD", "OPTIONS") or (method, path) in VIEW_ROUTES:
        return "view"
    return "work"


def projectRouteAccess(getMapper):
    """The dependency of a router's routes checking the user's access, with the router's own getMapper."""

    async def checkProjectRouteAccess(request: Request, currentUser: dict = Depends(getCurrentUser),
                                      mapper=Depends(getMapper)) -> None:
        """403 unless the signed-in user may do what this route does to its project."""
        route = request.scope.get("route")
        path = getattr(route, "path", None) or request.url.path
        method = request.method.upper()

        permission = PERMISSION_ROUTES.get((method, path))
        if permission:
            checkPermission(currentUser, permission)

        rawProjectId = request.path_params.get("projectId")
        if rawProjectId is None:
            return
        try:
            projectId = int(rawProjectId)
        except (TypeError, ValueError):
            # The route answers for an id it cannot read
            return
        project = mapper.getProject(projectId=projectId, userId=currentUser["id"])
        if project is None:
            # A project the user cannot reach is not found, as the route itself answers
            return
        checkProjectAccess(project, requiredProjectLevel(method, path))

    checkProjectRouteAccess.checksProjectAccess = True
    return checkProjectRouteAccess
