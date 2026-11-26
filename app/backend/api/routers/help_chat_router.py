"""The help chat: a question, answered with ScipionWeb's own help (see services/help_chat.py), or by the AI assistant
when an administrator turned it on and the user may use it (see services/assistant_agent.py)."""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.backend.api.audit import recordAudit
from app.backend.api.dependencies import getCurrentUser
from app.backend.api.permissions import hasPermission, requirePermission
from app.backend.api.services import help_index
from app.backend.api.services.assistant_agent import AssistantAgent, AssistantTools, LOG_BYTES, contextLine
from app.backend.api.services.assistant_provider import AssistantProvider, AssistantProviderError
from app.backend.api.services.assistant_settings import (
    PROVIDERS, AssistantSettings, baseUrlOf, decryptKey,
)
from app.backend.api.services.help_chat import MAX_QUESTION, HelpChat
from app.backend.database import getMapperDependency
from app.backend.mapper.assistant_mapper import AssistantPostgresqlMapper
from app.backend.mapper.help_chat_mapper import HelpChatPostgresqlMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/help-chat", tags=["Help chat"])

MAX_PROJECTS = 200
MAX_PARAM_CHARS = 500


class HistoryTurn(BaseModel):
    role: str = Field(..., max_length=16)
    text: str = Field("", max_length=20000)


class HelpQuestion(BaseModel):
    question: str = Field(..., max_length=MAX_QUESTION * 4)
    # Where the user is: the project open and the protocol selected in it (its Scipion id), if any
    projectId: Optional[int] = None
    protocolId: Optional[str] = Field(None, max_length=32)
    # The conversation so far, for the assistant (the rule-based answers do not use it)
    history: Optional[List[HistoryTurn]] = Field(None, max_items=40)


class AssistantSettingsPayload(BaseModel):
    enabled: Optional[bool] = None
    provider: Optional[str] = None
    baseUrl: Optional[str] = Field(None, max_length=500)
    model: Optional[str] = Field(None, max_length=200)
    # None keeps the key there is; "" removes it
    key: Optional[str] = Field(None, max_length=2000)
    mode: Optional[str] = None
    dailyLimit: Optional[int] = None


def _assistantFor(mapper, currentUser) -> Optional[AssistantSettings]:
    settings = AssistantSettings(mapper.db)
    if hasPermission(currentUser, "assistant.use") and settings.ready():
        return settings
    return None


def _providerOf(stored: Dict[str, Any]) -> AssistantProvider:
    return AssistantProvider(baseUrlOf(stored), decryptKey(stored.get("keyEncrypted")), stored.get("model") or "")


@router.get("/status")
def chatStatus(currentUser: dict = Depends(getCurrentUser),
               mapper: PostgresqlFlatMapper = Depends(getMapperDependency)) -> Dict[str, Any]:
    """Whether this user's questions go to the AI assistant, and how many are left today."""
    settings = _assistantFor(mapper, currentUser)
    if settings is None:
        return {"assistant": False}
    limit = int(settings.stored()["dailyLimit"])
    used = AssistantPostgresqlMapper(mapper.db).usageToday(int(currentUser["id"]))["questions"]
    return {"assistant": True, "dailyLimit": limit, "left": max(0, limit - used)}


def _projectTools(mapper, currentUser) -> AssistantTools:
    from app.backend.api.services.project_service import ProjectService
    from app.backend.api.services.protocol_failure import explainProtocolFailure

    service = ProjectService()
    seen: Dict[int, bool] = {}

    def allowed(projectId: int) -> None:
        if projectId not in seen:
            seen[projectId] = bool(service.getProjectDbRow(mapper, projectId, currentUser))
        if not seen[projectId]:
            raise PermissionError(projectId)

    def listProjects():
        return [{"id": row.get("id"), "name": row.get("name")}
                for row in (service.listProjects(mapper, currentUser) or [])[:MAX_PROJECTS]]

    def listProtocols(projectId: int):
        allowed(projectId)
        return HelpChatPostgresqlMapper(mapper.db).projectProtocols(projectId)

    def protocolDetails(projectId: int, protocolId: str):
        allowed(projectId)
        row = AssistantPostgresqlMapper(mapper.db).protocol(projectId, protocolId)
        if not row:
            return None
        params = row.pop("params", None) or {}
        row["params"] = {key: (value if len(str(value)) <= MAX_PARAM_CHARS else str(value)[:MAX_PARAM_CHARS] + "…")
                         for key, value in params.items() if value not in (None, "", [], {})} \
            if isinstance(params, dict) else {}
        row["outputs"] = HelpChatPostgresqlMapper(mapper.db).protocolOutputs(projectId, protocolId)
        return row

    def protocolLog(projectId: int, protocolId: str, channel: str) -> str:
        allowed(projectId)
        window = service.readProtocolLogWindowService(projectId=projectId, protocolId=int(protocolId),
                                                      channel=channel, maxBytes=LOG_BYTES, mapper=mapper,
                                                      currentUser=currentUser, protocolIdIsScipionId=True)
        return (window or {}).get("content") or "(the log is empty)"

    def explainFailure(projectId: int, protocolId: str):
        allowed(projectId)
        return explainProtocolFailure(mapper, service, projectId, int(protocolId))

    def searchHelp(query: str):
        return HelpChat(help_index.protocolsHelp)._search(query, None, False).get("cards") or []

    return AssistantTools(listProjects, listProtocols, protocolDetails, protocolLog, explainFailure, searchHelp)


