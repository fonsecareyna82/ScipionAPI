# schemas/project.py

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ProjectCreate(BaseModel):
    # Schema for creating a new project
    name: str
    description: Optional[str] = None
    status: Optional[str] = "active"


class ProjectOut(BaseModel):
    # Schema for returning project data
    id: int
    name: str
    description: Optional[str]
    status: str
    createdAt: datetime
    updatedAt: Optional[datetime]

    class Config:
        orm_mode = True  # Enables compatibility with SQLAlchemy models
