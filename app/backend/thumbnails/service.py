"""What the thumbnail routes do: list the thumbnails of a project and serve one.

Neither loads the project: the outputs come from the database (catalog), the
images from the signed disk cache (store), and the missing ones are drawn by
worker processes (scheduler).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response

from app.backend.thumbnails import catalog as thumbnailCatalog
from app.backend.thumbnails import scheduler, store

# How long an image request waits for its thumbnail to be drawn.
IMAGE_WAIT_SECONDS = 4.0
IMMUTABLE = "private, max-age=31536000, immutable"


def imageUrl(projectId: int, item: thumbnailCatalog.ThumbnailOutput, size: int) -> str:
    return (f"/projects/{int(projectId)}/protocols/{quote(item.protocolId, safe='')}/outputs/"
            f"{quote(item.outputName, safe='')}/thumbnail-image?size={int(size)}&sig={item.signature}")


def _state(path) -> str:
    if store.isReady(path):
        return "ready"
    if store.isMissing(path):
        return "unavailable"
    return "pending"


def listProjectThumbnails(
        mapper,
        projectId: int,
        projectPath: str,
        userId: int,
        scope: str = "card",
        size: int = 256,
        maxProtocols: int = 6,
        maxOutputsPerProtocol: int = 2,
) -> Dict[str, Any]:
    """The thumbnails of a project's card (its best protocols) or of every output (graph)."""
    size = store.snapSize(size)
    items = thumbnailCatalog.loadProjectThumbnailCatalog(mapper, projectId)
    if scope == "card":
        groups = thumbnailCatalog.selectProjectCardOutputs(items, maxProtocols, maxOutputsPerProtocol)
    else:
        byProtocol: Dict[str, List[thumbnailCatalog.ThumbnailOutput]] = {}
        for item in items:
            byProtocol.setdefault(item.protocolId, []).append(item)
        groups = list(byProtocol.values())

    toDraw: List[dict] = []
    payload: List[Dict[str, Any]] = []
    for group in groups:
        outputs = []
        for item in group:
            path = store.thumbnailPath(projectPath, item.protocolId, item.outputName, size, item.signature)
            state = _state(path)
            if state == "pending":
                toDraw.append({"protocolId": item.protocolId, "outputName": item.outputName,
                               "size": size, "path": str(path)})
            outputs.append({
                "outputName": item.outputName,
                "outputClassName": item.className,
                "signature": item.signature,
                "state": state,
                "url": imageUrl(projectId, item, size),
            })
        first = group[0]
        payload.append({
            "protocolId": first.protocolId,
            "label": first.protocolLabel,
            "status": first.protocolStatus,
            "outputs": outputs,
        })

    if toDraw:
        scheduler.schedule(projectId, userId, toDraw)
    return {"projectId": int(projectId), "size": size, "scope": scope, "groups": payload}


def _imageResponse(path, cacheControl: str) -> Response:
    return FileResponse(str(path), media_type="image/webp", headers={"Cache-Control": cacheControl})


def outputThumbnailImage(
        mapper,
        projectId: int,
        projectPath: str,
        userId: int,
        protocolId: str,
        outputName: str,
        size: int,
        signature: Optional[str],
        waitSeconds: float = IMAGE_WAIT_SECONDS,
) -> Response:
    """The thumbnail image; drawn first (waiting a little) when missing, 202 if still on its way."""
    size = store.snapSize(size)
    if signature:
        requested = store.thumbnailPath(projectPath, protocolId, outputName, size, signature)
        if store.isReady(requested):
            return _imageResponse(requested, IMMUTABLE)

    current = next((item for item in thumbnailCatalog.loadProjectThumbnailCatalog(mapper, projectId, protocolId)
                    if item.outputName == outputName), None)
    if current is None:
        raise HTTPException(status_code=404, detail="Output has no thumbnail")
    path = store.thumbnailPath(projectPath, current.protocolId, current.outputName, size, current.signature)
    # The URL names a signature: only the current one may be cached for good.
    cacheControl = IMMUTABLE if signature == current.signature else "private, no-cache"

    if not store.isReady(path) and not store.isMissing(path):
        futures = scheduler.schedule(projectId, userId, [{
            "protocolId": current.protocolId, "outputName": current.outputName, "size": size, "path": str(path),
        }])
        scheduler.waitFor(list(futures.values()), waitSeconds)

    if store.isReady(path):
        return _imageResponse(path, cacheControl)
    if store.isMissing(path):
        raise HTTPException(status_code=404, detail=store.readMissingReason(path) or "Thumbnail not available")
    return JSONResponse({"pending": True}, status_code=202, headers={"Retry-After": "1", "Cache-Control": "no-store"})
