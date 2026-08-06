"""Resolving a volume file from an output, reading it into numpy, caching
rendered slice previews, and constructing the PostgreSQL volume reader
when available.
"""
import collections
import os
import threading
from typing import Any, Optional, Union

import numpy as np
from fastapi import HTTPException, Response
from pwem.emlib.image.image_readers import ImageReadersRegistry

_VOLUME_SLICE_CACHE_LOCK = threading.Lock()
_VOLUME_SLICE_CACHE = collections.OrderedDict()
_VOLUME_SLICE_CACHE_MAX_ITEMS = 128


def isVolumeLikeImageFile(filePath: Union[str, Any]) -> bool:
    try:
        reader = ImageReadersRegistry.open(str(filePath))
        data = reader.getImages()

        if isinstance(data, list):
            data = data[0]

        return getattr(data, "ndim", 0) == 3 and data.shape[0] > 1
    except Exception:
        return False


def getVolumePathFromOutput(output, volumeId: Union[int, str], setOfVolumesClass) -> str:
    """Resolve a concrete volume path from an output (Volume / SetOfVolumes / VolumeMask).

    setOfVolumesClass is passed in explicitly (rather than imported here) so
    the caller's own SetOfVolumes binding - the one tests monkeypatch - is
    the one actually used for the isinstance check.
    """
    if isinstance(output, setOfVolumesClass):
        try:
            vid = int(volumeId)
        except Exception:
            raise HTTPException(status_code=400, detail="volumeId must be an integer")

        item = output.getItem('_objId', vid + 1)
        if item is None:
            raise HTTPException(status_code=404, detail="Volume not found in SetOfVolumes")
        volumePath = item.getFileName()
    else:
        getFileNameFn = getattr(output, "getFileName", None)
        if not callable(getFileNameFn):
            raise HTTPException(status_code=404, detail="Output has no getFileName()")
        volumePath = getFileNameFn()

    if not volumePath or not os.path.exists(volumePath):
        raise HTTPException(status_code=404, detail="Volume file not found on disk")

    return volumePath


def readVolumeAsNumpy(volumePath: str) -> np.ndarray:
    """
    Read a volume file into a numpy array (Z,Y,X).
    Tries Scipion/pwem readers first, falls back to mrcfile/numpy when possible.
    """
    ext = os.path.splitext(volumePath)[1].lower()

    # Numpy formats
    if ext in (".npy",):
        arr = np.load(volumePath)
        return np.asarray(arr, dtype=np.float32)

    if ext in (".npz",):
        zf = np.load(volumePath)
        for k in ("data", "volume", "arr_0"):
            if k in zf:
                return np.asarray(zf[k], dtype=np.float32)
        firstKey = list(zf.keys())[0]
        return np.asarray(zf[firstKey], dtype=np.float32)

    # Try Scipion image readers registry
    try:
        reader = ImageReadersRegistry.getReader(volumePath)
        if reader is not None:
            data = reader.read(volumePath)
            return np.asarray(data, dtype=np.float32)
    except Exception:
        pass

    # Try pwem ImageHandler
    try:
        from pwem.emlib.image import ImageHandler
        ih = ImageHandler()
        ih.read(volumePath)
        data = ih.getData()
        return np.asarray(data, dtype=np.float32)
    except Exception:
        pass

    # Last resort: mrcfile if available
    try:
        import mrcfile
        with mrcfile.open(volumePath, permissive=True) as m:
            data = m.data
        return np.asarray(data, dtype=np.float32)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Cannot read volume file '{volumePath}': {e}",
        )


