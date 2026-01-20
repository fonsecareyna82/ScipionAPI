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