def _askAssistant(payload: HelpQuestion, settings: AssistantSettings, mapper, currentUser) -> Dict[str, Any]:
    stored = settings.stored()
    usage = AssistantPostgresqlMapper(mapper.db)
    userId = int(currentUser["id"])
    limit = int(stored["dailyLimit"])
    if usage.usageToday(userId)["questions"] >= limit:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="You asked the assistant %d times today, the most allowed. "
                                   "It answers again tomorrow." % limit)
    project = protocol = None
    if payload.projectId is not None:
        from app.backend.api.services.project_service import ProjectService

        project = ProjectService().getProjectDbRow(mapper, payload.projectId, currentUser)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        if payload.protocolId:
            protocol = HelpChatPostgresqlMapper(mapper.db).protocol(int(payload.projectId), payload.protocolId)
    agent = AssistantAgent(_providerOf(stored), _projectTools(mapper, currentUser))
    try:
        answer = agent.answer(payload.question, contextLine(project, protocol),
                              [turn.dict() for turn in payload.history or []])
    except AssistantProviderError as error:
        logger.warning("The assistant could not answer: %s", error)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error))
    tokens = answer.pop("usage")
    usage.addUsage(userId, 1, tokens["inputTokens"], tokens["outputTokens"])
    answer["left"] = max(0, limit - usage.usageToday(userId)["questions"])
    return answer


@router.post("/ask")
def ask(payload: HelpQuestion, currentUser: dict = Depends(getCurrentUser),
        mapper: PostgresqlFlatMapper = Depends(getMapperDependency)) -> Dict[str, Any]:
    """{text, cards}: a short sentence and the pieces of help that answer the question; from the assistant, also
    the steps it took and how many questions are left today."""
    settings = _assistantFor(mapper, currentUser)
    if settings is not None:
        return _askAssistant(payload, settings, mapper, currentUser)

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


# Settings (administrators) ---------------------------------------------------------------------------------------

@router.get("/settings")
def getAssistantSettings(mapper: PostgresqlFlatMapper = Depends(getMapperDependency),
                         currentUser: dict = Depends(requirePermission("settings.manage"))) -> Dict[str, Any]:
    settings = AssistantSettings(mapper.db)
    answer = settings.view()
    answer["usage"] = {"today": AssistantPostgresqlMapper(mapper.db).totals(0),
                       "last30Days": AssistantPostgresqlMapper(mapper.db).totals(29)}
    return answer


@router.put("/settings")
def saveAssistantSettings(payload: AssistantSettingsPayload, mapper: PostgresqlFlatMapper = Depends(getMapperDependency),
                          currentUser: dict = Depends(requirePermission("settings.manage"))) -> Dict[str, Any]:
    settings = AssistantSettings(mapper.db).save(payload.dict(), userId=currentUser.get("id"))
    recordAudit(mapper, currentUser, "settings.assistantUpdated", "settings", None, "assistant",
                {"enabled": settings["enabled"], "provider": settings["provider"], "model": settings["model"],
                 "dailyLimit": settings["dailyLimit"], "key": "changed" if payload.key is not None else "kept"})
    return settings


def _providerForPayload(payload: AssistantSettingsPayload, mapper) -> AssistantProvider:
    """The provider as the form shows it now, before it is saved: the key typed, or the one kept."""
    stored = AssistantSettings(mapper.db).merged(payload.dict())
    if not baseUrlOf(stored):
        raise HTTPException(status_code=400, detail="A local model needs its address")
    if PROVIDERS[stored["provider"]]["needsKey"] and not stored.get("keyEncrypted"):
        raise HTTPException(status_code=400, detail="Write the provider's key first")
    return _providerOf(stored)


@router.post("/settings/models")
def listAssistantModels(payload: AssistantSettingsPayload, mapper: PostgresqlFlatMapper = Depends(getMapperDependency),
                        currentUser: dict = Depends(requirePermission("settings.manage"))) -> Dict[str, Any]:
    """The models the provider offers with that key."""
    try:
        return {"models": _providerForPayload(payload, mapper).models()}
    except AssistantProviderError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error))


@router.post("/settings/test")
def testAssistant(payload: AssistantSettingsPayload, mapper: PostgresqlFlatMapper = Depends(getMapperDependency),
                  currentUser: dict = Depends(requirePermission("settings.manage"))) -> Dict[str, Any]:
    """Ask the model one tiny question, to see that the provider, the key and the model work together."""
    provider = _providerForPayload(payload, mapper)
    if not provider.model:
        raise HTTPException(status_code=400, detail="Choose a model first")
    try:
        reply = provider.chat([{"role": "user", "content": "Answer only with the word: ready"}])
    except AssistantProviderError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error))
    return {"ok": True, "reply": str(reply["message"].get("content") or "")[:200]}
