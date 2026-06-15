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
# schemas/protocol.py
from typing import Optional, Any, Dict, List, Union
from pydantic import BaseModel, Field, validator
from datetime import datetime


class ProtocolCreate(BaseModel):
    projectId: int
    protocolId: str = Field(..., min_length=1)
    protocolClassName: str = Field(..., min_length=1)
    params: Dict[str, Any] = {}

    @validator("protocolId")
    @classmethod
    def validateProtocolId(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError("protocolId must be a valid identifier")
        return value

    @validator("protocolClassName")
    @classmethod
    def validateProtocolClassName(cls, value: str) -> str:
        if not value.isidentifier():
            raise ValueError("protocolClassName must be a valid identifier")
        return value


class ProtocolUpdate(BaseModel):
    params: Optional[Dict[str, Any]] = None


class ProtocolOut(BaseModel):
    id: int
    projectId: int
    protocolId: str
    protocolClassName: str
    params: Dict[str, Any]
    createdAt: datetime
    updatedAt: Optional[datetime] = None

    class Config:
        orm_mode = True  # Compatibility with SQLAlchemy models


class ProtocolRequestOut(BaseModel):
    protocolId: str
    protocolClassName: str
    params: Any

    class Config:
        arbitrary_types_allowed = True


class ExportProtocolsRequest(BaseModel):
    protocolIds: List[Union[int, str]] = Field(default_factory=list)
    directoryPath: str = Field(..., min_length=1)
    filename: str = Field(..., min_length=1)


class RemoteFileWriteRequest(BaseModel):
    path: str = Field(..., min_length=1)
    content: str = ""
    mimeType: Optional[str] = "application/json"


class WorkflowExportRequest(BaseModel):
    protocolIds: List[Union[int, str]] = Field(default_factory=list)
    includeUpstream: bool = False


class WorkflowImportRequest(BaseModel):
    workflow: Any
    mode: str = "append"
    sourceProjectId: Optional[Union[int, str]] = None
    sourceProjectName: Optional[str] = None

