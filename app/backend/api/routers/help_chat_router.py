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
from app.backend.api.services import (assistant_actions, assistant_new_project, search_projects, streaming_watch,
                                      tutorial_progress)
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


# How many turns of a conversation the assistant reads; how long a conversation's title is
MAX_HISTORY_TURNS = 12
TITLE_CHARS = 80
MAX_CONVERSATIONS = 100
TUTOR = "tutor"


class HistoryTurn(BaseModel):
    role: str = Field(..., max_length=16)
    text: str = Field("", max_length=20000)


class HelpQuestion(BaseModel):
    question: str = Field(..., max_length=MAX_QUESTION * 4)
    # Where the user is: the project open and the protocol selected in it (its Scipion id), if any
    projectId: Optional[int] = None
    protocolId: Optional[str] = Field(None, max_length=32)
    # The conversation so far, for the assistant (the rule-based answers do not use it); with conversationId the
    # server reads it from the conversation kept instead
    history: Optional[List[HistoryTurn]] = Field(None, max_items=40)
    # The conversation this question goes on (one of the user's own); a new one when left out
    conversationId: Optional[int] = None
    # "tutor": a new conversation where the assistant guides a new user step by step (kept with the conversation)
    mode: Optional[str] = Field(None, max_length=16)


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
    # The protocols the card listed (a subworkflow, the protocols to tag): the apply refuses if they changed
    protocolIds: Optional[List[str]] = Field(None, max_items=200)
    # The tag's name to add
    tag: Optional[str] = Field(None, max_length=200)
    # A rename: the changes the card listed ({field: name|comment, to})
    renames: Optional[List[Dict[str, Any]]] = Field(None, max_items=2)
    # How long to watch a stream, in hours
    hours: Optional[int] = Field(None, ge=1, le=72)


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


def _subworkflow(service, mapper, currentUser, projectId: int, protocol: Dict[str, Any],
                 withOutputs: bool = False) -> List[Dict[str, Any]]:
    """The protocol and every protocol depending on it, the protocol first; with their outputs if asked."""
    preflight = _preflight(service, mapper, currentUser, projectId, str(protocol["protocolId"]), "restart")
    rootId = str(protocol["protocolId"])
    items = [{"protocolId": rootId, "label": protocol.get("label") or "", "className": protocol.get("className") or "",
              "status": protocol.get("status") or "",
              "active": (protocol.get("status") or "").lower() in assistant_actions.ACTIVE_STATUSES}]
    for item in preflight.get("affectedProtocols") or []:
        if str(item.get("protocolId")) != rootId:
            items.append({"protocolId": str(item.get("protocolId")), "label": item.get("runName") or "",
                          "status": item.get("status") or "", "active": bool(item.get("active"))})
    if withOutputs and len(items) <= assistant_actions.MAX_SUBWORKFLOW:
        outputs = HelpChatPostgresqlMapper(mapper.db)
        for item in items:
            item["outputs"] = outputs.protocolOutputs(projectId, item["protocolId"])
    return items


def _depending(service, mapper, currentUser, projectId: int, protocols: List[Dict[str, Any]],
               action: str) -> Dict[str, List[str]]:
    """Each protocol's depending protocols (only needed to relaunch, and only for the ones not running)."""
    if action != "relaunchmany":
        return {}
    return {str(protocol["protocolId"]): [item["protocolId"] for item in
                                          _subworkflow(service, mapper, currentUser, projectId, protocol)[1:]]
            for protocol in protocols
            if (protocol.get("status") or "").lower() not in assistant_actions.ACTIVE_STATUSES}


def _tagsOf(service, mapper, currentUser, projectId: int, protocolIds: List[str]) -> Dict[str, List[str]]:
    return {protocolId: list((service.listProtocolTags(mapper=mapper, projectId=projectId, protocolId=int(protocolId),
                                                      currentUser=currentUser, protocolIdIsScipionId=True)
                              or {}).get("tagIds") or []) for protocolId in protocolIds}


def _tagNames(service, mapper, currentUser, projectId: int, protocolId: str) -> List[str]:
    """The names of the protocol's tags, as the graph shows them."""
    try:
        ids = _tagsOf(service, mapper, currentUser, projectId, [str(protocolId)])[str(protocolId)]
        names = {str(tag.get("id")): tag.get("title") for tag in mapper.listProtocolTags(projectId=projectId) or []}
    except Exception:
        return []
    return [names[tagId] for tagId in ids if names.get(tagId)]


