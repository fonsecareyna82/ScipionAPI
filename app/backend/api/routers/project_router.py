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

from fastapi import APIRouter, HTTPException, Request
from typing import List, Any

from pydantic import BaseModel
from pyworkflow.object import Dict

from app.backend.api.services.project_service import ProjectService
from app.backend.models.project_model import ProjectCreateRequest, ProjectResponse, ProjectUpdateRequest
from app.backend.models.protocol_model import ProtocolRequest

router = APIRouter(prefix="/projects", tags=["Projects"])
service = ProjectService()


@router.post("/launch", response_model=Any)
async def launch_protocol(request: ProtocolRequest):
    """
    Espera un body JSON:
    {
      "protocolId": "abc-123",
      "params": {
        "0_paramA": { ... },
        "0_paramB": { ... },
        // ...
      }
    }
    """
    try:
        protocolId = request.getProtocolId()
        params = request.getParams()
        if not protocolId:
            raise HTTPException(status_code=400, detail="Se requiere protocolId")

        return service.launchProtocol(protocolId, params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
def healthCheck():
    """Simple health check endpoint"""
    return {"status": "ok"}


@router.post("/create", response_model=ProjectResponse)
async def createProject(project: ProjectCreateRequest):
    return service.createProject(project)


@router.get("/", response_model=List[ProjectResponse])
async def listProjects():
    return service.listProjects()


@router.get("/list", response_model=List[ProjectResponse])
async def listProjectsAlias():
    return service.listProjects()


@router.get("/load/{projectId}", response_model=Any)
async def loadProject(projectId: str):
    return service.loadProject(projectId)


@router.delete("/{project_id}")
async def deleteProject(project_id: int):
    try:
        return service.deleteProject(project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: int, updated: ProjectUpdateRequest):
    try:
        return service.updateProject(project_id, updated)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/protocols/{protocolId}", response_model=Any)
async def loadProtocol(protocolId: str):
    return service.getProtocolParams(protocolId)
