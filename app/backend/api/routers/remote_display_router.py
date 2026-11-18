"""Desktop programs opened on the server and shown in the browser (see services/remote_display_service.py).

Opening, listing and closing need the signed-in user. The page and the connection of a session
(/remote-displays/<session id>/...) are opened by the browser itself, which sends no Authorization header there:
the session id, long and random, is their key.
"""
import asyncio
import ipaddress
import os
import socket
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel

from app.backend.api.dependencies import getCurrentUser
from app.backend.api.project_access import projectRouteAccess
from app.backend.api.services import remote_display_service as displays
from app.backend.api.routers.project_router import getProjectService
from app.backend.api.services.project_service import ProjectService
from app.backend.database import getMapperDependency as getMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper

router = APIRouter(tags=["Remote displays"])

_ERROR_STATUS = {"unavailable": 503, "too_many": 409, "not_found": 404, "start_failed": 502, "no_files": 422}
_MAX_VOLUMES = 20
# Headers of Xpra's answers that the browser gets as they are
_PASSED_HEADERS = ("content-type", "cache-control", "etag", "last-modified")


class OpenVolumesRequest(BaseModel):
    program: str = "volumes"


def _error(exc: displays.RemoteDisplayError) -> HTTPException:
    return HTTPException(status_code=_ERROR_STATUS.get(exc.code, 500), detail={"code": exc.code, "message": str(exc)})


def _volumeProgram() -> List[str]:
    """The program that opens volumes, as its plugin installed it; [] when it is not installed."""
    try:
        from pwem import Domain
        plugin = Domain.getPluginModule("chimera").Plugin
        program = plugin.getProgram()
    except Exception:
        return []
    return [program] if program and os.path.isfile(program) else []


def _thisMachineAddresses() -> set:
    addresses = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            addresses.add(info[4][0])
    except OSError:
        pass
    return addresses


def _hasOwnScreen() -> bool:
    """Whether the API shows programs on a screen of this machine. A display forwarded through SSH (localhost:10.0,
    from a login with ssh -X) is the screen of another machine, and goes away with that login."""
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    display = (os.environ.get("DISPLAY") or "").strip()
    return display.startswith(":") or display.startswith("unix:")


def _connectionOwner(clientPort: Any, serverPort: Any) -> Any:
    """The account of this machine that opened a connection to the API, from the kernel's table of open
    connections (Linux). None when it cannot be told."""
    if not clientPort or not serverPort:
        return None
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(table) as handle:
                next(handle, None)
                for line in handle:
                    fields = line.split()
                    if len(fields) < 8:
                        continue
                    local, remote = fields[1], fields[2]
                    if (int(local.rsplit(":", 1)[1], 16) == int(clientPort)
                            and int(remote.rsplit(":", 1)[1], 16) == int(serverPort)):
                        return int(fields[7])
        except (OSError, ValueError):
            continue
    return None


def _browserIsOnThisMachine(request: Request) -> bool:
    """Whether the browser runs on the machine of the API, in front of its screen (then programs open there)."""
    if not _hasOwnScreen():
        return False  # no screen here: nobody sits in front of it
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    host = forwarded or (request.client.host if request.client else "")
    if not host:
        return False
    try:
        if not ipaddress.ip_address(host).is_loopback and host not in _thisMachineAddresses():
            return False
    except ValueError:
        return False
    if not forwarded:
        # Another account logged in on this machine sits in front of its own screen, where programs of the
        # account that runs the API are not allowed to draw: show them in the browser instead
        scope = getattr(request, "scope", None) or {}
        server = scope.get("server") or (None, None)
        owner = _connectionOwner(getattr(request.client, "port", None), server[1])
        if owner is not None and owner != os.getuid():
            return False
    return True


@router.get("/remote-displays/available")
def remoteDisplaysAvailable(request: Request, currentUser: dict = Depends(getCurrentUser)) -> Dict[str, Any]:
    """Whether programs are shown in the browser, and which. Not when the browser is on this machine: there the
    programs open on its own screen, as before."""
    xpra = bool(displays.xpraExecutable()) and not _browserIsOnThisMachine(request)
    return {"available": xpra, "programs": {"volumes": xpra and bool(_volumeProgram())}}


@router.get("/remote-displays")
def listMyRemoteDisplays(currentUser: dict = Depends(getCurrentUser)) -> List[Dict[str, Any]]:
    return [displays.publicView(s) for s in displays.listSessions(int(currentUser["id"]))]


@router.delete("/remote-displays/{sessionId}", status_code=204)
def closeRemoteDisplay(sessionId: str, currentUser: dict = Depends(getCurrentUser)) -> Response:
    try:
        displays.stopSession(sessionId, int(currentUser["id"]))
    except displays.RemoteDisplayError as exc:
        raise _error(exc) from None
    return Response(status_code=204)


@router.post("/projects/{projectId}/protocols/{protocolId}/outputs/{outputName}/remote-display",
             dependencies=[Depends(projectRouteAccess(getMapper))])