def _currentComment(service, mapper, currentUser, projectId: int, protocolId: str) -> str:
    """The protocol's comment as the graph shows it."""
    if not service.loadPostgresqlRuntimeProjectForMutation(mapper=mapper, projectId=projectId,
                                                           currentUser=currentUser):
        raise PermissionError("The user cannot see that project")
    protocol = service._getScipionProtocolByScipionId(protocolId)
    getter = getattr(protocol, "getObjComment", None)
    return str((getter() if callable(getter) else getattr(protocol, "_objComment", "")) or "")


def _waitFor(mapper, projectId: int, protocolIds: List[str]) -> List[Dict[str, Any]]:
    helper = AssistantPostgresqlMapper(mapper.db)
    found = []
    for protocolId in dict.fromkeys(str(item) for item in protocolIds or []):
        row = helper.protocol(projectId, protocolId)
        if not row:
            raise ProposalError("There is no protocol %s in that project" % protocolId)
        found.append(row)
    return found


def _projectTag(mapper, projectId: int, title: str) -> Optional[Dict[str, Any]]:
    """The project's tag with that name, in any case."""
    wanted = title.strip().lower()
    return next((dict(tag) for tag in mapper.listProtocolTags(projectId=projectId) or []
                 if str(tag.get("title") or "").strip().lower() == wanted), None)


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
        row["tags"] = _tagNames(service, mapper, currentUser, projectId, protocolId)
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

    def proposeDuplicate(projectId: int, protocolId: str, changes: Dict[str, Any], reason: str, launch: bool = False):
        protocol = workable(projectId, protocolId)
        return assistant_actions.duplicateCard(projectId, protocol, help_index.protocolHelp(protocol.get("className")),
                                               changes, reason, launch)

    def proposeSubworkflow(action: str, projectId: int, protocolId: str, reason: str, launch: bool = False):
        protocol = workable(projectId, protocolId)
        items = _subworkflow(service, mapper, currentUser, projectId, protocol, action != "copyworkflow")
        return assistant_actions.subworkflowCard(action, projectId, items, reason, launch)

    def proposeRename(projectId: int, protocolId: str, name: Optional[str], comment: Optional[str], reason: str,
                      addToComment: bool = False):
        protocol = workable(projectId, protocolId)
        return assistant_actions.renameCard(projectId, protocol,
                                            _currentComment(service, mapper, currentUser, projectId, protocolId),
                                            name, comment, reason, addToComment)

    def proposeSchedule(projectId: int, protocolId: str, waitFor: List[str], reason: str):
        protocol = workable(projectId, protocolId)
        depending = [item["protocolId"] for item in _subworkflow(service, mapper, currentUser, projectId, protocol)[1:]]
        return assistant_actions.scheduleCard(projectId, protocol, _waitFor(mapper, projectId, waitFor), depending,
                                              reason)

    def proposeTag(projectId: int, protocolIds: List[str], tag: str, reason: str, remove: bool = False):
        protocols = [workable(projectId, protocolId) for protocolId in dict.fromkeys(protocolIds)]
        tagged = _tagsOf(service, mapper, currentUser, projectId, [str(item["protocolId"]) for item in protocols])
        if remove and not tag.strip():
            tag = assistant_actions.tagToRemove(tagged, mapper.listProtocolTags(projectId=projectId) or [])
        title = assistant_actions.tagTitle(tag)
        return assistant_actions.tagCard(projectId, protocols, title, _projectTag(mapper, projectId, title),
                                         tagged, reason, remove)

    def proposeMany(projectId: int, action: str, protocolIds: List[str], reason: str):
        protocols = [workable(projectId, protocolId) for protocolId in dict.fromkeys(protocolIds)]
        return assistant_actions.manyCard(projectId, action, protocols,
                                          _depending(service, mapper, currentUser, projectId, protocols, action),
                                          reason)

    def proposeNewProject(args: Dict[str, Any]):
        if not hasPermission(currentUser, "projects.create"):
            raise PermissionError("The user may not create projects")
        data = assistant_new_project.plan(args.get("name"), args.get("folder"), args.get("data"),
                                          args.get("pattern"), args, args.get("streaming") is True,
                                          args.get("gainFile"), hasPermission(currentUser, "files.browseServer"))
        return assistant_new_project.card(data, str(args.get("reason") or ""))

    def proposeWatch(projectId: int, hours: Any, reason: str, stop: bool = False):
        project = allowed(projectId)
        name = streaming_watch.projectName(mapper.db, projectId) if project else ""
        active = AssistantPostgresqlMapper(mapper.db).activeWatch(currentUser["id"], projectId)
        if stop:
            return streaming_watch.unwatchCard(projectId, name, active, reason)
        from app.backend.api.services.streaming_monitor import watchSnapshot

        return streaming_watch.watchCard(projectId, name, watchSnapshot(mapper, projectId), hours, active, reason)

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

    def showProtocol(projectId: int, protocolId: str):
        allowed(projectId)
        row = AssistantPostgresqlMapper(mapper.db).protocol(projectId, protocolId)
        if not row:
            raise ProposalError("There is no protocol %s in that project" % protocolId)
        return {"projectId": int(projectId), "protocolId": str(row["protocolId"]), "label": row.get("label") or ""}

    reading = {"readPage": readPage, "listTemplates": listTemplates, "listChains": listChains,
               "showProtocol": showProtocol,
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
                          proposeContinue=proposeContinue, proposeSubset=proposeSubset,
                          proposeSubworkflow=proposeSubworkflow, proposeTag=proposeTag, proposeRename=proposeRename,
                          proposeSchedule=proposeSchedule, proposeMany=proposeMany,
                          proposeNewProject=proposeNewProject, proposeWatch=proposeWatch, **reading)


