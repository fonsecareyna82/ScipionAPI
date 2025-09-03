from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    status: Optional[str] = "active"


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
    protocolsCount = 0,
    diskUsage = f"{0.0} GB"

    class Config:
        orm_mode = True
