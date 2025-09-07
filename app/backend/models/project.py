# models/project.py
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.backend.database import Base

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.backend.database import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    status = Column(String, default="active")
    ownerId = Column(Integer, ForeignKey("users.id"))
    createdAt = Column(DateTime(timezone=True), server_default=func.now())
    updatedAt = Column(DateTime(timezone=True), onupdate=func.now())

    owner = relationship("User", back_populates="projects")


class ProjectCreateRequest(BaseModel):
    name: str
    description: str
    created_at: datetime = datetime.now()
    status: str = 'PENDING'
    protocolsCount: str = '0'
    diskUsage: str = '1.4 GB'


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str
    created_at: datetime
    status: str
    protocolsCount: str = '0'
    diskUsage: str


class ProjectUpdateRequest(BaseModel):
    name: str
    description: str