def _askAssistant(payload: HelpQuestion, settings: AssistantSettings, mapper, currentUser,
                  authorization: str = "", history: Optional[List[Dict[str, Any]]] = None,
                  tutor: bool = False) -> Dict[str, Any]:
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
    progress = None
    if tutor and project:
        progress = tutorial_progress.progress(usage.projectOutputs(int(payload.projectId)))
    propose = stored.get("mode") == "propose"
    agent = AssistantAgent(_providerOf(stored), _projectTools(mapper, currentUser, propose,
                                                              propose and bool(stored.get("allowDelete")),
                                                              authorization))
    try:
        answer = agent.answer(payload.question, contextLine(project, protocol),
                              history if history is not None else [turn.dict() for turn in payload.history or []],
                              (tutorial_progress.describe(progress) if progress else "") if tutor else None)
    except AssistantProviderError as error:
        logger.warning("The assistant could not answer: %s", error)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error))
    if progress and progress.get("kind"):
        # Where the project is on its road, under every answer of the tutor
        answer["cards"] = [tutorial_progress.card(int(payload.projectId), progress)] + list(answer.get("cards") or [])
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
    conversations = AssistantPostgresqlMapper(mapper.db)
    userId = int(currentUser["id"])
    history = None
    mode = TUTOR if payload.mode == TUTOR else ""
    if payload.conversationId is not None:
        conversation = conversations.conversation(userId, payload.conversationId)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        mode = conversation.get("mode") or ""
        # The turns kept, not the ones the browser sends
        history = [{"role": row["role"], "text": row["text"]}
                   for row in conversations.messages(payload.conversationId, MAX_HISTORY_TURNS)]
    settings = _assistantFor(mapper, currentUser)
    if settings is not None:
        answer = _askAssistant(payload, settings, mapper, currentUser, request.headers.get("authorization") or "",
                               history, mode == TUTOR)
    elif mode == TUTOR:
        raise HTTPException(status_code=400, detail="The tutor needs the AI assistant, which is not on for you")
    else:
        answer = _askByRules(payload, mapper, currentUser)
    if mode:
        answer["mode"] = mode
    answer["conversationId"] = _keepTurn(conversations, userId, payload, answer, mode)
    return answer


def _keepTurn(conversations, userId: int, payload: HelpQuestion, answer: Dict[str, Any],
              mode: str = "") -> Optional[int]:
    """Keep the question and its answer in the user's conversation (a new one for a first question); the
    conversation's id. A conversation that cannot be kept does not lose the answer."""
    try:
        conversationId = payload.conversationId
        if conversationId is None:
            title = " ".join(payload.question.split())[:TITLE_CHARS]
            conversationId = conversations.addConversation(userId, payload.projectId, title, mode)
        conversations.addMessage(conversationId, "user", payload.question)
        kept = {key: value for key, value in answer.items() if key not in ("left", "conversationId")}
        conversations.addMessage(conversationId, "assistant", str(answer.get("text") or ""), kept)
        return conversationId
    except Exception:
        logger.warning("Could not keep the help chat conversation of user %s", userId, exc_info=True)
        return payload.conversationId


