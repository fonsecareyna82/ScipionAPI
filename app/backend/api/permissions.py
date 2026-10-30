"""What a user may do: the permission catalogue, the access levels of a project and their checks.

Permissions are fixed here, as each one is checked by the code. Roles, created by an administrator, are
sets of them; a user holds the permissions of their own roles and of the roles of their groups. The
Administrator role is the system one: it holds every permission, now and in the future.
"""
from typing import Callable, Dict, Iterable

from fastapi import Depends, HTTPException, status

PERMISSIONS: Dict[str, str] = {
    # System
    "plugins.manage": "Install and uninstall plugins and their binaries",
    "settings.manage": "Change the instance settings, the host and the environment variables",
    "jobs.manage": "Manage the queues, the nodes and the workers",
    "users.manage": "Activate and deactivate accounts, and give them roles and groups",
    "roles.manage": "Create roles and choose their permissions",
    "groups.manage": "Create groups and manage their members",
    "audit.view": "See the audit log",
    # Projects
    "projects.create": "Create and import projects",
    "projects.share": "Share own projects with users and groups",
    "projects.viewAll": "See every project without it being shared",
    "projects.manageAll": "Work on and manage every project",
    # Files
    "files.browseServer": "Browse the whole file system of the server",
    "files.download": "Download files of the projects one can see",
    # Facility
    "facility.monitor": "See the facility monitor with every active stream",
    # A project's own monitor thresholds need work access to the project, not this
    "facility.thresholds": "Change the facility's default quality thresholds",
    "facility.sessions": "Create and close acquisition sessions",
    "facility.manage": "Manage microscopes and processing templates",
}

# What one may do in a project, each level including the ones before it
PROJECT_ACCESS_LEVELS = ("view", "work", "manage")
PROJECT_ACCESS_RANK = {level: rank for rank, level in enumerate(PROJECT_ACCESS_LEVELS, start=1)}

SYSTEM_ROLE_NAME = "Administrator"

# The roles a new installation starts with; an administrator can change all but the system one
DEFAULT_ROLES = (
    (SYSTEM_ROLE_NAME, "Everything, now and in the future", True, False, tuple(PERMISSIONS)),
    ("Facility manager", "Runs the facility: users, groups, microscopes and templates", False, False,
     ("users.manage", "groups.manage", "projects.create", "projects.share", "projects.viewAll",
      "files.browseServer", "files.download", "facility.monitor", "facility.thresholds", "facility.sessions",
      "facility.manage")),
    ("Technician", "Facility staff: sessions, the monitor and the projects of the facility", False, False,
     ("projects.create", "projects.share", "projects.viewAll", "files.browseServer", "files.download",
      "facility.monitor", "facility.thresholds", "facility.sessions")),
    ("User", "Works on their own projects and the ones shared with them", False, True,
     ("projects.create", "projects.share", "files.download")),
    ("Guest", "Only sees what is shared with them", False, False, ()),
)


def withPermissions(mapper, userRecord: dict) -> dict:
    """userRecord with the permissions of its roles and of its groups' roles (a system role holds all)."""
    from app.backend.mapper.access_mapper import AccessPostgresqlMapper

    held = AccessPostgresqlMapper(mapper.db).getUserPermissions(userRecord["id"])
    user = dict(userRecord)
    user["isSystemAdmin"] = held["isSystem"]
    user["permissions"] = sorted(PERMISSIONS) if held["isSystem"] else sorted(
        permission for permission in held["permissions"] if permission in PERMISSIONS)
    return user


def hasPermission(user: dict, permission: str) -> bool:
    """Whether the signed-in user (as getCurrentUser gives it) holds permission."""
    if permission not in PERMISSIONS:
        raise ValueError("Unknown permission: %s" % permission)
    return permission in set((user or {}).get("permissions") or ())


def checkPermission(user: dict, permission: str) -> None:
    if not hasPermission(user, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission required: %s" % permission,
        )


_permissionDependencies: Dict[str, Callable] = {}


def requirePermission(permission: str) -> Callable:
    """A route dependency giving the signed-in user if they hold permission, else 403."""
    if permission not in PERMISSIONS:
        raise ValueError("Unknown permission: %s" % permission)
    dependency = _permissionDependencies.get(permission)
    if dependency is None:
        from app.backend.api.dependencies import getCurrentUser

        async def dependency(currentUser: dict = Depends(getCurrentUser)) -> dict:
            checkPermission(currentUser, permission)
            return currentUser

        dependency.permission = permission
        dependency.__name__ = "require_%s" % permission.replace(".", "_")
        _permissionDependencies[permission] = dependency
    return dependency


def checkProjectAccess(project: dict, level: str) -> None:
    """403 unless the user's access to project (as getProject resolves it) reaches level."""
    if level not in PROJECT_ACCESS_RANK:
        raise ValueError("Unknown project access level: %s" % level)
    granted = str((project or {}).get("access") or "")
    if PROJECT_ACCESS_RANK.get(granted, 0) < PROJECT_ACCESS_RANK[level]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This needs %s access to the project" % level,
        )


def validPermissions(permissions: Iterable[str]) -> list:
    unknown = sorted(set(permissions) - set(PERMISSIONS))
    if unknown:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Unknown permissions: %s" % ", ".join(unknown))
    return sorted(set(permissions))
