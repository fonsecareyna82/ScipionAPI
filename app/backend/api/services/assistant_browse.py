"""The AI assistant reading the web's own pages: the GET routes in READ_ROUTES, run inside the API as the user who
asks (with their own sign-in), so every route checks their permissions exactly as when the web calls it.

Only routes listed here: reading ones that answer JSON and say nothing private (no users, sign-in, audit, mail,
host or environment settings, server files or downloads). The administrators' pages (jobs, nodes, disk, plugin
installs) answer only users with their permission, as in the web. The answer is cut to MAX_CHARS for the model.
"""
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MAX_CHARS = 16000
MAX_PAGE_SIZE = 50

_P = "/projects/{projectId}"
_PROT = _P + "/protocols/{protocolId}"
_OUT = _PROT + "/outputs/{outputName}"

# (path, what it gives), relative to the API's root
READ_ROUTES: List[Tuple[str, str]] = [
    ("/projects/", "the projects the user can see"),
    ("/projects/workflows", "the ready-made workflows that can be imported"),
    (_P + "/overview", "a project's overview: protocols by status, progress, problems"),
    (_P + "/summary", "a project's summary"),
    (_P + "/disk-usage", "the disk a project uses"),
    (_P + "/monitor", "the streaming monitor of a single-particle project: CTF, picking, 2D classes as they come"),
    (_P + "/monitor/tomo", "the streaming monitor of a tomography project"),
    (_P + "/tags", "a project's tags"),
    (_PROT + "/summary", "a protocol's summary, as the desktop Summary tab"),
    (_PROT + "/steps", "a protocol's steps and their status (where a running protocol is)"),
    (_PROT + "/launches", "a protocol's launch history: when, where, how long"),
    (_PROT + "/failure", "why a protocol failed"),
    (_PROT + "/logs/search", "search a protocol's log; query: channel (stdout|stderr), query (the text)"),
    (_PROT + "/suggestions/next", "the protocols usually run after this one"),
    (_PROT + "/viewers", "the ways to analyze a protocol's results"),
    (_OUT + "/metadata/tables", "the tables of an output (a set): their names and sizes"),
    (_OUT + "/metadata/tables/{tableName}/schema", "the columns of an output's table"),
    (_OUT + "/metadata/tables/{tableName}/page", "rows of an output's table; query: page (from 1), pageSize "
                                                 "(at most 50), sortBy (a column), asc (true|false)"),
    (_OUT + "/ctf", "the CTF of every micrograph of a CTF output: defocus, resolution, astigmatism"),
    (_OUT + "/fsc/rows", "an FSC curve"),
    (_OUT + "/coords2d/micrographs", "the micrographs of a coordinates output, with how many particles each has"),
    (_OUT + "/volumes", "the volumes of an output"),
    (_OUT + "/volumes/{volumeId}/info", "a volume's size, sampling and values"),
    ("/workspace/protocol-activity", "what is running or waiting now, in every project the user can see"),
    ("/resources", "the machines now: CPU, memory and GPUs in use"),
    ("/storage/quotas/me", "the user's disk quota and use"),
    ("/usage/compute/me", "the computing the user used"),
    ("/notifications", "the user's notices"),
    ("/plugins/", "the plugins installed and their versions"),
    ("/system/version", "ScipionWeb's version"),
    ("/facility/status", "the facility now: microscopes and their sessions"),
    ("/facility/sessions", "the acquisition sessions"),
    ("/facility/sessions/{sessionId}", "one acquisition session"),
    ("/facility/my-sessions", "the user's acquisition sessions"),
    ("/facility/alerts", "the facility's open alerts"),
    ("/facility/bookings", "the microscope bookings"),
    ("/facility/my-bookings", "the user's bookings"),
    ("/facility/microscopes", "the microscopes and their detectors"),
    ("/facility/samples", "the samples and grids"),
    # For the people who run the installation (each page answers only those with its permission)
    ("/settings/jobs", "administrators: the queues, the workers and the jobs running, waiting and recent"),
    ("/settings/jobs/nodes", "administrators: the machines (nodes) that run protocols, their GPUs and state"),
    ("/settings/instance/resources", "administrators: the resources of the main machine"),
    ("/storage/usage", "administrators: the disk each user, group and project uses, and the free space"),
    ("/storage/quotas", "administrators: the disk quotas"),
    ("/usage/compute", "administrators: the computing each user and group used"),
    ("/plugins/tasks", "administrators: the plugin installs and updates, and how they ended"),
    ("/plugins/tasks/{taskId}", "administrators: one plugin install or update"),
    ("/plugins/tasks/{taskId}/log", "administrators: the log of a plugin install or update"),
    ("/system/update-check", "administrators: whether a newer ScipionWeb is out"),
]