def _askByRules(payload: HelpQuestion, mapper, currentUser) -> Dict[str, Any]:
    """The answer of the help without a model (services/help_chat.py)."""
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
    if payload.action in ("delete", "deletefrom") and not stored.get("allowDelete"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The assistant may not propose deletes")
    service = ProjectService()
    if payload.action == "newproject":
        return _applyNewProject(payload, service, mapper, currentUser)
    project = service.getProjectDbRow(mapper, payload.projectId, currentUser)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if payload.action in ("watch", "unwatch"):
        return _applyWatch(payload, mapper, currentUser)
    checkProjectAccess(project, "work")
    if payload.action in ("template", "continue"):
        return _applyChain(payload, service, mapper, currentUser)
    if payload.action == "subset":
        return _applySubset(payload, service, mapper, currentUser)
    if payload.action in ("copyworkflow", "reset", "deletefrom"):
        return _applySubworkflow(payload, service, mapper, currentUser)
    if payload.action in ("tag", "untag"):
        return _applyTag(payload, service, mapper, currentUser)
    if payload.action == "rename":
        return _applyRename(payload, service, mapper, currentUser)
    if payload.action == "schedule":
        return _applySchedule(payload, service, mapper, currentUser)
    if payload.action in ("stopmany", "relaunchmany"):
        return _applyMany(payload, service, mapper, currentUser)
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

        result = _duplicate(service, mapper, payload.projectId, [DuplicateItem(id=payload.protocolId)])
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
            if payload.launch and not result.get("errors"):
                launched = _launchCopy(service, mapper, currentUser, payload.projectId, answer["newProtocolId"],
                                       protocol["className"], plan["params"], "single")
                result = dict(result, errors=list(launched.get("errors") or []))
                answer["started"] = not launched.get("errors")
    else:
        # With its inputs, as the protocol form relaunches one
        params = dict(AssistantPostgresqlMapper(mapper.db).pointerParams(payload.projectId, payload.protocolId),
                      **plan["params"])
        result = _executeWorkflow(service, mapper, currentUser, payload.projectId, payload.protocolId,
                                  protocol["className"], params, plan["mode"], plan["scope"])
    errors = [str(error) for error in result.get("errors") or []]
    recordAudit(mapper, currentUser, "assistant.actionApplied", "project", payload.projectId,
                str(payload.protocolId), {"action": payload.action, "mode": plan.get("mode"),
                                          "scope": plan.get("scope"), "params": plan.get("params"),
                                          "newProtocolId": answer.get("newProtocolId"), "errors": errors[:3]})
    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(errors))
    return answer


def _launchCopy(service, mapper, currentUser, projectId: int, protocolId: str, className: str,
                params: Dict[str, Any], scope: str) -> Dict[str, Any]:
    """Launch a copy just made, with its inputs, as the protocol form launches a new protocol."""
    full = dict(AssistantPostgresqlMapper(mapper.db).pointerParams(projectId, protocolId), **(params or {}))
    return _executeWorkflow(service, mapper, currentUser, projectId, protocolId, className, full, "restart", scope)


def _duplicate(service, mapper, projectId: int, items) -> Dict[str, Any]:
    """The project's own copy (all or none); its refusal as errors, not raised."""
    try:
        return service.duplicateProtocol(mapper, projectId, items, protocolIdIsScipionId=True) or {}
    except HTTPException as error:
        return {"errors": ["The copy could not be made: %s" % "; ".join(_errorTexts(error.detail) or ["unknown"])]}


def _errorTexts(detail: Any) -> List[str]:
    """A service's error (a text, a list of texts, or {detail}) as texts the chat shows."""
    if isinstance(detail, (list, tuple)):
        return [text for item in detail for text in _errorTexts(item)]
    if isinstance(detail, dict):
        return _errorTexts(detail.get("detail") or detail.get("error") or detail.get("message") or str(detail))
    return [str(detail)] if detail not in (None, "") else []


def _executeWorkflow(service, mapper, currentUser, projectId: int, protocolId: str, className: str,
                     params: Dict[str, Any], mode: str, scope: str) -> Dict[str, Any]:
    """Launch or relaunch as the protocol form does: with the protocol's internal id (the launch takes an id as
    internal first, so the number the user sees could name another protocol of the project). Its refusals come
    back as errors, not raised."""
    from app.backend.runtime.protocol_identity import ProtocolIdentityResolver

    dbId = ProtocolIdentityResolver(mapper=mapper, projectId=projectId) \
        .resolvePostgresqlProtocolDbIdFromScipionProtocolId(protocolId)
    if dbId is None:
        return {"errors": ["Protocol #%s is not in the project any more" % protocolId]}
    try:
        return service.executeProtocolWorkflow(mapper=mapper, projectId=projectId, protocolId=int(dbId),
                                               protocolClassName=className, params=params, mode=mode, scope=scope,
                                               currentUserId=currentUser["id"]) or {}
    except HTTPException as error:
        return {"errors": _errorTexts(error.detail) or ["The launch was refused"]}


