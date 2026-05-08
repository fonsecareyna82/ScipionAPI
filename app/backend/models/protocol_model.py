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
# models/protocol_model.py
from datetime import datetime
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, JSON, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.backend.database import Base
from pydantic import BaseModel, ConfigDict
from typing import Any, Optional, List, Dict
from app.backend.models.project_model import Project

# ------------------------ SQLAlchemy model ------------------------


class Protocol(Base):
    __tablename__ = "protocols"

    id = Column(Integer, primary_key=True, index=True)
    protocolId = Column(String, nullable=False, unique=True)
    projectId = Column(Integer, ForeignKey("projects.id"))
    protocolClassName = Column(String, nullable=False)
    params = Column(JSON, nullable=True)
    status = Column(String, default="pending")
    parentIds = Column(ARRAY(Integer), default=[])
    childIds = Column(ARRAY(Integer), default=[])
    createdAt = Column(DateTime(timezone=True), server_default=func.now())
    updatedAt = Column(DateTime(timezone=True), onupdate=func.now())

    project = relationship("Project", back_populates="protocols")

# ------------------------ Pydantic models ------------------------


class ProtocolRequest(BaseModel):
    protocolId: str
    protocolClassName: str
    params: Any
    mode: str = None
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def getProtocolId(self):
        return self.protocolId

    def getParams(self):
        return self.params

    def getProtocolClassName(self):
        return self.protocolClassName

    def getMode(self):
        return self.mode


class ProtocolCreateRequest(BaseModel):
    protocolId: str
    projectId: int
    protocolClassName: str
    params: Any
    status: str = "pending"


class ProtocolResponse(BaseModel):
    id: int
    protocolId: str
    projectId: int
    protocolClassName: str
    params: Any
    status: str
    createdAt: datetime
    updatedAt: datetime

    class Config:
        orm_mode = True


class ProtocolUpdateRequest(BaseModel):
    params: Any
    status: str


class ProtocolRenameIn(BaseModel):
    runName: str
    comment: Optional[str] = ""


class ProtocolDuplicateIn(BaseModel):
    name: Optional[str] = None


class DuplicateItem(BaseModel):
    id: str
    name: Optional[str] = None


class DuplicatePayload(BaseModel):
    items: List[DuplicateItem]


class DeletePayload(BaseModel):
    protocolIds: List[str]
