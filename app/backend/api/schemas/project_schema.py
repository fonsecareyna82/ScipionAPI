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
    copyProject: Literal[True] = True


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


class ProjectImportOut(ProjectOut):
    importReport: Dict[str, Any]


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


class ProtocolWizardRunRequest(BaseModel):
    """Run a form wizard: the answers to its dialogs so far, or a preview to compute."""
    protocolId: Optional[int] = None
    protocolClassName: str
    paramName: str
    wizardId: str
    formValues: Dict[str, Any] = Field(default_factory=dict)
    answers: List[Dict[str, Any]] = Field(default_factory=list)
    preview: Optional[Dict[str, Any]] = None


class ProtocolRelationCandidatesRequest(BaseModel):
    protocolClassName: str
    paramName: str
    formValues: Dict[str, Any] = Field(
        default_factory=dict
    )


class ProtocolRelationCandidatesResponse(BaseModel):
    paramName: str
    relationName: str
    values: List[str] = Field(
        default_factory=list
    )