def _applySubworkflow(payload: ActionPayload, service, mapper, currentUser) -> Dict[str, Any]:
    """Copy, reset or delete a protocol and everything depending on it, as the card listed them."""
    protocol = AssistantPostgresqlMapper(mapper.db).protocol(payload.projectId, payload.protocolId)
    try:
        if protocol is None:
            raise ProposalError("The protocol is not in the project any more")
        items = _subworkflow(service, mapper, currentUser, payload.projectId, protocol,
                             payload.action != "copyworkflow")
        if payload.action == "deletefrom":
            assistant_actions.deleteFromChecks(items, payload.protocolIds, payload.confirm)
        else:
            assistant_actions.subworkflowCard(payload.action, payload.projectId, items)
            assistant_actions.sameProtocols(payload.protocolIds, items)
    except (ProposalError, PermissionError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if not service.loadPostgresqlRuntimeProjectForMutation(mapper=mapper, projectId=payload.projectId,
                                                           currentUser=currentUser):
        raise HTTPException(status_code=404, detail="Project not found")
    ids = [item["protocolId"] for item in items]
    answer: Dict[str, Any] = {"ok": True, "protocols": len(ids)}
    if payload.action == "reset":
        result = service.resetProtocolFrom(mapper, payload.projectId, int(payload.protocolId)) or {}
    elif payload.action == "deletefrom":
        result = service.deleteProtocol(mapper, payload.projectId, ids, protocolIdIsScipionId=True) or {}
    else:
        from app.backend.models.protocol_model import DuplicateItem

        result = _duplicate(service, mapper, payload.projectId, [DuplicateItem(id=item) for item in ids])
        copies = {str(item.get("sourceId")): str(item.get("newId")) for item in result.get("duplicated") or []}
        if copies.get(str(protocol["protocolId"])):
            answer["newProtocolId"] = copies[str(protocol["protocolId"])]
        if payload.launch and answer.get("newProtocolId") and not result.get("errors"):
            # The copy of the first protocol with everything after it
            launched = _launchCopy(service, mapper, currentUser, payload.projectId, answer["newProtocolId"],
                                   protocol["className"], {}, "all")
            result = dict(result, errors=list(launched.get("errors") or []))
            answer["started"] = not launched.get("errors")
    errors = [str(error) for error in result.get("errors") or []]
    recordAudit(mapper, currentUser, "assistant.actionApplied", "project", payload.projectId,
                str(payload.protocolId), {"action": payload.action, "protocols": ids,
                                          "newProtocolId": answer.get("newProtocolId"),
                                          "launch": bool(payload.launch), "errors": errors[:3]})
    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(errors))
    return answer


def _applyTag(payload: ActionPayload, service, mapper, currentUser) -> Dict[str, Any]:
    """Add the tag (made if the project has none with that name) to the protocols the card listed."""
    from app.backend.api.schemas.tags_schema import ProtocolTagCreateIn

    helper = AssistantPostgresqlMapper(mapper.db)
    try:
        title = assistant_actions.tagTitle(payload.tag)
        ids = list(dict.fromkeys(str(item) for item in payload.protocolIds or []))
        if not ids or len(ids) > assistant_actions.MAX_TAGGED:
            raise ProposalError("Say which protocols to tag (at most %d)" % assistant_actions.MAX_TAGGED)
        missing = [protocolId for protocolId in ids if not helper.protocol(payload.projectId, protocolId)]
        if missing:
            raise ProposalError("Not in the project any more: %s" % ", ".join("#%s" % item for item in missing))
    except ProposalError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    tag = _projectTag(mapper, payload.projectId, title)
    if payload.action == "untag":
        return _removeTag(payload, service, mapper, currentUser, tag, title, ids)
    created = tag is None
    if created:
        tag = service.createProjectTag(mapper=mapper, projectId=payload.projectId, currentUser=currentUser,
                                       payload=ProtocolTagCreateIn(title=title))
    current = _tagsOf(service, mapper, currentUser, payload.projectId, ids)
    tagged = []
    for protocolId in ids:
        if tag["id"] not in current[protocolId]:
            service.setProtocolTags(mapper=mapper, projectId=payload.projectId, protocolId=int(protocolId),
                                    tagIds=current[protocolId] + [tag["id"]], currentUser=currentUser,
                                    protocolIdIsScipionId=True)
            tagged.append(protocolId)
    recordAudit(mapper, currentUser, "assistant.actionApplied", "project", payload.projectId, ids[0],
                {"action": "tag", "tag": tag.get("title"), "created": created, "protocols": tagged})
    return {"ok": True, "tag": tag.get("title"), "newTag": created, "tagged": tagged}


