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

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


thumbnailUrl: Optional[str] = None
thumbnailRebuildUrl: Optional[str] = None


class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    status: Optional[str] = "active"


class ProjectImportIn(BaseModel):
    projectLocation: str = Field(..., min_length=1)
    projectName: Optional[str] = Field(None)
    copyProject: bool = True


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


class ProjectOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    status: str
    createdAt: datetime
    updatedAt: Optional[datetime]
    protocolsCount: int = 0
    diskUsage: str = f"{0.0} GB"
    isOwner: bool
    isShared: bool
    permission: str
    projectOwnerId: int
    thumbnailItemsUrl: Optional[str] = None
    thumbnailUrl: Optional[str] = None
    thumbnailRebuildUrl: Optional[str] = None
    thumbnailVersion: Optional[str] = None

    class Config:
        orm_mode = True


class ProjectShareCreate(BaseModel):
    userIds = []
    permission: Optional[str] = "full"


class TiltSeriesNewSetRequest(BaseModel):
    """
    Request payload for creating a new SetOfTiltSeries based on exclusions.
    """

    exclusions: Dict[str, Any]
    restack: bool = False


class ShareProjectPayload(BaseModel):
    """
    Request payload for sharing a project with one or more users.
    """

    userIds: List[int]


class ApplyWorkflowToProjectRequest(BaseModel):
    workflowId: str


class ProtocolWizardInputOption(BaseModel):
    value: str
    label: str


class ProtocolWizardInputSchema(BaseModel):
    type: Literal["select"]
    paramName: str
    options: List[ProtocolWizardInputOption] = Field(default_factory=list)


class ProtocolWizardExecuteRequest(BaseModel):
    protocolId: Optional[int] = None
    protocolClassName: str
    paramName: str
    wizardId: str
    formValues: Dict[str, Any] = Field(default_factory=dict)
    wizardInputs: Dict[str, Any] = Field(default_factory=dict)


class WizardInputFieldResponse(BaseModel):
    name: str
    label: str
    kind: str
    value: Optional[Any] = None
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None


class WizardInputSchemaResponse(BaseModel):
    type: str
    paramName: str
    title: Optional[str] = None
    fields: Optional[List[WizardInputFieldResponse]] = None


class WizardPreviewResponse(BaseModel):
    imageUrl: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None


class WizardViewerItemResponse(BaseModel):
    id: str
    label: str
    index: int


class WizardViewerPreviewResponse(BaseModel):
    imageUrl: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    caption: Optional[str] = None


class WizardViewerStateResponse(BaseModel):
    items: List[WizardViewerItemResponse] = Field(default_factory=list)
    selectedIndex: int = 1
    radius: Optional[int] = None
    radiusMin: Optional[int] = None
    radiusStep: Optional[int] = None
    radiusAngstrom: Optional[float] = None
    samplingRate: Optional[float] = None
    preview: Optional[WizardViewerPreviewResponse] = None


class ProtocolWizardExecuteResponse(BaseModel):
    success: bool
    wizardId: str
    kind: str
    paramUpdates: Dict[str, Any] = Field(default_factory=dict)
    message: Optional[str] = None

    availableValues: Optional[List[Union[str, Dict[str, Any]]]] = None

    requiresUserInput: bool = False
    inputSchema: Optional[WizardInputSchemaResponse] = None
    preview: Optional[WizardPreviewResponse] = None
    viewerState: Optional[WizardViewerStateResponse] = None