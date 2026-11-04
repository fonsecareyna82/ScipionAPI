"""The disk the projects use, for those who may see it (each user sees their own in the project list)."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.backend.api.permissions import requirePermission
from app.backend.api.services import project_storage
from app.backend.database import getMapperDependency
from app.backend.mapper.postgresql import PostgresqlFlatMapper

router = APIRouter(prefix="/storage", tags=["Storage"])


class MeasurePayload(BaseModel):
    # Without any, every project
    projectIds: Optional[List[int]] = None


@router.get("/usage")
def getStorageUsage(currentUser: dict = Depends(requirePermission("storage.view")),
                    mapper: PostgresqlFlatMapper = Depends(getMapperDependency)) -> Dict[str, Any]:
    """Every project's last measure, summed by user and by group, and the projects' disk."""
    return project_storage.usageReport(mapper.db, project_storage.projectsRoot())


@router.post("/measure")
def measureStorage(payload: MeasurePayload, currentUser: dict = Depends(requirePermission("storage.view")),
                   mapper: PostgresqlFlatMapper = Depends(getMapperDependency)) -> Dict[str, Any]:
    """Measure these projects again (all of them, without ids), as soon as the measurer can."""
    project_storage.requestMeasure(mapper.db, payload.projectIds)
    return {"requested": True}