def _applyRename(payload: ActionPayload, service, mapper, currentUser) -> Dict[str, Any]:
    """Rename the protocol or change its comment, as the graph's own rename does."""
    protocol = AssistantPostgresqlMapper(mapper.db).protocol(payload.projectId, payload.protocolId)
    try:
        if protocol is None:
            raise ProposalError("The protocol is not in the project any more")
        name, comment = assistant_actions.renamed(
            protocol, _currentComment(service, mapper, currentUser, payload.projectId, payload.protocolId),
            payload.renames or [])
    except (ProposalError, PermissionError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    try:
        result = service.renameProtocol(mapper, payload.projectId, payload.protocolId, name, comment,
                                        protocolIdIsScipionId=True) or {}
    except HTTPException as error:
        result = {"errors": _errorTexts(error.detail)}
    errors = [str(error) for error in result.get("errors") or []]
    recordAudit(mapper, currentUser, "assistant.actionApplied", "project", payload.projectId,
                str(payload.protocolId), {"action": "rename", "name": name, "errors": errors[:3]})
    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(errors))
    return {"ok": True, "name": name}


def _applyMany(payload: ActionPayload, service, mapper, currentUser) -> Dict[str, Any]:
    """Stop or relaunch the protocols the card listed, each as its own button would. One that fails does not
    stop the others: the answer says which went and which did not."""
    helper = AssistantPostgresqlMapper(mapper.db)
    listed = [str(item) for item in payload.protocolIds or []]
    try:
        protocols = [helper.protocol(payload.projectId, protocolId) for protocolId in listed]
        if not listed or None in protocols:
            raise ProposalError("A protocol of the card is not in the project any more")
        plan = assistant_actions.manyChecks(
            payload.action, protocols, _depending(service, mapper, currentUser, payload.projectId, protocols,
                                                  payload.action),
            listed, payload.mode == "restart", payload.scope)
    except (ProposalError, PermissionError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    done, failed = [], []
    if payload.action == "stopmany":
        if not service.loadPostgresqlRuntimeProjectForMutation(mapper=mapper, projectId=payload.projectId,
                                                               currentUser=currentUser):
            raise HTTPException(status_code=404, detail="Project not found")
        try:
            result = service.stopProtocol(mapper, payload.projectId, plan["ids"], protocolIdIsScipionId=True) or {}
            errors = [str(error) for error in result.get("errors") or []]
        except HTTPException as error:
            errors = _errorTexts(error.detail) or ["The stop was refused"]
        if errors:
            failed = [{"protocolId": "", "error": "; ".join(errors)}]
        else:
            done = list(plan["ids"])
    else:
        classes = {str(item["protocolId"]): item.get("className") for item in protocols}
        for protocolId in plan["ids"]:
            params = helper.pointerParams(payload.projectId, protocolId)
            result = _executeWorkflow(service, mapper, currentUser, payload.projectId, protocolId,
                                      classes[protocolId], params, plan["modes"][protocolId], plan["scope"])
            errors = [str(error) for error in result.get("errors") or []]
            if errors:
                failed.append({"protocolId": protocolId, "error": "; ".join(errors)})
            else:
                done.append(protocolId)
    recordAudit(mapper, currentUser, "assistant.actionApplied", "project", payload.projectId,
                ",".join(plan["ids"])[:200], {"action": payload.action, "scope": plan.get("scope"),
                                              "modes": plan.get("modes"), "done": done,
                                              "failed": [item["protocolId"] for item in failed]})
    if not done:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="; ".join(("#%s: %s" % (item["protocolId"], item["error"])) if item["protocolId"]
                                             else item["error"] for item in failed) or "Nothing was done")
    return {"ok": True, "done": done, "failed": failed}