def openOutputInRemoteDisplay(
    projectId: int,
    protocolId: int,
    outputName: str,
    body: OpenVolumesRequest,
    currentUser: dict = Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: ProjectService = Depends(getProjectService),
) -> Dict[str, Any]:
    """Open the volumes of an output (a volume or a set of them) in the desktop 3D viewer, on this server."""
    project = service.getProjectDbRow(mapper, projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    program = _volumeProgram()
    if not program:
        raise _error(displays.RemoteDisplayError("unavailable", "The desktop 3D viewer is not installed"))

    reader = service._getPostgresqlVolumeReaderIfAvailable(
        mapper=mapper, projectId=projectId, protocolId=protocolId, outputName=outputName,
        protocolIdIsScipionId=True)
    files = []
    for volume in (reader.listVolumes() if reader is not None else None) or []:
        volumeId = volume.get("id")
        if isinstance(volumeId, str) and volumeId.startswith("half"):
            continue  # half maps are opened by hand when wanted
        info = reader.getVolumeFile(volumeId)
        if info and info.get("fileName"):
            files.append(info["fileName"])
        if len(files) >= _MAX_VOLUMES:
            break
    if not files:
        raise _error(displays.RemoteDisplayError("no_files", "This output has no volume file to open"))

    title = f"{outputName} (#{protocolId})"
    try:
        session = displays.startSession(
            userId=int(currentUser["id"]), projectId=projectId, title=title,
            command=displays.programCommand(program[0], files),
            cwd=str(project.get("name") or "") or None)
    except displays.RemoteDisplayError as exc:
        raise _error(exc) from None
    return displays.publicView(session)


def _sessionOr404(sessionId: str) -> Dict[str, Any]:
    session = displays.getSession(sessionId)
    if not session:
        raise HTTPException(status_code=404, detail="This window is closed")
    return session


@router.get("/remote-displays/{sessionId}/{path:path}")
async def remoteDisplayPage(sessionId: str, path: str, request: Request) -> Response:
    """The page (and its scripts and styles) that shows the window, as Xpra serves it."""
    import httpx  # here, so that the rest of the API starts without it

    session = _sessionOr404(sessionId)
    url = f"http://127.0.0.1:{session['port']}/{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        upstream = await client.get(url, params=dict(request.query_params))
    headers = {k: v for k, v in upstream.headers.items() if k.lower() in _PASSED_HEADERS}
    headers["X-Frame-Options"] = "SAMEORIGIN"
    content = upstream.content
    if request.query_params.get("embed") == "1" and path in ("", "index.html") and b"</body>" in content:
        # Inside a window of the web: only the program, filling it
        content = content.replace(b"</body>", _EMBED_SNIPPET.encode("utf-8") + b"</body>", 1)
        headers["Cache-Control"] = "no-store"
    return Response(content=content, status_code=upstream.status_code, headers=headers)


# Xpra's page shows the server's windows over a desktop with a menu. Inside a window of the web, its desktop, menu
# and title bars go, and each main window of the program (not its dialogs) is kept maximized: the program fills the
# window of the web and follows its size. The page tells the web how many main windows are left (0: it closed).
_EMBED_SNIPPET = """
<style>
  #float_menu, #float_tray, #open_windows, #window_preview, #shadow_pointer, #progress { display: none !important; }
  html, body, #screen { background: #fff !important; background-image: none !important; overflow: hidden !important; }
  .sw-main .windowhead { display: none !important; }
  .sw-main { border: 0 !important; box-shadow: none !important; border-radius: 0 !important; }
</style>
<script>
(function () {
  function isMain(w) {
    if (w.override_redirect || w.tray) return false;
    if (w.metadata && w.metadata["transient-for"]) return false;
    var type = String(w.windowtype || "NORMAL").toUpperCase();
    return type.indexOf("NORMAL") >= 0;
  }
  var reported = -1;
  var seen = false;
  setInterval(function () {
    var c = window.client;
    if (!c || !c.id_to_window) return;
    var mains = 0;
    for (var id in c.id_to_window) {
      var w = c.id_to_window[id];
      if (!w || !isMain(w)) continue;
      mains += 1;
      if (w.div && w.div.classList && !w.div.classList.contains("sw-main")) w.div.classList.add("sw-main");
      // Without its title bar, so that maximized it starts at the top
      if (w.decorated && typeof w._set_decorated === "function") {
        w.decorations = false;
        w._set_decorated(false);
        if (w.maximized && typeof w.set_maximized === "function") w.set_maximized(false);
      }
      if (!w.maximized && typeof w.set_maximized === "function") w.set_maximized(true);
    }
    // No window yet is the program still starting, not closed
    if (mains > 0) seen = true;
    if (!seen) return;
    if (mains !== reported && window.parent !== window) {
      reported = mains;
      window.parent.postMessage({ type: "scipion-remote-display", windows: mains }, window.location.origin);
    }
  }, 400);
})();
</script>
"""


@router.websocket("/remote-displays/{sessionId}/{path:path}")
async def remoteDisplayConnection(websocket: WebSocket, sessionId: str, path: str) -> None:
    """The window's picture, keyboard and mouse, passed between the browser and Xpra as they come."""
    session = displays.getSession(sessionId)
    if not session:
        await websocket.close(code=4404)
        return
    try:
        import websockets  # here, so that the rest of the API starts without it
    except ImportError:
        await websocket.close(code=1011)
        return
    offered = websocket.scope.get("subprotocols") or []
    subprotocol = "binary" if "binary" in offered else None
    try:
        upstream = await websockets.connect(f"ws://127.0.0.1:{session['port']}/",
                                            subprotocols=["binary"], max_size=None, ping_interval=None)
    except Exception:
        await websocket.close(code=1011)
        return
    await websocket.accept(subprotocol=subprotocol)

    async def toXpra() -> None:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            data = message.get("bytes")
            await upstream.send(data if data is not None else message.get("text") or "")

    async def toBrowser() -> None:
        async for data in upstream:
            if isinstance(data, bytes):
                await websocket.send_bytes(data)
            else:
                await websocket.send_text(data)

    tasks = [asyncio.ensure_future(toXpra()), asyncio.ensure_future(toBrowser())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for task in tasks:
            task.cancel()
        await upstream.close()
        try:
            await websocket.close()
        except Exception:
            pass
