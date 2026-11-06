"""The computing each user, group, protocol and machine used, for those who may see it; each user sees their own."""
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.backend.api.permissions import requirePermission
from app.backend.api.services import compute_usage
from app.backend.database import getMapperDependency
from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.api.dependencies import getCurrentUser

router = APIRouter(prefix="/usage", tags=["Usage"])


def _call(function, *args, **kwargs) -> Dict[str, Any]:
    try:
        return function(*args, **kwargs)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get("/compute")
def getComputeUsage(since: Optional[datetime] = Query(None), until: Optional[datetime] = Query(None),
                    currentUser: dict = Depends(requirePermission("storage.view")),
                    mapper: PostgresqlFlatMapper = Depends(getMapperDependency)) -> Dict[str, Any]:
    """The runs of the period (this month without one) summed in all and by user, group, protocol and machine."""
    return _call(compute_usage.usageReport, mapper.db, since, until)


@router.get("/compute/users/{userId}/runs")
def getUserRuns(userId: int, since: Optional[datetime] = Query(None), until: Optional[datetime] = Query(None),
                currentUser: dict = Depends(requirePermission("storage.view")),
                mapper: PostgresqlFlatMapper = Depends(getMapperDependency)) -> Dict[str, Any]:
    """One user's runs in the period, the newest first."""
    return _call(compute_usage.userRuns, mapper.db, userId, since, until)


@router.get("/compute/me")
def getOwnComputeUsage(since: Optional[datetime] = Query(None), until: Optional[datetime] = Query(None),
                       currentUser: dict = Depends(getCurrentUser),
                       mapper: PostgresqlFlatMapper = Depends(getMapperDependency)) -> Dict[str, Any]:
    """What the user used in the period, in all."""
    return _call(compute_usage.ownUsage, mapper.db, int(currentUser["id"]), since, until)