_SEGMENT = r"[A-Za-z0-9_.\-]+"


def _pattern(template: str) -> "re.Pattern":
    escaped = re.escape(template.rstrip("/") or "/")
    return re.compile("^" + re.sub(r"\\\{[A-Za-z]+\\\}", _SEGMENT, escaped) + "/?$")


_PATTERNS = [(template, _pattern(template)) for template, _ in READ_ROUTES]


def catalogue() -> str:
    """The routes as the model reads them in the tool's description."""
    return "\n".join("%s: %s" % (template, what) for template, what in READ_ROUTES)


def allowedPath(path: str) -> Optional[str]:
    """The listed route the path is (None when it is not one), with "/api" and query strings refused."""
    path = str(path or "").strip()
    if not path.startswith("/"):
        path = "/" + path
    if path.startswith("/api/"):
        path = path[4:]
    if "?" in path or "#" in path or ".." in path or "//" in path:
        return None
    for template, pattern in _PATTERNS:
        if pattern.match(path):
            return template
    return None


def cleanQuery(template: str, query: Dict[str, Any]) -> Dict[str, str]:
    values = {str(key): str(value) for key, value in (query or {}).items() if value is not None}
    if template.endswith("/page"):
        try:
            values["pageSize"] = str(min(MAX_PAGE_SIZE, max(1, int(values.get("pageSize") or 20))))
        except ValueError:
            values["pageSize"] = "20"
    return values


class WebReader:
    """Reads a listed route as the user: send(path, query, headers) -> (status, content type, text) does the
    request (in the API itself; a test passes its own)."""

    def __init__(self, authorization: str, send: Optional[Callable[..., Tuple[int, str, str]]] = None):
        self.authorization = authorization or ""
        self._send = send or _sendInside

    def read(self, path: str, query: Optional[Dict[str, Any]] = None) -> Any:
        template = allowedPath(path)
        if template is None:
            raise ValueError("That page is not one the assistant may read; use one of the listed paths")
        if not path.startswith("/"):
            path = "/" + path
        if path.startswith("/api/"):
            path = path[4:]
        statusCode, contentType, text = self._send(path, cleanQuery(template, query or {}),
                                                   {"Authorization": self.authorization})
        if statusCode in (401, 403):
            raise PermissionError("The user may not see that")
        if statusCode == 404:
            raise ValueError("Not found: check the ids (list them first)")
        if statusCode >= 400:
            detail = text[:300]
            try:
                detail = str(json.loads(text).get("detail") or detail)[:300]
            except (ValueError, AttributeError):
                pass
            raise ValueError("The page answered an error (%d): %s" % (statusCode, detail))
        if "json" not in (contentType or ""):
            raise ValueError("That page is not data the assistant can read")
        return {"page": path, "data": json.loads(text)}


def _sendInside(path: str, query: Dict[str, str], headers: Dict[str, str]) -> Tuple[int, str, str]:
    from starlette.testclient import TestClient

    from app.backend.main import apiApp

    # One client per read: they are cheap, and one is not shared between the API's threads
    client = TestClient(apiApp, raise_server_exceptions=False)
    response = client.get(path, params=query, headers=headers)
    return response.status_code, response.headers.get("content-type", ""), response.text
