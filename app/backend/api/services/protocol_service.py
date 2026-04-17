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
# app/backend/api/services/protocol_service.py
from typing import Dict, Any, Optional
from app.backend.api.services.project_service import ProjectService
from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.models.protocol_model import ProtocolRequest


class ProtocolService:
    """Service layer for handling Protocol-related actions, using ProjectService."""

    def __init__(self):
        self.projectService = ProjectService()

    # -----------------------------
    # Protocol Retrieval
    # -----------------------------
    def getProtocols(
        self,
        mapper: PostgresqlFlatMapper,
        projectId: int,
        currentUser: Dict[str, Any]
    ):
        """Return all protocols for a given project."""
        return self.projectService.getProtocols(mapper, projectId, currentUser)

    def getProtocolParams(
        self,
        mapper: PostgresqlFlatMapper,
        projectId: int,
        protocolId: int,
        currentUser: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Return parameters of an existing protocol."""
        project = self.projectService.getProjectById(mapper, projectId, currentUser)
        if not project:
            return None
        return self.projectService.getProtocolParams(projectId, protocolId)

    def getNewProtocolParams(
        self,
        mapper: PostgresqlFlatMapper,
        projectId: int,
        protClassName: str,
        currentUser: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Return parameters for a new protocol instance."""
        project = self.projectService.getProjectById(mapper, projectId, currentUser)
        if not project:
            return None
        return self.projectService.getNewProtocolParams(projectId, protClassName)
