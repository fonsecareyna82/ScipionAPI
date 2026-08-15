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

# settingsRouter
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Dict, List
from app.backend.api.dependencies import getCurrentUser, requireAdmin
from app.backend.database import getMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper

from app.backend.api.schemas.settings_schema import (
    UserSettingsOut,
    UserSettingsIn,
    UserSettingsPatch,
    InstanceSettingsOut,
    InstanceSettingsIn,
    InstanceSettingsPatch,
    EnvironmentVariableOut,
    HostSettingsOut,
    HostSettingsIn,
    HostSettingsPatch,
    InstanceResourcesOut
)
from app.backend.api.schemas.job_monitoring_schema import (
    JobMonitoringOverviewOut,
)
from app.backend.api.services.settings_service import SettingsService
from app.backend.api.services.job_monitoring_service import (
    JobMonitoringService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


def getSettingsService() -> SettingsService:
    """Return a fresh SettingsService per request to avoid shared state."""
    return SettingsService()


def getJobMonitoringService() -> JobMonitoringService:
    return JobMonitoringService()


@router.get(
    "/user",
    response_model=UserSettingsOut,
    status_code=status.HTTP_200_OK,
)
def getUserSettings(
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: SettingsService = Depends(getSettingsService),
):
    """
    Return user-scoped settings for the authenticated user.
    """
    try:
        return service.getUserSettings(mapper, currentUser)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in getUserSettings: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load user settings: {e}",
        )


@router.put(
    "/user",
    response_model=UserSettingsOut,
    status_code=status.HTTP_200_OK,
)
def putUserSettings(
    payload: UserSettingsIn,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: SettingsService = Depends(getSettingsService),
):
    """
    Replace user-scoped settings for the authenticated user.
    """
    try:
        return service.putUserSettings(mapper, currentUser, payload)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in putUserSettings: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update user settings: {e}",
        )


@router.patch(
    "/user",
    response_model=UserSettingsOut,
    status_code=status.HTTP_200_OK,
)
def patchUserSettings(
    patch: UserSettingsPatch,
    currentUser=Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: SettingsService = Depends(getSettingsService),
):
    """
    Partially update user-scoped settings for the authenticated user.
    """
    try:
        return service.patchUserSettings(mapper, currentUser, patch)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in patchUserSettings: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to patch user settings: {e}",
        )


@router.get(
    "/instance",
    response_model=InstanceSettingsOut,
    status_code=status.HTTP_200_OK,
)
def getInstanceSettings(
    currentUser=Depends(requireAdmin),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: SettingsService = Depends(getSettingsService),
):
    """
    Return instance-wide settings (admin-only).
    """
    try:
        return service.getInstanceSettings(mapper, currentUser)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in getInstanceSettings: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load instance settings: {e}",
        )


@router.get(
    "/instance/resources",
    response_model=InstanceResourcesOut,
    status_code=status.HTTP_200_OK,
)
def getInstanceResources(
    currentUser=Depends(
        requireAdmin
    ),
    service: SettingsService = Depends(
        getSettingsService
    ),
):
    try:
        return (
            service
            .getInstanceResources(
                currentUser
            )
        )

    except HTTPException:
        raise

    except Exception as error:
        logger.exception(
            "Error in "
            "getInstanceResources: %s",
            error,
        )

        raise HTTPException(
            status_code=(
                status
                .HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=(
                "Failed to load instance "
                f"resources: {error}"
            ),
        )


@router.get(
    "/jobs",
    response_model=JobMonitoringOverviewOut,
    status_code=status.HTTP_200_OK,
)
def getJobsOverview(
    recentLimit: int = Query(
        25,
        ge=1,
        le=100,
    ),
    currentUser=Depends(requireAdmin),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: JobMonitoringService = Depends(getJobMonitoringService),
):
    try:
        return service.getOverview(
            mapper=mapper,
            recentLimit=recentLimit,
        )

    except HTTPException:
        raise

    except Exception as error:
        logger.exception(
            "Error in getJobsOverview: %s",
            error,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Failed to load job monitoring data: %s"
                % error
            ),
        )


@router.put(
    "/instance",
    response_model=InstanceSettingsOut,
    status_code=status.HTTP_200_OK,
)
def putInstanceSettings(
    payload: InstanceSettingsIn,
    currentUser=Depends(requireAdmin),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: SettingsService = Depends(getSettingsService),
):
    """
    Replace instance-wide settings (admin-only).
    """
    try:
        return service.putInstanceSettings(mapper, currentUser, payload)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in putInstanceSettings: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update instance settings: {e}",
        )


@router.patch(
    "/instance",
    response_model=InstanceSettingsOut,
    status_code=status.HTTP_200_OK,
)
def patchInstanceSettings(
    patch: InstanceSettingsPatch,
    currentUser=Depends(requireAdmin),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    service: SettingsService = Depends(getSettingsService),
):
    """
    Partially update instance-wide settings (admin-only).
    """
    try:
        return service.patchInstanceSettings(mapper, currentUser, patch)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in patchInstanceSettings: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to patch instance settings: {e}",
        )


@router.get(
    "/environment",
    response_model=List[EnvironmentVariableOut],
    status_code=status.HTTP_200_OK,
)
def getEnvironmentVariables(
    currentUser=Depends(requireAdmin),
    service: SettingsService = Depends(getSettingsService),
):
    try:
        return service.getEnvironmentVariables(currentUser)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in getEnvironmentVariables: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load environment variables: {e}",
        )


@router.patch(
    "/environment",
    response_model=List[EnvironmentVariableOut],
    status_code=status.HTTP_200_OK,
)
def patchEnvironmentVariables(
    patch: Dict[str, str],
    currentUser=Depends(requireAdmin),
    service: SettingsService = Depends(getSettingsService),
):
    try:
        return service.patchEnvironmentVariables(currentUser, patch)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in patchEnvironmentVariables: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to patch environment variables: {e}",
        )


@router.get(
    "/host",
    response_model=HostSettingsOut,
    status_code=status.HTTP_200_OK,
)
def getHostSettings(
        currentUser=Depends(requireAdmin),
        mapper: PostgresqlFlatMapper = Depends(getMapper),
        service: SettingsService = Depends(getSettingsService),
):
    """
    Return host execution settings (admin-only).
    """
    try:
        return service.getHostSettings(mapper, currentUser)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in getHostSettings: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load host settings: {e}",
        )


@router.put(
    "/host",
    response_model=HostSettingsOut,
    status_code=status.HTTP_200_OK,
)
def putHostSettings(
        payload: HostSettingsIn,
        currentUser=Depends(requireAdmin),
        mapper: PostgresqlFlatMapper = Depends(getMapper),
        service: SettingsService = Depends(getSettingsService),
):
    """
    Replace host execution settings (admin-only).
    """
    try:
        return service.putHostSettings(mapper, currentUser, payload)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in putHostSettings: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update host settings: {e}",
        )


@router.patch(
    "/host",
    response_model=HostSettingsOut,
    status_code=status.HTTP_200_OK,
)
def patchHostSettings(
        patch: HostSettingsPatch,
        currentUser=Depends(requireAdmin),
        mapper: PostgresqlFlatMapper = Depends(getMapper),
        service: SettingsService = Depends(getSettingsService),
):
    """
    Partially update host execution settings (admin-only).
    """
    try:
        return service.patchHostSettings(mapper, currentUser, patch)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in patchHostSettings: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to patch host settings: {e}",
        )