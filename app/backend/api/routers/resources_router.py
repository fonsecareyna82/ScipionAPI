"""What the machines have in use right now, for every signed-in user (with the privacy of resources.py)."""
from typing import Any, Dict

from fastapi import APIRouter, Depends, Query

from app.backend.api.dependencies import getCurrentUser
from app.backend.api.services import resources
from app.backend.api.services.job_monitoring_service import JobMonitoringService
from app.backend.database import getMapperDependency
from app.backend.mapper.postgresql import PostgresqlFlatMapper

router = APIRouter(prefix="/resources", tags=["Resources"])


def getJobMonitoringService() -> JobMonitoringService:
    return JobMonitoringService()


@router.get("")
def getResources(timeout: float = Query(2.0, ge=0.5, le=10.0),
                 currentUser: dict = Depends(getCurrentUser),
                 mapper: PostgresqlFlatMapper = Depends(getMapperDependency),
                 service: JobMonitoringService = Depends(getJobMonitoringService)) -> Dict[str, Any]:
    """Each machine now (as its workers report it), the runs going on and the protocols waiting."""
    reports, error = service.getNodeResources(timeout=timeout)
    return resources.resourcesView(mapper.db, currentUser, reports, available=bool(reports), error=error)