def buildPostgresqlVolumeReader(mapper, projectId: int, protocolId, outputName: str, logger):
    """protocolId here is expected to already be resolved for reader use
    (see ProjectService._resolvePostgresqlReaderProtocolId)."""
    try:
        from app.backend.viewers.postgresql_coords3d_tomogram_volume_reader import \
            PostgresqlCoords3dTomogramVolumeReader

        reader = PostgresqlCoords3dTomogramVolumeReader(
            db=mapper.db,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )

        if reader.hasOutput():
            return reader

    except Exception:
        logger.debug(
            "PostgreSQL Coords3D-derived tomogram volume reader is not available. projectId=%s protocolId=%s outputName=%s",
            projectId,
            protocolId,
            outputName,
            exc_info=True,
        )

    try:
        from app.backend.viewers.postgresql_volume_reader import PostgresqlVolumeReader

        reader = PostgresqlVolumeReader(
            db=mapper.db,
            projectId=projectId,
            protocolId=protocolId,
            outputName=outputName,
        )

        if reader.hasOutput():
            return reader

    except Exception:
        logger.exception(
            "Failed to initialize PostgreSQL volume reader. projectId=%s protocolId=%s outputName=%s",
            projectId,
            protocolId,
            outputName,
        )

    return None


def exposeHeader(headers, headerName: str) -> None:
    exposeKey = "Access-Control-Expose-Headers"
    current = headers.get(exposeKey, "")
    parts = [h.strip() for h in str(current).split(",") if h.strip()]

    if headerName not in parts:
        parts.append(headerName)

    headers[exposeKey] = ", ".join(parts)


def buildVolumeSliceCacheKey(
        *,
        volumePath: str,
        tomogramId: Union[int, str],
        sliceIndex: int,
        axis: str,
        colormap: Optional[str],
        normalize: Optional[str],
        scale: float,
        fmt: str,
        thumb: Optional[int],
        fast: bool,
        quality: int,
):
    try:
        stat = os.stat(volumePath)
        mtimeNs = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))
        sizeBytes = int(stat.st_size)
    except Exception:
        mtimeNs = None
        sizeBytes = None

    return (
        os.path.abspath(str(volumePath)),
        mtimeNs,
        sizeBytes,
        str(tomogramId),
        int(sliceIndex),
        str(axis or "z").lower(),
        str(colormap or ""),
        str(normalize or "minmax").lower(),
        float(scale or 1.0),
        str(fmt or "webp").lower(),
        int(thumb or 0),
        bool(fast),
        int(quality or 75),
    )


def getCachedVolumeSliceResponse(cacheKey) -> Optional[Response]:
    with _VOLUME_SLICE_CACHE_LOCK:
        cached = _VOLUME_SLICE_CACHE.get(cacheKey)
        if cached is None:
            return None

        _VOLUME_SLICE_CACHE.move_to_end(cacheKey)

    headers = dict(cached.get("headers") or {})
    headers.pop("content-length", None)
    headers.pop("Content-Length", None)

    headers["X-Preview-Cache"] = "hit"
    exposeHeader(headers, "X-Preview-Cache")

    return Response(
        content=cached["body"],
        media_type=cached.get("mediaType") or "image/webp",
        headers=headers,
    )


def storeCachedVolumeSliceResponse(cacheKey, response: Response) -> Response:
    body = getattr(response, "body", None)
    if body is None:
        return response

    headers = dict(response.headers)
    headers.pop("content-length", None)
    headers.pop("Content-Length", None)

    mediaType = getattr(response, "media_type", None) or headers.get("content-type")

    with _VOLUME_SLICE_CACHE_LOCK:
        _VOLUME_SLICE_CACHE[cacheKey] = {
            "body": bytes(body),
            "headers": headers,
            "mediaType": mediaType,
        }
        _VOLUME_SLICE_CACHE.move_to_end(cacheKey)

        while len(_VOLUME_SLICE_CACHE) > _VOLUME_SLICE_CACHE_MAX_ITEMS:
            _VOLUME_SLICE_CACHE.popitem(last=False)

    response.headers["X-Preview-Cache"] = "miss"
    exposeHeader(response.headers, "X-Preview-Cache")

    return response