def _applyNewProject(payload: ActionPayload, service, mapper, currentUser) -> Dict[str, Any]:
    """Make the project and add its import, saved for the user to review; checked again as things are now. An
    import that cannot be added takes the new project away again."""
    from app.backend.api.schemas.project_schema import ProjectCreate
    from app.backend.api.schemas.protocols_schema import WorkflowImportRequest

    fields = payload.fields or {}
    try:
        if not hasPermission(currentUser, "projects.create"):
            raise PermissionError("You may not create projects")
        data = assistant_new_project.plan(payload.name, fields.get("folder"), fields.get("data"),
                                          fields.get("pattern"), fields, fields.get("streaming") is True,
                                          fields.get("gainFile"), hasPermission(currentUser, "files.browseServer"))
    except (ProposalError, PermissionError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    project = service.createProject(mapper, ProjectCreate(name=data["name"],
                                                          description="Made from the help chat"), currentUser)
    projectId = int(project["id"])
    errors: List[str] = []
    protocolId = None
    try:
        if not service.loadPostgresqlRuntimeProjectForMutation(mapper=mapper, projectId=projectId,
                                                               currentUser=currentUser):
            raise RuntimeError("The new project could not be opened")
        imported = service.importWorkflowProtocolsService(
            mapper=mapper, projectId=projectId, currentUser=currentUser,
            payload=WorkflowImportRequest(workflow=[assistant_new_project.importProtocol(data)]))
        errors = [str(error) for error in imported.get("errors") or []]
        protocolId = next((str(item["newId"]) for item in imported.get("created") or []), None)
        if protocolId is None and not errors:
            errors = ["The import was not added"]
    except HTTPException as error:
        errors = _errorTexts(error.detail) or ["The import was not added"]
    except Exception as error:
        logger.warning("Could not add the import to the new project %s", projectId, exc_info=True)
        errors = [str(error)]
    if errors:
        try:
            service.deleteProject(mapper, currentUser, projectId)
        except Exception:
            logger.warning("Could not take away the new project %s", projectId, exc_info=True)
    recordAudit(mapper, currentUser, "assistant.actionApplied", "project", projectId, data["name"],
                {"action": "newproject", "folder": data["folder"], "pattern": data["files"]["pattern"],
                 "files": data["files"]["count"], "errors": errors[:3]})
    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="The project was not made: %s" % "; ".join(errors))
    return {"ok": True, "projectId": projectId, "newProtocolId": protocolId}


def _applyWatch(payload: ActionPayload, mapper, currentUser) -> Dict[str, Any]:
    """Begin or end watching a project for the user; begun with the stream as it is now."""
    from app.backend.api.services.streaming_monitor import watchSnapshot

    watches = AssistantPostgresqlMapper(mapper.db)
    name = streaming_watch.projectName(mapper.db, payload.projectId)
    active = watches.activeWatch(currentUser["id"], payload.projectId)
    try:
        if payload.action == "unwatch":
            streaming_watch.unwatchCard(payload.projectId, name, active)
            watches.endWatch(active["id"], "user")
            answer: Dict[str, Any] = {"ok": True}
        else:
            snapshot = watchSnapshot(mapper, payload.projectId)
            card = streaming_watch.watchCard(payload.projectId, name, snapshot, payload.hours, active)
            protocols = HelpChatPostgresqlMapper(mapper.db).projectProtocols(payload.projectId)
            start = streaming_watch.startingState(snapshot, protocols)
            row = watches.addWatch(currentUser["id"], payload.projectId, card["hours"], start["reference"])
            watches.saveWatch(row["id"], start["reference"], start["state"])
            answer = {"ok": True, "until": str(row.get("until") or "")}
    except ProposalError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    recordAudit(mapper, currentUser, "assistant.actionApplied", "project", payload.projectId, name,
                {"action": payload.action, "hours": payload.hours})
    return answer


