"""The disk the projects use, for those who may see it (each user sees their own in the project list)."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.backend.api.dependencies import getCurrentUser
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


class QuotaPayload(BaseModel):
    kind: str
    targetId: int
    # None removes the quota
    limitBytes: Optional[int] = None


@router.get("/quotas")
def listStorageQuotas(currentUser: dict = Depends(requirePermission("storage.view")),
                      mapper: PostgresqlFlatMapper = Depends(getMapperDependency)) -> List[Dict[str, Any]]:
    """The disk quotas, with how much of each is used."""
    from app.backend.api.services import storage_quotas

    return storage_quotas.listQuotas(mapper.db)


@router.put("/quotas")
def saveStorageQuota(payload: QuotaPayload, currentUser: dict = Depends(requirePermission("settings.manage")),
                     mapper: PostgresqlFlatMapper = Depends(getMapperDependency)) -> List[Dict[str, Any]]:
    """Set (or remove, with no limit) the disk quota of a user or a group."""
    from app.backend.api.audit import recordAudit
    from app.backend.api.services import storage_quotas

    quotas = storage_quotas.saveQuota(mapper.db, payload.kind, payload.targetId, payload.limitBytes,
                                      currentUser.get("id"))
    recordAudit(mapper, currentUser, "storage.quotaUpdated", payload.kind, payload.targetId, None,
                {"limitBytes": payload.limitBytes})
    return quotas


@router.get("/quotas/me")
def myStorageQuotas(currentUser: dict = Depends(getCurrentUser),
                    mapper: PostgresqlFlatMapper = Depends(getMapperDependency)) -> List[Dict[str, Any]]:
    """The quotas the user's projects count against, with their usage."""
    from app.backend.api.services import storage_quotas

    return storage_quotas.quotasOf(mapper.db, int(currentUser["id"]))

