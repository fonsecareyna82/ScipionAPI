"""The help chat: a question, answered with ScipionWeb's own help (see services/help_chat.py), or by the AI assistant
when an administrator turned it on and the user may use it (see services/assistant_agent.py)."""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.backend.api.audit import recordAudit
from app.backend.api.dependencies import getCurrentUser
from app.backend.api.permissions import checkProjectAccess, hasPermission, requirePermission
from app.backend.api.services import help_index
from app.backend.api.services import assistant_actions, search_projects
from app.backend.api.services.assistant_actions import ProposalError
from app.backend.api.services.assistant_agent import AssistantAgent, AssistantTools, LOG_BYTES, contextLine
from app.backend.api.services.assistant_browse import WebReader
from app.backend.api.services.assistant_chains import TemplateChains
from app.backend.api.services.assistant_provider import AssistantProvider, AssistantProviderError
from app.backend.api.services.assistant_settings import (
    PROVIDERS, AssistantSettings, baseUrlOf, decryptKey, providerFor,
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


class ActionPayload(BaseModel):
    action: str = Field(..., max_length=16)
    projectId: int
    # The protocol the action is about ("" for a whole template)
    protocolId: str = Field("", max_length=32)
    mode: Optional[str] = Field(None, max_length=16)
    # single: only this protocol (the ones depending on it are reset); all: its whole workflow
    scope: Optional[str] = Field(None, max_length=16)
    changes: Optional[Dict[str, Any]] = None
    # A delete is confirmed by writing the protocol's number
    confirm: Optional[str] = Field(None, max_length=32)
    # A template: which, from which output of protocolId (cut) or whole with its fields, its links to the project
    # (template ref -> project ref) and the template ids it stops after
    templateId: Optional[str] = Field(None, max_length=300)
    fromOutput: Optional[str] = Field(None, max_length=200)
    anchor: Optional[str] = Field(None, max_length=200)
    links: Optional[Dict[str, str]] = None
    stops: Optional[List[str]] = Field(None, max_items=200)
    fields: Optional[Dict[str, Any]] = None
    # A template only added (False), to start later
    launch: Optional[bool] = None
    # Going on with a chain after its stop protocolId ("" starts one that was only added)
    chainId: Optional[int] = None
    # A subset of protocolId's output kept by its values
    outputName: Optional[str] = Field(None, max_length=200)
    table: Optional[str] = Field(None, max_length=200)
    conditions: Optional[List[Dict[str, Any]]] = Field(None, max_items=6)
    makes: Optional[str] = Field(None, max_length=100)
    name: Optional[str] = Field(None, max_length=200)


class ReportPayload(BaseModel):
    projectId: int
    # Only what led to this protocol; all the project's protocols when left out
    protocolId: Optional[str] = Field(None, max_length=32)
    # pdf: the report; workflow: the workflow file to import and run again
    format: str = Field("pdf", max_length=16)
    # A methods text written by the assistant (when the user may use it)
    methods: bool = True


class AssistantSettingsPayload(BaseModel):
    enabled: Optional[bool] = None
    provider: Optional[str] = None
    baseUrl: Optional[str] = Field(None, max_length=500)
    model: Optional[str] = Field(None, max_length=200)
    # None keeps the key there is; "" removes it
    key: Optional[str] = Field(None, max_length=2000)
    mode: Optional[str] = None
    allowDelete: Optional[bool] = None
    explainFailures: Optional[bool] = None
    summarizeSessions: Optional[bool] = None
    # 0: no limit
    dailyLimit: Optional[int] = None


def _assistantFor(mapper, currentUser) -> Optional[AssistantSettings]:
    settings = AssistantSettings(mapper.db)
    if hasPermission(currentUser, "assistant.use") and settings.ready():
        return settings
    return None


def _providerOf(stored: Dict[str, Any]):
    if stored.get("provider") == "anthropic":
        return providerFor(stored)
    return AssistantProvider(baseUrlOf(stored), decryptKey(stored.get("keyEncrypted")), stored.get("model") or "")


@router.get("/status")
def chatStatus(currentUser: dict = Depends(getCurrentUser),
               mapper: PostgresqlFlatMapper = Depends(getMapperDependency)) -> Dict[str, Any]:
    """Whether this user's questions go to the AI assistant, and how many are left today."""
    settings = _assistantFor(mapper, currentUser)
    if settings is None:
        return {"assistant": False}
    limit = int(settings.stored()["dailyLimit"] or 0)
    if limit <= 0:
        return {"assistant": True, "dailyLimit": 0}
    used = AssistantPostgresqlMapper(mapper.db).usageToday(int(currentUser["id"]))["questions"]
    return {"assistant": True, "dailyLimit": limit, "left": max(0, limit - used)}


def _canWork(project: Dict[str, Any]) -> bool:
    try:
        checkProjectAccess(project, "work")
        return True
    except HTTPException:
        return False


def _preflight(service, mapper, currentUser, projectId: int, protocolId: str, mode: str) -> Dict[str, Any]:
    """The protocols a relaunch would touch, as the protocol form asks before one."""
    if not service.loadPostgresqlRuntimeProjectForMutation(mapper=mapper, projectId=projectId,
                                                           currentUser=currentUser):
        raise PermissionError("The user cannot see that project")
    return service.getProtocolWorkflowExecutionPreflight(mapper=mapper, projectId=projectId,
                                                         protocolId=int(protocolId), mode=mode) or {}


def _children(service, mapper, currentUser, projectId: int, protocol: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The protocols depending on one, each with whether it runs or has results (what blocks a delete)."""
    preflight = _preflight(service, mapper, currentUser, projectId, str(protocol["protocolId"]), "restart")
    children = []
    for item in preflight.get("affectedProtocols") or []:
        childId = str(item.get("protocolId"))
        if childId == str(protocol["protocolId"]):
            continue
        outputs = HelpChatPostgresqlMapper(mapper.db).protocolOutputs(projectId, childId)
        children.append({"protocolId": childId, "label": item.get("runName") or "", "status": item.get("status") or "",
                         "active": bool(item.get("active")), "hasOutputs": bool(outputs)})
    return children


def _projectTools(mapper, currentUser, canPropose: bool = False, canDelete: bool = False,
                  authorization: str = "") -> AssistantTools:
    from app.backend.api.services.project_service import ProjectService
    from app.backend.api.services.protocol_failure import explainProtocolFailure

    service = ProjectService()
    seen: Dict[int, Optional[Dict[str, Any]]] = {}

    def allowed(projectId: int) -> Dict[str, Any]:
        if projectId not in seen:
            seen[projectId] = service.getProjectDbRow(mapper, projectId, currentUser)
        if not seen[projectId]:
            raise PermissionError(projectId)
        return seen[projectId]

    def workable(projectId: int, protocolId: str) -> Dict[str, Any]:
        if not _canWork(allowed(projectId)):
            raise PermissionError("The user can only look at that project, not run things in it")
        protocol = AssistantPostgresqlMapper(mapper.db).protocol(projectId, protocolId)
        if not protocol:
            raise ProposalError("There is no protocol %s in that project" % protocolId)
        return protocol

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

    def proposeRelaunch(projectId: int, protocolId: str, changes: Dict[str, Any], reason: str):
        protocol = workable(projectId, protocolId)
        help_ = help_index.protocolHelp(protocol.get("className"))
        checked = assistant_actions.parameterChanges(protocol.get("params") or {}, help_, changes or {})
        mode, _ = assistant_actions.relaunchModes(protocol.get("status"), bool(checked))
        preflight = _preflight(service, mapper, currentUser, projectId, protocolId, mode)
        return assistant_actions.relaunchCard(projectId, protocol, help_, changes, preflight, reason)

    def proposeStop(projectId: int, protocolId: str, reason: str):
        return assistant_actions.stopCard(projectId, workable(projectId, protocolId), reason)

    def proposeNextStep(projectId: int, protocolId: str, className: str, reason: str):
        source = workable(projectId, protocolId)
        return assistant_actions.nextStepCard(projectId, source, help_index.protocolHelp(className), reason)

    def proposeDuplicate(projectId: int, protocolId: str, changes: Dict[str, Any], reason: str):
        protocol = workable(projectId, protocolId)
        return assistant_actions.duplicateCard(projectId, protocol, help_index.protocolHelp(protocol.get("className")),
                                               changes, reason)

    def proposeDelete(projectId: int, protocolId: str, reason: str):
        protocol = workable(projectId, protocolId)
        outputs = HelpChatPostgresqlMapper(mapper.db).protocolOutputs(projectId, protocolId)
        return assistant_actions.deleteCard(projectId, protocol, outputs,
                                            _children(service, mapper, currentUser, projectId, protocol), reason)

    # The web's pages, read with the user's own sign-in (so as the user)
    readPage = WebReader(authorization).read if authorization else None
    chains = TemplateChains(service, mapper, currentUser)

    def listTemplates(query: str, projectId=None, fromProtocolId=None, fromOutput=None):
        if projectId is not None:
            allowed(int(projectId))
        return chains.find(query, int(projectId) if projectId is not None else None, fromProtocolId, fromOutput)

    def listChains(projectId: int):
        allowed(projectId)
        return chains.chainsOf(projectId)

    def searchProjects(words: str, since: Optional[str], until: Optional[str], status: str):
        return search_projects.search(AssistantPostgresqlMapper(mapper.db),
                                      [row["id"] for row in listProjects()], words, since, until, status)

    def prepareReport(projectId: int, protocolId: Optional[str]):
        from app.backend.api.services.workflow_report import protocolIdsOf

        project = allowed(projectId)
        ids = protocolIdsOf(mapper, projectId, protocolId)
        return {"kind": "report", "projectId": int(projectId), "protocolId": protocolId or "",
                "project": str(project.get("name") or "").rstrip("/").split("/")[-1], "protocols": len(ids)}

    def compareProtocols(projectId: int, protocolIds: List[str]):
        from app.backend.api.services import compare_protocols
        from app.backend.api.services.workflow_report import describeProtocol

        allowed(projectId)
        ids = list(dict.fromkeys(protocolIds))
        if not compare_protocols.MIN_PROTOCOLS <= len(ids) <= compare_protocols.MAX_PROTOCOLS:
            raise ValueError("Compare two to four protocols")
        assistant, help_ = AssistantPostgresqlMapper(mapper.db), HelpChatPostgresqlMapper(mapper.db)
        for pid in ids:
            if not assistant.protocol(projectId, pid):
                raise ValueError("There is no protocol %s in that project" % pid)
        comparison = compare_protocols.compare([describeProtocol(assistant, help_, projectId, pid) for pid in ids])
        return dict(comparison, projectId=int(projectId))

    def serverLog(which: str, node: Optional[str], search: str):
        from app.backend.api.services.server_logs import readLog

        return readLog(which, node, search)

    reading = {"readPage": readPage, "listTemplates": listTemplates, "listChains": listChains,
               "searchProjects": searchProjects, "prepareReport": prepareReport,
               "compareProtocols": compareProtocols,
               # The server's logs only for who runs the installation
               "serverLog": serverLog if (hasPermission(currentUser, "settings.manage")
                                         or hasPermission(currentUser, "jobs.manage")) else None}
    if not canPropose:
        return AssistantTools(listProjects, listProtocols, protocolDetails, protocolLog, explainFailure, searchHelp,
                              **reading)

    def proposeTemplate(projectId: int, templateId: str, fromProtocolId: Optional[str], fromOutput: Optional[str],
                        anchor: Optional[str], reason: str):
        if fromProtocolId:
            workable(projectId, fromProtocolId)
        elif not _canWork(allowed(projectId)):
            raise PermissionError("The user can only look at that project, not run things in it")
        return chains.card(projectId, chains.plan(projectId, templateId, fromProtocolId, fromOutput, anchor), reason)

    def proposeSubset(projectId: int, protocolId: str, outputName: str, table: str, conditions, makes, name: str,
                      reason: str):
        protocol = workable(projectId, protocolId)
        plan = _subsetPlan(service, mapper, projectId, protocolId, outputName, table, conditions, makes)
        return {"kind": "action", "action": "subset", "projectId": int(projectId), "protocolId": str(protocolId),
                "label": protocol.get("label") or "", "outputName": outputName, "table": table,
                "conditions": plan["conditions"], "makes": plan["action"], "actions": plan["actions"],
                "total": plan["total"], "kept": len(plan["kept"]), "removed": len(plan["removed"]),
                "examples": plan["examples"], "name": name or "subset of %s" % outputName,
                "reason": str(reason or "")[:500]}

    def proposeContinue(projectId: int, chainId: int, stopProtocolId: Optional[str], reason: str):
        if stopProtocolId:
            workable(projectId, stopProtocolId)
        elif not _canWork(allowed(projectId)):
            raise PermissionError("The user can only look at that project, not run things in it")
        return chains.continueCard(projectId, chainId, stopProtocolId, reason)

    return AssistantTools(listProjects, listProtocols, protocolDetails, protocolLog, explainFailure, searchHelp,
                          proposeRelaunch, proposeStop, proposeNextStep, proposeDuplicate,
                          proposeDelete if canDelete else None, proposeTemplate=proposeTemplate,
                          proposeContinue=proposeContinue, proposeSubset=proposeSubset, **reading)


def _askAssistant(payload: HelpQuestion, settings: AssistantSettings, mapper, currentUser,
                  authorization: str = "") -> Dict[str, Any]:
    stored = settings.stored()
    usage = AssistantPostgresqlMapper(mapper.db)
    userId = int(currentUser["id"])
    # 0: no limit
    limit = int(stored["dailyLimit"] or 0)
    if limit > 0 and usage.usageToday(userId)["questions"] >= limit:
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
    propose = stored.get("mode") == "propose"
    agent = AssistantAgent(_providerOf(stored), _projectTools(mapper, currentUser, propose,
                                                              propose and bool(stored.get("allowDelete")),
                                                              authorization))
    try:
        answer = agent.answer(payload.question, contextLine(project, protocol),
                              [turn.dict() for turn in payload.history or []])
    except AssistantProviderError as error:
        logger.warning("The assistant could not answer: %s", error)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error))
    tokens = answer.pop("usage")
    usage.addUsage(userId, 1, tokens["inputTokens"], tokens["outputTokens"])
    if limit > 0:
        answer["left"] = max(0, limit - usage.usageToday(userId)["questions"])
    return answer


@router.post("/ask")
def ask(payload: HelpQuestion, request: Request, currentUser: dict = Depends(getCurrentUser),
        mapper: PostgresqlFlatMapper = Depends(getMapperDependency)) -> Dict[str, Any]:
    """{text, cards}: a short sentence and the pieces of help that answer the question; from the assistant, also
    the steps it took and how many questions are left today."""
    settings = _assistantFor(mapper, currentUser)
    if settings is not None:
        return _askAssistant(payload, settings, mapper, currentUser, request.headers.get("authorization") or "")

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


@router.post("/actions/apply")
def applyAction(payload: ActionPayload, currentUser: dict = Depends(getCurrentUser),
                mapper: PostgresqlFlatMapper = Depends(getMapperDependency)) -> Dict[str, Any]:
    """Run what the user confirmed on an assistant's card, checked again as things are now, through the same
    services as the web's own buttons."""
    from app.backend.api.services.project_service import ProjectService

    settings = _assistantFor(mapper, currentUser)
    stored = settings.stored() if settings is not None else {}
    if settings is None or stored.get("mode") != "propose":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The assistant may not propose actions")
    if payload.action == "delete" and not stored.get("allowDelete"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The assistant may not propose deletes")
    service = ProjectService()
    project = service.getProjectDbRow(mapper, payload.projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    checkProjectAccess(project, "work")
    if payload.action in ("template", "continue"):
        return _applyChain(payload, service, mapper, currentUser)
    if payload.action == "subset":
        return _applySubset(payload, service, mapper, currentUser)
    protocol = AssistantPostgresqlMapper(mapper.db).protocol(payload.projectId, payload.protocolId)
    try:
        help_ = help_index.protocolHelp((protocol or {}).get("className"))
        hasChildren = False
        if payload.action == "relaunch" and protocol is not None:
            preflight = _preflight(service, mapper, currentUser, payload.projectId, payload.protocolId,
                                   payload.mode or "restart")
            hasChildren = any(str(item.get("protocolId")) != str(protocol["protocolId"])
                              for item in preflight.get("affectedProtocols") or [])
        children = _children(service, mapper, currentUser, payload.projectId, protocol) \
            if payload.action == "delete" and protocol is not None else None
        plan = assistant_actions.applyChecks(protocol, help_, payload.action, payload.mode or "", payload.scope,
                                             payload.changes or {}, hasChildren, payload.confirm, children)
    except (ProposalError, PermissionError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))

    answer: Dict[str, Any] = {"ok": True}
    if payload.action in ("stop", "duplicate", "delete"):
        if not service.loadPostgresqlRuntimeProjectForMutation(mapper=mapper, projectId=payload.projectId,
                                                               currentUser=currentUser):
            raise HTTPException(status_code=404, detail="Project not found")
    if payload.action == "stop":
        result = service.stopProtocol(mapper, payload.projectId, [payload.protocolId],
                                      protocolIdIsScipionId=True) or {}
    elif payload.action == "delete":
        result = service.deleteProtocol(mapper, payload.projectId, [payload.protocolId],
                                        protocolIdIsScipionId=True) or {}
    elif payload.action == "duplicate":
        from app.backend.models.protocol_model import DuplicateItem

        result = service.duplicateProtocol(mapper, payload.projectId, [DuplicateItem(id=payload.protocolId)],
                                           protocolIdIsScipionId=True) or {}
        copies = result.get("duplicated") or []
        if copies and not result.get("errors"):
            answer["newProtocolId"] = str(copies[0].get("newId"))
            if plan["params"]:
                # With the copy's inputs, as the form saves: a save without them leaves them empty
                params = dict(AssistantPostgresqlMapper(mapper.db).pointerParams(payload.projectId,
                                                                                 answer["newProtocolId"]),
                              **plan["params"])
                _, saveErrors = service.saveProtocol(mapper, payload.projectId, answer["newProtocolId"],
                                                     protocol["className"], params, setToSave=True,
                                                     protocolIdIsScipionId=True)
                result = dict(result, errors=list(result.get("errors") or []) + list(saveErrors or []))
    else:
        # With its inputs, as the protocol form relaunches one
        params = dict(AssistantPostgresqlMapper(mapper.db).pointerParams(payload.projectId, payload.protocolId),
                      **plan["params"])
        result = service.executeProtocolWorkflow(mapper=mapper, projectId=payload.projectId,
                                                 protocolId=int(payload.protocolId),
                                                 protocolClassName=protocol["className"], params=params,
                                                 mode=plan["mode"], scope=plan["scope"],
                                                 currentUserId=currentUser["id"]) or {}
    errors = [str(error) for error in result.get("errors") or []]
    recordAudit(mapper, currentUser, "assistant.actionApplied", "project", payload.projectId,
                str(payload.protocolId), {"action": payload.action, "mode": plan.get("mode"),
                                          "scope": plan.get("scope"), "params": plan.get("params"),
                                          "newProtocolId": answer.get("newProtocolId"), "errors": errors[:3]})
    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(errors))
    return answer


def _subsetPlan(service, mapper, projectId: int, protocolId: str, outputName: str, table: str, conditions,
                makes: Optional[str]) -> Dict[str, Any]:
    from app.backend.api.services import subset_by_values

    common = {"projectId": projectId, "protocolId": int(protocolId), "outputName": outputName, "tableName": table,
              "mapper": mapper, "protocolIdIsScipionId": True}
    try:
        schema = service.getMetadataTableSchemaService(**common) or {}
    except Exception:
        logger.warning("Could not read the table %s of %s.%s", table, protocolId, outputName, exc_info=True)
        raise subset_by_values.SubsetError("Protocol %s has no table %s in %s" % (protocolId, table, outputName))
    return subset_by_values.plan(
        schema, lambda page, size: service.getMetadataTablePageService(
            page=page, pageSize=size, sortBy="id", asc=True, selectionOnly=False, **common), conditions, makes)


def _applySubset(payload: ActionPayload, service, mapper, currentUser) -> Dict[str, Any]:
    """The subset the user confirmed, chosen again by its values now, made with the viewer's own action."""
    from app.backend.api.services.subset_by_values import SubsetError

    table = payload.table or "objects"
    try:
        if not payload.outputName or not payload.protocolId:
            raise SubsetError("Which output?")
        plan = _subsetPlan(service, mapper, payload.projectId, payload.protocolId, payload.outputName, table,
                           payload.conditions or [], payload.makes)
    except SubsetError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if not service.loadPostgresqlRuntimeProjectForMutation(mapper=mapper, projectId=payload.projectId,
                                                           currentUser=currentUser):
        raise HTTPException(status_code=404, detail="Project not found")
    name = (payload.name or "").strip() or "subset of %s" % payload.outputName
    result = service.runMetadataTableActionService(
        projectId=payload.projectId, protocolId=int(payload.protocolId), outputName=payload.outputName,
        tableName=table, action=plan["action"], subsetName=name, ids=plan["kept"], currentUser=currentUser,
        mapper=mapper, protocolIdIsScipionId=True)
    errors = [str(error) for error in (result.get("errors") or [])] if isinstance(result, dict) else []
    if isinstance(result, dict) and result.get("success") is False and not errors:
        errors = [str(result.get("message") or "The subset could not be made")]
    recordAudit(mapper, currentUser, "assistant.actionApplied", "project", payload.projectId, str(payload.protocolId),
                {"action": "subset", "output": payload.outputName, "table": table, "makes": plan["action"],
                 "conditions": plan["conditions"], "kept": len(plan["kept"]), "total": plan["total"],
                 "errors": errors[:3]})
    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(errors))
    return {"ok": True, "kept": len(plan["kept"]), "total": plan["total"]}


def _applyChain(payload: ActionPayload, service, mapper, currentUser) -> Dict[str, Any]:
    """A template added (and launched up to its first stops) or a chain gone on with after a stop."""
    chains = TemplateChains(service, mapper, currentUser)
    try:
        if payload.action == "template":
            if not payload.templateId:
                raise ProposalError("Which template?")
            result = chains.apply(payload.projectId, payload.templateId, payload.protocolId or None,
                                  payload.fromOutput, payload.anchor, payload.links or {}, payload.stops or [],
                                  payload.fields or {}, payload.launch is not False)
        else:
            if payload.chainId is None:
                raise ProposalError("Which chain?")
            result = chains.launchNext(payload.projectId, payload.chainId, payload.protocolId or None)
    except ProposalError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    recordAudit(mapper, currentUser, "assistant.actionApplied", "project", payload.projectId,
                str(payload.templateId or payload.chainId or ""),
                {"action": payload.action, "templateId": payload.templateId, "chainId": result.get("chainId") or
                 payload.chainId, "from": payload.protocolId, "launched": result.get("launched"),
                 "errors": (result.get("errors") or [])[:3]})
    return dict(result, ok=not result.get("errors"))


@router.post("/report")
def processingReport(payload: ReportPayload, currentUser: dict = Depends(getCurrentUser),
                     mapper: PostgresqlFlatMapper = Depends(getMapperDependency)):
    """The processing report of a project (or of what led to one protocol) as a PDF, or its workflow file."""
    from fastapi.responses import Response

    from app.backend.api.services import workflow_report, workflow_report_pdf
    from app.backend.api.services.project_service import ProjectService

    try:
        report = workflow_report.reportData(ProjectService(), mapper, currentUser, payload.projectId,
                                            payload.protocolId or None)
    except PermissionError:
        raise HTTPException(status_code=404, detail="Project not found")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    stem = "%s%s" % (report["project"], "_up_to_%s" % payload.protocolId if payload.protocolId else "")
    stem = "".join(char if char.isalnum() or char in "-_." else "_" for char in stem)
    if payload.format == "workflow":
        if not report["workflowFile"]:
            raise HTTPException(status_code=500, detail="The workflow could not be exported")
        return Response(report["workflowFile"], media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="%s_workflow.json"' % stem})
    methods = None
    settings = _assistantFor(mapper, currentUser) if payload.methods else None
    if settings is not None:
        try:
            written = workflow_report.writeMethods(_providerOf(settings.stored()), report)
            methods = written["text"] or None
            AssistantPostgresqlMapper(mapper.db).addUsage(int(currentUser["id"]), 1,
                                                          written["usage"]["inputTokens"],
                                                          written["usage"]["outputTokens"])
        except AssistantProviderError as error:
            logger.warning("The assistant could not write the methods of project %s: %s", payload.projectId, error)
    try:
        from scipionapi_cli.version import __version__ as version
    except Exception:
        version = ""
    try:
        pdf = workflow_report_pdf.render(report, methods, version)
    except workflow_report_pdf.ReportUnavailable as error:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(error))
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="%s_report.pdf"' % stem})


# Settings (administrators) ---------------------------------------------------------------------------------------

@router.get("/settings")
def getAssistantSettings(mapper: PostgresqlFlatMapper = Depends(getMapperDependency),
                         currentUser: dict = Depends(requirePermission("settings.manage"))) -> Dict[str, Any]:
    settings = AssistantSettings(mapper.db)
    answer = settings.view()
    try:
        answer["usage"] = {"today": AssistantPostgresqlMapper(mapper.db).totals(0),
                           "last30Days": AssistantPostgresqlMapper(mapper.db).totals(29)}
    except Exception:
        # The settings still load without the usage (its table comes with a migration)
        logger.warning("Could not read the assistant's usage", exc_info=True)
        mapper.db.rollback()
    return answer


@router.put("/settings")
def saveAssistantSettings(payload: AssistantSettingsPayload, mapper: PostgresqlFlatMapper = Depends(getMapperDependency),
                          currentUser: dict = Depends(requirePermission("settings.manage"))) -> Dict[str, Any]:
    settings = AssistantSettings(mapper.db).save(payload.dict(), userId=currentUser.get("id"))
    recordAudit(mapper, currentUser, "settings.assistantUpdated", "settings", None, "assistant",
                {"enabled": settings["enabled"], "provider": settings["provider"], "model": settings["model"],
                 "dailyLimit": settings["dailyLimit"], "key": "changed" if payload.key is not None else "kept"})
    return settings


def _providerForPayload(payload: AssistantSettingsPayload, mapper):
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
