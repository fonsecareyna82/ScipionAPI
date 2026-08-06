"""Shared 404 for preview/viewer endpoints whose PostgreSQL-backed output
metadata isn't available. Used across every preview-by-type service."""
import logging
from typing import Optional, Union

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def raisePostgresqlViewerUnavailable(
        viewerName: str,
        projectId: int,
        protocolId: Union[int, str],
        outputName: str,
        reason: Optional[str] = None,
        **extra,
) -> None:
    extraText = " ".join(
        "%s=%s" % (key, value)
        for key, value in extra.items()
        if value is not None
    )

    logger.warning(
        "%s output is not available in PostgreSQL metadata. projectId=%s protocolId=%s outputName=%s reason=%s %s",
        viewerName,
        projectId,
        protocolId,
        outputName,
        reason,
        extraText,
    )

    detail = "%s output is not available in PostgreSQL metadata" % viewerName
    if reason:
        detail = "%s: %s" % (detail, reason)

    raise HTTPException(
        status_code=404,
        detail=detail,
    )
