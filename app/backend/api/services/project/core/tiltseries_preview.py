"""Building summary rows for TiltSeries preview, resolving frame paths,
caching rendered tilt-series preview images, and constructing the
PostgreSQL TiltSeries reader when available.
"""
import collections
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from fastapi import HTTPException, Response

# In-memory cache for rendered tilt-series previews.
# The key includes file path, mtime and render options, so changed stacks invalidate naturally.
_tiltSeriesPreviewCacheLock = threading.Lock()
_tiltSeriesPreviewCache = collections.OrderedDict()
_TILT_SERIES_PREVIEW_CACHE_LIMIT = 160


def buildTiltSeriesSummary(ts) -> Dict[str, Any]:
    """Build a JSON-friendly summary for one tilt series."""
    tsId = ts.getTsId()
    label = f"TiltSeries {tsId}"
    nViews = ts.getSize()
    dims = ts.getDim()
    pixelSize = ts.getSamplingRate()
    tiltAxisAngle = ts.getAcquisition().getTiltAxisAngle()
    item: Dict[str, Any] = {
        "tiltSeriesId": tsId,
        "label": str(label),
    }
    if nViews is not None:
        item["nViews"] = nViews
    if dims is not None:
        item["dims"] = dims
    if pixelSize is not None:
        item["pixelSize"] = pixelSize
    if tiltAxisAngle is not None:
        item["tiltAxisAngle"] = tiltAxisAngle

    return item


def parseTiltSeriesFramePath(
        framePath: Any,
        fallbackIndex: int,
) -> Tuple[str, int]:
    pathText = str(framePath or "").strip()
    if not pathText:
        raise HTTPException(
            status_code=404,
            detail="Tilt image path not found in PostgreSQL metadata",
        )

    imageIndex = int(fallbackIndex)
    imagePath = pathText

    if "@" in pathText:
        indexText, imagePath = pathText.split("@", 1)
        try:
            imageIndex = int(float(indexText))
        except Exception:
            imageIndex = int(fallbackIndex)

    # Do not os.path.abspath() here.
    # PostgreSQL paths can be project-relative:
    # Runs/000084_Prot.../extra/...
    # They must be resolved against the project path, not against cwd/scipion_home.
    return str(Path(str(imagePath)).expanduser()), imageIndex


def cloneTiltImage(ti, included):
    newTi = ti.clone()
    newTi.copyInfo(ti, copyId=False)
    newTi.setObjId(None)
    newTi.setAcquisition(ti.getAcquisition())
    newTi.setEnabled(included)
    return newTi


def buildPostgresqlTiltSeriesReader(mapper, projectId: int, protocolId, outputName: str):
    """protocolId here is expected to already be resolved for reader use
    (see ProjectService._resolvePostgresqlReaderProtocolId)."""
    from app.backend.viewers.postgresql_tiltseries_reader import PostgresqlTiltSeriesReader

    reader = PostgresqlTiltSeriesReader(
        db=mapper.db,
        projectId=projectId,
        protocolId=protocolId,
        outputName=outputName,
    )

    if reader.hasOutput():
        return reader

    return None


def buildTiltSeriesPreviewCacheKey(
        projectId: int,
        protocolId: int,
        outputName: str,
        tiltSeriesId: Union[int, str],
        index: int,
        size: int,
        fmt: str,
        applyTransform: bool,
        inline: bool,
        imagePath: str,
) -> Tuple[Any, ...]:
    absPath = os.path.abspath(str(imagePath))

    try:
        stat = os.stat(absPath)
        fileMtimeNs = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)))
        fileSize = int(stat.st_size)
    except Exception:
        fileMtimeNs = 0
        fileSize = 0

    return (
        int(projectId),
        int(protocolId),
        str(outputName),
        str(tiltSeriesId),
        int(index),
        int(size),
        str(fmt or "png").lower(),
        bool(applyTransform),
        bool(inline),
        absPath,
        fileMtimeNs,
        fileSize,
    )


def ensureTiltSeriesPreviewCacheHeader(
        headers: Dict[str, str],
        cacheState: str,
) -> Dict[str, str]:
    nextHeaders = dict(headers or {})
    nextHeaders["X-Preview-Cache"] = cacheState

    exposeRaw = nextHeaders.get("Access-Control-Expose-Headers", "")
    exposeItems = [h.strip() for h in exposeRaw.split(",") if h.strip()]
    if "X-Preview-Cache" not in exposeItems:
        exposeItems.append("X-Preview-Cache")
    nextHeaders["Access-Control-Expose-Headers"] = ", ".join(exposeItems)

    return nextHeaders


def getTiltSeriesPreviewFromCache(cacheKey: Tuple[Any, ...]) -> Optional[Response]:
    with _tiltSeriesPreviewCacheLock:
        cached = _tiltSeriesPreviewCache.get(cacheKey)
        if not cached:
            return None

        _tiltSeriesPreviewCache.move_to_end(cacheKey)

        headers = ensureTiltSeriesPreviewCacheHeader(
            cached.get("headers") or {},
            "HIT",
        )

        return Response(
            content=cached.get("body") or b"",
            media_type=cached.get("mediaType") or "image/png",
            headers=headers,
        )


def storeTiltSeriesPreviewInCache(
        cacheKey: Tuple[Any, ...],
        response: Any,
) -> Any:
    headersObj = getattr(response, "headers", None)
    if headersObj is None or not hasattr(headersObj, "update"):
        return response

    body = getattr(response, "body", None)

    if body is None:
        response.headers.update(
            ensureTiltSeriesPreviewCacheHeader(
                dict(response.headers),
                "SKIP",
            )
        )
        return response

    headers = dict(response.headers)
    headers.pop("content-length", None)
    headers.pop("Content-Length", None)

    mediaType = getattr(response, "media_type", None) or headers.get("content-type") or "image/png"

    with _tiltSeriesPreviewCacheLock:
        _tiltSeriesPreviewCache[cacheKey] = {
            "body": bytes(body),
            "headers": headers,
            "mediaType": mediaType,
        }
        _tiltSeriesPreviewCache.move_to_end(cacheKey)

        while len(_tiltSeriesPreviewCache) > _TILT_SERIES_PREVIEW_CACHE_LIMIT:
            _tiltSeriesPreviewCache.popitem(last=False)

    response.headers.update(
        ensureTiltSeriesPreviewCacheHeader(
            dict(response.headers),
            "MISS",
        )
    )

    return response
