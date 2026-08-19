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

# settingsSchema
from __future__ import annotations

from typing import Optional, Literal, List
from pydantic import BaseModel, Field


class UserSettingsOut(BaseModel):
    # userSettingsOut
    theme: Literal["system", "light", "dark"] = "system"
    uiDensity: Literal["comfortable", "compact"] = "comfortable"
    fontScale: float = Field(default=1.0, ge=0.85, le=1.25)
    workflowViewMode: Optional[Literal["treeTb", "treeLr", "grid", "table"]] = "treeTb"

    language: Literal["en", "es"] = "en"
    timeZone: str = "Europe/Madrid"

    graphMiniMapEnabled: bool = True
    graphFocusModeEnabled: bool = False
    protocolOutputThumbnailsEnabled: bool = False
    workflowsAutoRefreshSec: int = Field(default=5, ge=0, le=300)


class UserSettingsIn(UserSettingsOut):
    # userSettingsIn
    pass


class UserSettingsPatch(BaseModel):
    # userSettingsPatch
    theme: Optional[Literal["system", "light", "dark"]] = None
    uiDensity: Optional[Literal["comfortable", "compact"]] = None
    fontScale: Optional[float] = Field(default=None, ge=0.85, le=1.25)
    workflowViewMode: Optional[Literal["treeTb", "treeLr", "grid", "table"]] = None

    language: Optional[Literal["en", "es"]] = None
    timeZone: Optional[str] = None

    graphMiniMapEnabled: Optional[bool] = None
    graphFocusModeEnabled: Optional[bool] = None
    protocolOutputThumbnailsEnabled: Optional[bool] = None
    workflowsAutoRefreshSec: Optional[int] = Field(default=None, ge=0, le=300)


class InstanceSettingsOut(BaseModel):
    # instanceSettingsOut
    defaultQueueName: str = "default"
    maxConcurrentRunsPerUser: int = Field(
        default=4,
        ge=1,
        le=64,
    )


class InstanceSettingsIn(
        InstanceSettingsOut,
):
    # instanceSettingsIn
    pass


class InstanceSettingsPatch(BaseModel):
    # instanceSettingsPatch
    defaultQueueName: Optional[str] = None
    maxConcurrentRunsPerUser: Optional[int] = Field(
        default=None,
        ge=1,
        le=64,
    )


class InstanceGpuResourceOut(BaseModel):
    index: int
    name: str
    memoryTotalBytes: Optional[int] = None


class InstanceResourcesOut(BaseModel):
    hostAlias: str = ""
    hostname: str
    fqdn: str
    schedulerName: str = ""

    operatingSystem: str
    architecture: str
    cpuModel: str

    physicalCores: int
    logicalCores: int
    ramTotalBytes: int

    gpuCount: int
    gpus: List[
        InstanceGpuResourceOut
    ] = Field(
        default_factory=list
    )


class EnvironmentVariableOut(BaseModel):
    name: str
    value: str
    default: str
    description: str
    source: str
    isDefault: bool
    type: str


class HostQueueParam(BaseModel):
    variableName: str = Field(..., min_length=1, description="Queue variable name")
    value: str = Field("", description="Default value")
    label: str = Field("", description="Human-readable label")
    help: str = Field("", description="Help text shown in the UI")


class HostQueue(BaseModel):
    name: str = Field(..., min_length=1, description="Queue name")
    params: List[HostQueueParam] = Field(default_factory=list, description="Queue parameter definitions")


class HostSettingsIn(BaseModel):
    hostAlias: str = Field(..., min_length=1, description="Host alias or section name")
    schedulerName: str = Field(..., min_length=1, description="Scheduler display name")
    mandatory: bool = Field(False, description="Whether queue usage is mandatory")

    parallelCommand: str = Field(..., min_length=1, description="Parallel execution command")
    submitCommand: str = Field(..., min_length=1, description="Queue submit command")
    cancelCommand: str = Field(..., min_length=1, description="Queue cancel command")
    checkCommand: str = Field(..., min_length=1, description="Queue status command")

    jobDoneRegex: str = Field("", description="Optional regex used to detect finished jobs")
    submitTemplate: str = Field(..., min_length=1, description="Submit script template")

    queues: List[HostQueue] = Field(default_factory=list, description="Configured queues")


class HostSettingsOut(BaseModel):
    hostAlias: str = Field(
        ...,
        min_length=1,
        description="Host alias or section name",
    )
    schedulerName: str = Field(
        "",
        description="Scheduler display name",
    )
    mandatory: bool = Field(
        False,
        description="Whether queue usage is mandatory",
    )

    parallelCommand: str = Field(
        "",
        description="Parallel execution command",
    )
    submitCommand: str = Field(
        "",
        description="Queue submit command",
    )
    cancelCommand: str = Field(
        "",
        description="Queue cancel command",
    )
    checkCommand: str = Field(
        "",
        description="Queue status command",
    )

    jobDoneRegex: str = Field(
        "",
        description="Optional regex used to detect finished jobs",
    )
    submitTemplate: str = Field(
        "",
        description="Submit script template",
    )

    queues: List[HostQueue] = Field(
        default_factory=list,
        description="Configured queues",
    )


class HostSettingsPatch(BaseModel):
    hostAlias: Optional[str] = Field(None, min_length=1, description="Host alias or section name")
    schedulerName: Optional[str] = Field(None, min_length=1, description="Scheduler display name")
    mandatory: Optional[bool] = Field(None, description="Whether queue usage is mandatory")

    parallelCommand: Optional[str] = Field(None, min_length=1, description="Parallel execution command")
    submitCommand: Optional[str] = Field(None, min_length=1, description="Queue submit command")
    cancelCommand: Optional[str] = Field(None, min_length=1, description="Queue cancel command")
    checkCommand: Optional[str] = Field(None, min_length=1, description="Queue status command")

    jobDoneRegex: Optional[str] = Field(None, description="Optional regex used to detect finished jobs")
    submitTemplate: Optional[str] = Field(None, min_length=1, description="Submit script template")

    queues: Optional[List[HostQueue]] = Field(None, description="Configured queues")