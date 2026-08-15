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
from typing import List, Optional

from pydantic import BaseModel, Field


class JobWorkerOut(BaseModel):
    name: str
    queues: List[str] = Field(default_factory=list)
    online: bool = True
    concurrency: int = 0
    active: int = 0
    reserved: int = 0


class ActiveProtocolJobOut(BaseModel):
    taskId: str
    projectId: int
    projectName: Optional[str] = None
    protocolId: str
    protocolClassName: Optional[str] = None
    runMode: str
    celeryState: str
    step: Optional[str] = None
    protocolStatus: str
    worker: str
    queue: Optional[str] = None
    workerPid: Optional[int] = None
    protocolPid: Optional[int] = None
    jobIds: List[str] = Field(default_factory=list)
    startedAt: Optional[datetime] = None
    elapsedSeconds: Optional[float] = None


class RecentProtocolJobOut(BaseModel):
    projectId: int
    projectName: str
    protocolId: str
    protocolClassName: str
    status: str
    runtimePid: Optional[int] = None
    jobIds: List[str] = Field(default_factory=list)
    elapsedTimeSeconds: Optional[float] = None
    createdAt: datetime
    updatedAt: Optional[datetime] = None


class JobMonitoringOverviewOut(BaseModel):
    celeryAvailable: bool
    celeryError: Optional[str] = None
    workers: List[JobWorkerOut] = Field(default_factory=list)
    activeJobs: List[ActiveProtocolJobOut] = Field(default_factory=list)
    recentJobs: List[RecentProtocolJobOut] = Field(default_factory=list)
    refreshedAt: datetime