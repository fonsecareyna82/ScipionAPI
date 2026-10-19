"""Routes over every project of the user (protocol activity)."""
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from app.backend.api.dependencies import getCurrentUser
from app.backend.api.services import workspace_service
from app.backend.database import getMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper

router = APIRouter(prefix="/workspace", tags=["workspace"])


def _userId(currentUser) -> int:
    return int(currentUser["id"] if isinstance(currentUser, dict) else getattr(currentUser, "id"))


@router.get("/protocol-activity", response_model=Any)
def getProtocolActivity(
    since: Optional[str] = Query(None, description="The 'now' of the previous call (ISO 8601); none for a first call."),
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    """Runs of the user's projects that ended (finished, failed, aborted, waiting) since the previous call."""
    sinceTime = None
    if since:
        try:
            sinceTime = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=422, detail="since must be an ISO 8601 time")
    payload = workspace_service.protocolActivity(mapper, _userId(currentUser), sinceTime)
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})
