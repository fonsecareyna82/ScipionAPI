# ******************************************************************************
# *
# * Authors:     Yunior C. Fonseca Reyna
# *
# * Unidad de  Bioinformatica of Centro Nacional de Biotecnologia , CSIC
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 3 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************
import asyncio
import base64
import logging
import multiprocessing
import os
import threading
from concurrent.futures import ProcessPoolExecutor
from time import perf_counter
from typing import Any, Dict
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response


logger = logging.getLogger(__name__)

_interactivePreviewExecutor = None
_backgroundThumbnailExecutor = None

_interactivePreviewExecutorLock = threading.Lock()
_backgroundThumbnailExecutorLock = threading.Lock()


def _createPreviewExecutor() -> ProcessPoolExecutor:
    return ProcessPoolExecutor(
        max_workers=1,
        mp_context=multiprocessing.get_context("spawn"),
    )


def _getInteractivePreviewExecutor() -> ProcessPoolExecutor:
    global _interactivePreviewExecutor

    if _interactivePreviewExecutor is not None:
        return _interactivePreviewExecutor

    with _interactivePreviewExecutorLock:
        if _interactivePreviewExecutor is None:
            _interactivePreviewExecutor = (
                _createPreviewExecutor()
            )

    return _interactivePreviewExecutor


def _getBackgroundThumbnailExecutor() -> ProcessPoolExecutor:
    global _backgroundThumbnailExecutor

    if _backgroundThumbnailExecutor is not None:
        return _backgroundThumbnailExecutor

    with _backgroundThumbnailExecutorLock:
        if _backgroundThumbnailExecutor is None:
            _backgroundThumbnailExecutor = (
                _createPreviewExecutor()
            )

    return _backgroundThumbnailExecutor


def _serializeResponse(value: Any) -> Dict[str, Any]:
    if isinstance(value, Response):
        return {
            "ok": True,
            "isResponse": True,
            "body": bytes(value.body or b""),
            "statusCode": int(value.status_code),
            "mediaType": value.media_type,
            "headers": dict(value.headers),
        }

    return {
        "ok": True,
        "isResponse": False,
        "value": value,
    }


def _deserializeResponse(result: Dict[str, Any]):
    if not result.get("ok"):
        raise HTTPException(
            status_code=int(result.get("statusCode") or 500),
            detail=result.get("detail") or "Preview process failed",
        )

    if not result.get("isResponse"):
        return result.get("value")

    headers = {
        key: value
        for key, value in (result.get("headers") or {}).items()
        if key.lower() not in {
            "content-length",
            "content-type",
        }
    }

    return Response(
        content=result.get("body") or b"",
        status_code=int(result.get("statusCode") or 200),
        media_type=result.get("mediaType"),
        headers=headers,
    )


def _runOutputPreviewJob(
    service,
    mapper,
    job: Dict[str, Any],
):
    currentUser = {
        "id": int(job["userId"]),
    }

    project = service.loadPostgresqlRuntimeProjectForMutation(
        mapper=mapper,
        projectId=int(job["projectId"]),
        currentUser=currentUser,
    )

    if not project:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    return service.outputPreview(
        protocolId=job["protocolId"],
        outputName=str(job["outputName"]),
        requestHeaders=dict(job.get("requestHeaders") or {}),
        colormap=job.get("colormap"),
        mapper=mapper,
        projectId=int(job["projectId"]),
    )