def _applySchedule(payload: ActionPayload, service, mapper, currentUser) -> Dict[str, Any]:
    """Schedule the protocol: it starts by itself when the protocols it waits for (and its inputs) finish."""
    protocol = AssistantPostgresqlMapper(mapper.db).protocol(payload.projectId, payload.protocolId)
    try:
        if protocol is None:
            raise ProposalError("The protocol is not in the project any more")
        waitFor = _waitFor(mapper, payload.projectId, payload.protocolIds or [])
        depending = [item["protocolId"] for item in
                     _subworkflow(service, mapper, currentUser, payload.projectId, protocol)[1:]]
        card = assistant_actions.scheduleCard(payload.projectId, protocol, waitFor, depending)
    except (ProposalError, PermissionError) as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    ids = [item["protocolId"] for item in card["waitFor"]]
    params = dict(AssistantPostgresqlMapper(mapper.db).pointerParams(payload.projectId, payload.protocolId),
                  _prerequisites=assistant_actions.prerequisitesWith(
                      (protocol.get("params") or {}).get("_prerequisites"), ids))
    try:
        result = service.launchProtocol(mapper=mapper, projectId=payload.projectId, protocolId=payload.protocolId,
                                        protocolClassName=protocol["className"], params=params,
                                        executeMode="schedule", currentUserId=currentUser["id"],
                                        protocolIdIsScipionId=True) or {}
    except HTTPException as error:
        result = {"errors": _errorTexts(error.detail)}
    errors = [str(error) for error in result.get("errors") or []]
    recordAudit(mapper, currentUser, "assistant.actionApplied", "project", payload.projectId,
                str(payload.protocolId), {"action": "schedule", "waitFor": ids, "errors": errors[:3]})
    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(errors))
    return {"ok": True, "waitFor": ids}


def _removeTag(payload: ActionPayload, service, mapper, currentUser, tag: Optional[Dict[str, Any]], title: str,
               ids: List[str]) -> Dict[str, Any]:
    """Take the tag off the protocols that have it; the tag stays in the project."""
    if tag is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The project has no tag called %s" % title)
    current = _tagsOf(service, mapper, currentUser, payload.projectId, ids)
    untagged = []
    for protocolId in ids:
        if tag["id"] in current[protocolId]:
            service.setProtocolTags(mapper=mapper, projectId=payload.projectId, protocolId=int(protocolId),
                                    tagIds=[item for item in current[protocolId] if item != tag["id"]],
                                    currentUser=currentUser, protocolIdIsScipionId=True)
            untagged.append(protocolId)
    recordAudit(mapper, currentUser, "assistant.actionApplied", "project", payload.projectId, ids[0],
                {"action": "untag", "tag": tag.get("title"), "protocols": untagged})
    return {"ok": True, "tag": tag.get("title"), "untagged": untagged}


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


# Conversations ----------------------------------------------------------------------------------------------------

@router.get("/conversations")
def listConversations(currentUser: dict = Depends(getCurrentUser),
                      mapper: PostgresqlFlatMapper = Depends(getMapperDependency)) -> Dict[str, Any]:
    """The user's conversations, the newest first."""
    rows = AssistantPostgresqlMapper(mapper.db).conversations(int(currentUser["id"]), MAX_CONVERSATIONS)
    return {"conversations": [{
        "id": row["id"], "title": row.get("title") or "", "projectId": row.get("projectId"),
        "mode": row.get("mode") or "",
        "project": str(row.get("projectPath") or "").rstrip("/").split("/")[-1] or None,
        "messages": int(row.get("messages") or 0),
        "createdAt": row["createdAt"].isoformat() if hasattr(row.get("createdAt"), "isoformat") else row.get("createdAt"),
        "updatedAt": row["updatedAt"].isoformat() if hasattr(row.get("updatedAt"), "isoformat") else row.get("updatedAt"),
    } for row in rows]}


@router.get("/conversations/{conversationId}")
def getConversation(conversationId: int, currentUser: dict = Depends(getCurrentUser),
                    mapper: PostgresqlFlatMapper = Depends(getMapperDependency)) -> Dict[str, Any]:
    """One of the user's conversations with its messages (an answer as it was, cards and steps included)."""
    conversations = AssistantPostgresqlMapper(mapper.db)
    conversation = conversations.conversation(int(currentUser["id"]), conversationId)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"id": conversation["id"], "title": conversation.get("title") or "",
            "projectId": conversation.get("projectId"), "mode": conversation.get("mode") or "",
            "messages": [{"role": row["role"], "text": row["text"], "answer": row.get("answer")}
                         for row in conversations.messages(conversationId)]}


@router.delete("/conversations/{conversationId}", status_code=status.HTTP_204_NO_CONTENT)
def deleteConversation(conversationId: int, currentUser: dict = Depends(getCurrentUser),
                       mapper: PostgresqlFlatMapper = Depends(getMapperDependency)):
    if not AssistantPostgresqlMapper(mapper.db).deleteConversation(int(currentUser["id"]), conversationId):
        raise HTTPException(status_code=404, detail="Conversation not found")


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
