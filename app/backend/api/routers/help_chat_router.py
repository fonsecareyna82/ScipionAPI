"""The help chat: a question, answered with ScipionWeb's own help (see services/help_chat.py)."""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.backend.api.dependencies import getCurrentUser
from app.backend.api.services import help_index
from app.backend.api.services.help_chat import MAX_QUESTION, HelpChat
from app.backend.database import getMapperDependency
from app.backend.mapper.help_chat_mapper import HelpChatPostgresqlMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/help-chat", tags=["Help chat"])


class HelpQuestion(BaseModel):
    question: str = Field(..., max_length=MAX_QUESTION * 4)
    # Where the user is: the project open and the protocol selected in it (its Scipion id), if any
    projectId: Optional[int] = None
    protocolId: Optional[str] = Field(None, max_length=32)


@router.post("/ask")
def ask(payload: HelpQuestion, currentUser: dict = Depends(getCurrentUser),
        mapper: PostgresqlFlatMapper = Depends(getMapperDependency)) -> Dict[str, Any]:
    """{text, cards}: a short sentence and the pieces of help that answer the question."""
    projectProtocols = explainFailure = protocolOutputs = None
    if payload.projectId is not None:
        from app.backend.api.services.project_service import ProjectService
        from app.backend.api.services.protocol_failure import explainProtocolFailure

        service = ProjectService()
        if not service.getProjectDbRow(mapper, payload.projectId, currentUser):
            raise HTTPException(status_code=404, detail="Project not found")
        projectId = int(payload.projectId)

        def projectProtocols():
            return HelpChatPostgresqlMapper(mapper.db).projectProtocols(projectId)

        def protocolOutputs(protocolId: str) -> List[Dict[str, Any]]:
            return HelpChatPostgresqlMapper(mapper.db).protocolOutputs(projectId, protocolId)

        def explainFailure(protocolId: str) -> Dict[str, Any]:
            try:
                return explainProtocolFailure(mapper, service, projectId, int(protocolId))
            except Exception:
                logger.warning("Could not explain the failure of protocol %s", protocolId, exc_info=True)
                return {}

    chat = HelpChat(help_index.protocolsHelp, projectProtocols, explainFailure, protocolOutputs=protocolOutputs)
    return chat.answer(payload.question, payload.protocolId)
