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

# settingsModels
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


class UserSettings(BaseModel):
    # userSettings
    theme: Literal["system", "light", "dark"] = "system"
    uiDensity: Literal["comfortable", "compact"] = "comfortable"
    fontScale: float = Field(default=1.0, ge=0.85, le=1.25)

    language: Literal["en", "es"] = "en"
    timeZone: str = "Europe/Madrid"

    graphMiniMapEnabled: bool = True
    graphFocusModeEnabled: bool = False
    protocolOutputThumbnailsEnabled: bool = False
    workflowsAutoRefreshSec: int = Field(default=5, ge=0, le=300)


class UserSettingsPatch(BaseModel):
    # userSettingsPatch
    theme: Optional[Literal["system", "light", "dark"]] = None
    uiDensity: Optional[Literal["comfortable", "compact"]] = None
    fontScale: Optional[float] = Field(default=None, ge=0.85, le=1.25)

    language: Optional[Literal["en", "es"]] = None
    timeZone: Optional[str] = None

    graphMiniMapEnabled: Optional[bool] = None
    graphFocusModeEnabled: Optional[bool] = None
    protocolOutputThumbnailsEnabled: Optional[bool] = None
    workflowsAutoRefreshSec: Optional[int] = Field(default=None, ge=0, le=300)


class InstanceSettings(BaseModel):
    # instanceSettings
    defaultQueueName: str = "default"

    maxConcurrentRunsPerUser: int = Field(default=2, ge=1, le=64)

    requireConfirmBeforeExecute: bool = True
    requireConfirmBeforeDelete: bool = True


class InstanceSettingsPatch(BaseModel):
    # instanceSettingsPatch
    defaultQueueName: Optional[str] = None

    maxConcurrentRunsPerUser: Optional[int] = Field(default=None, ge=1, le=64)

    requireConfirmBeforeExecute: Optional[bool] = None
    requireConfirmBeforeDelete: Optional[bool] = None