def _runOutputThumbnailsBatchJob(
    service,
    mapper,
    job: Dict[str, Any],
):
    projectId = int(job["projectId"])
    currentUser = {
        "id": int(job["userId"]),
    }

    requestStartedAt = perf_counter()
    projectLoadMs = 0.0
    thumbnailBuildMs = 0.0
    cacheHits = 0
    items = []

    dbProj = service.getProjectDbRow(
        mapper,
        projectId,
        currentUser,
    )

    if not dbProj:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    projectLoadStartedAt = perf_counter()

    service.loadProjectForThumbnails(
        dbProj,
        mapper=mapper,
    )

    projectLoadMs = (
        perf_counter()
        - projectLoadStartedAt
    ) * 1000

    thumbnailBuildStartedAt = perf_counter()
    seen = set()

    size = int(job["size"])
    inlineImages = bool(job["inlineImages"])

    for requestedOutput in job.get("outputs") or []:
        requestedProtocolId = int(
            requestedOutput["protocolId"]
        )

        outputName = str(
            requestedOutput.get("outputName")
            or ""
        ).strip()

        if not outputName:
            continue

        requestKey = (
            requestedProtocolId,
            outputName,
        )

        if requestKey in seen:
            continue

        seen.add(requestKey)

        item = {
            "protocolId": requestedProtocolId,
            "outputName": outputName,
            "outputClassName": None,
            "exists": False,
            "cached": False,
            "thumbnailUrl": (
                f"/projects/{projectId}/protocols/"
                f"{requestedProtocolId}/outputs/"
                f"{quote(outputName, safe='')}/thumbnail"
            ),
            "thumbnailDataUrl": None,
            "error": None,
        }

        try:
            result = service.buildProtocolOutputThumbnail(
                protocolId=requestedProtocolId,
                outputName=outputName,
                force=False,
                size=size,
                mapper=mapper,
                projectId=projectId,
            )

            item["outputClassName"] = result.get(
                "outputClassName"
            )

            if result.get("cached"):
                cacheHits += 1

        except Exception as error:
            logger.exception(
                "Failed building protocol output thumbnail "
                "in preview process. "
                "projectId=%s protocolId=%s outputName=%s",
                projectId,
                requestedProtocolId,
                outputName,
            )

            item["error"] = str(error)
            items.append(item)
            continue

        thumbPath = result.get(
            "absolutePath"
        )

        if (
            not result.get("exists")
            or not thumbPath
        ):
            item["error"] = (
                "Thumbnail not available"
            )

            items.append(item)
            continue

        item["exists"] = True
        item["cached"] = bool(
            result.get("cached")
        )

        if inlineImages:
            try:
                if (
                    os.path.exists(
                        str(thumbPath)
                    )
                    and
                    os.path.getsize(
                        str(thumbPath)
                    ) > 0
                ):
                    with open(
                        str(thumbPath),
                        "rb",
                    ) as fileHandle:
                        encoded = (
                            base64
                            .b64encode(
                                fileHandle.read()
                            )
                            .decode("ascii")
                        )

                    item["thumbnailDataUrl"] = (
                        "data:image/png;base64,"
                        + encoded
                    )

            except Exception:
                logger.exception(
                    "Could not inline protocol "
                    "output thumbnail. "
                    "projectId=%s protocolId=%s "
                    "outputName=%s",
                    projectId,
                    requestedProtocolId,
                    outputName,
                )

        items.append(item)

    thumbnailBuildMs = (
        perf_counter()
        - thumbnailBuildStartedAt
    ) * 1000

    response = JSONResponse({
        "projectId": projectId,
        "size": size,
        "items": items,
    })

    totalMs = (
        perf_counter()
        - requestStartedAt
    ) * 1000

    response.headers[
        "Cache-Control"
    ] = (
        "private, max-age=60, "
        "stale-while-revalidate=300"
    )

    response.headers[
        "Server-Timing"
    ] = (
        f"project;dur={projectLoadMs:.1f}, "
        f"thumbnails;dur={thumbnailBuildMs:.1f}, "
        f"total;dur={totalMs:.1f}"
    )

    response.headers[
        "X-Thumbnail-Items"
    ] = str(len(items))

    response.headers[
        "X-Thumbnail-Cache-Hits"
    ] = str(cacheHits)

    response.headers[
        "Access-Control-Expose-Headers"
    ] = (
        "Cache-Control, Server-Timing, "
        "X-Thumbnail-Items, "
        "X-Thumbnail-Cache-Hits"
    )

    return response


def _runPreviewJob(
    job: Dict[str, Any],
) -> Dict[str, Any]:
    from app.backend.api.services.project_service import ProjectService
    from app.backend.database import getMapper

    mapper = None
    service = None

    try:
        mapper = getMapper()
        service = ProjectService()

        operation = str(
            job.get("operation")
            or ""
        )

        if operation == "output-preview":
            value = _runOutputPreviewJob(
                service,
                mapper,
                job,
            )

        elif operation == "output-thumbnails-batch":
            value = _runOutputThumbnailsBatchJob(
                service,
                mapper,
                job,
            )

        else:
            raise RuntimeError(
                f"Unknown preview operation: {operation}"
            )

        return _serializeResponse(
            value
        )

    except HTTPException as error:
        return {
            "ok": False,
            "statusCode": error.status_code,
            "detail": error.detail,
        }

    except Exception as error:
        logger.exception(
            "Preview process job failed. "
            "operation=%s",
            job.get("operation"),
        )

        return {
            "ok": False,
            "statusCode": 500,
            "detail": str(error),
        }

    finally:
        if service is not None:
            try:
                service.clearCurrentProject()
            except Exception:
                pass

        if mapper is not None:
            try:
                mapper.db.close()
            except Exception:
                pass


async def runOutputPreviewInProcess(
    *,
    projectId: int,
    protocolId,
    outputName: str,
    userId: int,
    requestHeaders: Dict[str, str],
    colormap=None,
):
    loop = asyncio.get_running_loop()

    result = await loop.run_in_executor(
        _getInteractivePreviewExecutor(),
        _runPreviewJob,
        {
            "operation": "output-preview",
            "projectId": int(projectId),
            "protocolId": protocolId,
            "outputName": outputName,
            "userId": int(userId),
            "requestHeaders": requestHeaders,
            "colormap": colormap,
        },
    )

    return _deserializeResponse(
        result
    )


async def runOutputThumbnailsBatchInProcess(
    *,
    projectId: int,
    userId: int,
    size: int,
    inlineImages: bool,
    outputs,
):
    loop = asyncio.get_running_loop()

    result = await loop.run_in_executor(
        _getBackgroundThumbnailExecutor(),
        _runPreviewJob,
        {
            "operation":
                "output-thumbnails-batch",
            "projectId": int(projectId),
            "userId": int(userId),
            "size": int(size),
            "inlineImages": bool(
                inlineImages
            ),
            "outputs": list(outputs),
        },
    )

    return _deserializeResponse(
        result
    )