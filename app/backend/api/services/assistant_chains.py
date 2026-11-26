"""Adding a facility template to a project for the AI assistant, whole or cut to start from an output the project
has, and running the protocols it adds stretch by stretch (see assistant_templates.py for the rules).

Everything goes through the web's own services: the template is materialized as the facility's sessions do it,
imported as the in-project paste does it (so Scipion links the inputs to the project's protocols), and each
protocol is scheduled (it waits for its inputs) as the protocol form schedules one.
"""
import logging
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from app.backend.api.services import assistant_templates as templates
from app.backend.api.services.assistant_actions import ProposalError
from app.backend.mapper.assistant_mapper import AssistantPostgresqlMapper
from app.backend.mapper.help_chat_mapper import HelpChatPostgresqlMapper

logger = logging.getLogger(__name__)

# The chain's protocols get ids above every id of the project, by this much
ID_MARGIN = 100000


def _outputNames(rows: List[Dict[str, Any]]) -> List[str]:
    return [str(row.get("outputName") or "") for row in rows if row.get("outputName")]


class TemplateChains:
    def __init__(self, service, mapper, currentUser: Dict[str, Any]):
        self.service = service
        self.mapper = mapper
        self.currentUser = currentUser
        self.db = AssistantPostgresqlMapper(mapper.db)
        self.help = HelpChatPostgresqlMapper(mapper.db)
        self._templates: Optional[List[Dict[str, Any]]] = None
        self._outputs: Dict[str, List[str]] = {}

    # Templates -----------------------------------------------------------------------------------------------
    def allTemplates(self) -> List[Dict[str, Any]]:
        if self._templates is None:
            self._templates = [item for item in self.service.listProjectWorkflows() or [] if isinstance(item, dict)]
        return self._templates

    def find(self, query: str = "", projectId: Optional[int] = None, fromProtocolId: Optional[str] = None,
             fromOutput: Optional[str] = None) -> List[Dict[str, Any]]:
        """The templates matching the words; given a protocol's output, what each would add from it."""
        found = [item for item in self.allTemplates() if templates.matches(item, query)]
        source = None
        if projectId is not None and fromProtocolId:
            source = self.db.protocol(projectId, fromProtocolId)
            if not source:
                raise ProposalError("There is no protocol %s in the project" % fromProtocolId)
            outputs = self.outputsOf(projectId, fromProtocolId)
            if not fromOutput and len(outputs) == 1:
                fromOutput = outputs[0]
            if fromOutput not in outputs:
                raise ProposalError("Say which output of protocol %s: %s" % (fromProtocolId, ", ".join(outputs)))
        answer = []
        for item in found:
            summary = templates.summary(item)
            if source is not None:
                summary.pop("steps", None)
                summary["fromHere"] = self._fromHere(item, fromOutput, source.get("className"))
            answer.append(summary)
        if source is not None:
            # The ones that take it first, the ones adding most first among them
            answer.sort(key=lambda summary: -(summary["fromHere"] or {}).get("adds", -1))
        return answer

    @staticmethod
    def _fromHere(template: Dict[str, Any], output: str, className: Optional[str]) -> Optional[Dict[str, Any]]:
        content = template.get("content") or []
        candidates = templates.anchorCandidates(content, output, className)
        if not candidates:
            return None
        kept, _ = templates.cut(content, candidates[0])
        keySteps = []
        for protocol in kept:
            step = templates.keyStepOf(protocol.get("object.className"))
            if step and step not in keySteps:
                keySteps.append(step)
        return {"anchor": candidates[0], "adds": len(kept), "keySteps": keySteps,
                "protocols": [protocol.get("object.className") for protocol in kept][:30]}

    def template(self, templateId: str) -> Dict[str, Any]:
        found = next((item for item in self.allTemplates() if str(item.get("id")) == str(templateId)), None)
        if found is None:
            raise ProposalError("There is no template %s (list_templates gives their ids)" % templateId)
        if found.get("canLoad") is False:
            missing = ", ".join(found.get("missingPluginNames") or []) or "some plugins"
            raise ProposalError("The template needs %s, which are not installed" % missing)
        return found

    # Planning ------------------------------------------------------------------------------------------------
    def outputsOf(self, projectId: int, protocolId: str) -> List[str]:
        key = "%s/%s" % (projectId, protocolId)
        if key not in self._outputs:
            self._outputs[key] = _outputNames(self.help.protocolOutputs(projectId, protocolId))
        return self._outputs[key]

    def plan(self, projectId: int, templateId: str, fromProtocolId: Optional[str] = None,
             fromOutput: Optional[str] = None, anchor: Optional[str] = None,
             overrides: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        template = self.template(templateId)
        content = template.get("content") or []
        allSteps = templates.steps(content)
        classes = {step["id"]: step["className"] for step in allSteps}
        if not fromProtocolId:
            kept = templates.protocolsOf(content)
            return {"template": template, "kept": kept, "anchor": None, "alternatives": [], "links": [],
                    "source": None}
        source = self.db.protocol(projectId, fromProtocolId)
        if not source:
            raise ProposalError("There is no protocol %s in the project" % fromProtocolId)
        outputs = self.outputsOf(projectId, fromProtocolId)
        if not fromOutput:
            if len(outputs) != 1:
                raise ProposalError("Say which output of protocol %s to start from: %s"
                                    % (fromProtocolId, ", ".join(outputs) or "it has none"))
            fromOutput = outputs[0]
        if fromOutput not in outputs:
            raise ProposalError("Protocol %s has no output %s (it has %s)"
                                % (fromProtocolId, fromOutput, ", ".join(outputs) or "none"))
        alternatives = templates.anchorCandidates(content, fromOutput, source.get("className"))
        if anchor is None:
            if not alternatives:
                raise ProposalError("Nothing in the template takes %s; choose another template or say which of its "
                                    "outputs stands for it (anchor)" % fromOutput)
            anchor = alternatives[0]
        kept, external = templates.cut(content, anchor)
        links = templates.suggestLinks(
            external, classes, anchor, {"protocolId": str(fromProtocolId), "output": fromOutput},
            self.db.ancestors(projectId, fromProtocolId), self.help.projectProtocols(projectId),
            lambda protocolId: self.outputsOf(projectId, protocolId), overrides)
        return {"template": template, "kept": kept, "anchor": anchor, "alternatives": alternatives, "links": links,
                "source": {"protocolId": str(fromProtocolId), "label": source.get("label") or "",
                           "output": fromOutput}}

    def card(self, projectId: int, plan: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
        template = plan["template"]
        stops = set(templates.defaultStops(plan["kept"]))
        steps = [{"id": step["id"], "className": step["className"], "label": step["label"],
                  "keyStep": step["keyStep"], "stop": step["id"] in stops}
                 for step in templates.steps(plan["kept"])][:templates.MAX_STEPS]
        labels = {str(row["protocolId"]): row.get("label") or "" for row in self.help.projectProtocols(projectId)}
        links = [dict(link, projectLabel=labels.get(str(link["projectRef"] or "").split(".")[0], ""))
                 for link in plan["links"]]
        fields = templates.summary(template)["fields"] if not plan["source"] else []
        few = len(plan["kept"]) <= 2
        return {"kind": "action", "action": "template", "projectId": int(projectId), "few": few,
                "protocolId": plan["source"]["protocolId"] if plan["source"] else "",
                "label": plan["source"]["label"] if plan["source"] else "",
                "templateId": str(template.get("id")), "templateName": str(template.get("name") or ""),
                "source": plan["source"], "anchor": plan["anchor"], "alternatives": plan["alternatives"],
                "links": links, "missing": [link["templateRef"] for link in links if not link["projectRef"]],
                "steps": steps, "fields": fields, "reason": str(reason or "")[:500]}

    # Applying --------------------------------------------------------------------------------------------------
    def _checkLink(self, projectId: int, projectRef: str) -> None:
        protocolId, _, output = str(projectRef or "").partition(".")
        row = self.db.protocol(projectId, protocolId) if protocolId else None
        if not row or output.split(".")[0] not in self.outputsOf(projectId, protocolId):
            raise ProposalError("The project has no %s" % projectRef)
        if str(row.get("status") or "").lower() != templates.FINISHED:
            raise ProposalError("Protocol %s has not finished; its %s is not ready" % (protocolId, output))

    def apply(self, projectId: int, templateId: str, fromProtocolId: Optional[str], fromOutput: Optional[str],
              anchor: Optional[str], links: Dict[str, str], stops: List[str],
              fields: Dict[str, Any]) -> Dict[str, Any]:
        plan = self.plan(projectId, templateId, fromProtocolId, fromOutput, anchor, links)
        missing = [link["templateRef"] for link in plan["links"] if not link["projectRef"]]
        if missing:
            raise ProposalError("Say what in the project stands for %s" % ", ".join(missing))
        for link in plan["links"]:
            self._checkLink(projectId, link["projectRef"])
        content = self.service.materializeWorkflowTemplate(str(templateId), fields or {})
        everything = templates.protocolsOf(content)
        kept = templates.cut(content, plan["anchor"])[0] if plan["anchor"] else everything
        keptIds = [str(protocol["object.id"]) for protocol in kept]
        linkMap = {link["templateRef"]: link["projectRef"] for link in plan["links"]}
        firstId = self.db.topProtocolId(projectId) + ID_MARGIN
        newContent, idMap = templates.renumbered(kept, linkMap, firstId,
                                                 {str(protocol["object.id"]) for protocol in everything})
        if not self.service.loadPostgresqlRuntimeProjectForMutation(mapper=self.mapper, projectId=projectId,
                                                                    currentUser=self.currentUser):
            raise ProposalError("The project is not there any more")
        result = self.service.importWorkflowProtocolsService(
            self.mapper, projectId, self.currentUser,
            SimpleNamespace(mode="append", workflow=newContent, sourceProjectId=str(projectId))) or {}
        if result.get("errors"):
            raise ProposalError("The template could not be added: %s" % "; ".join(str(e) for e in result["errors"]))
        created = {str(item["sourceId"]): str(item["newId"]) for item in result.get("created") or []}
        order = [created[idMap[pid]] for pid in keptIds if idMap.get(pid) in created]
        parents = {created[child]: [created[parent] for parent in parentIds if parent in created]
                   for child, parentIds in templates.parentsOf(newContent).items() if child in created}
        stopIds = [created[idMap[pid]] for pid in stops or [] if idMap.get(pid) in created]
        template = plan["template"]
        title = str(template.get("name") or templateId)
        if plan["source"]:
            title += " from #%s" % plan["source"]["protocolId"]
        chainId = self.db.addChain(projectId, self.currentUser.get("id"), str(templateId), title, order, parents,
                                   stopIds, [])
        launch = self.launchNext(projectId, chainId)
        return dict(launch, chainId=chainId, created=order)

    def launchNext(self, projectId: int, chainId: int, passedStop: Optional[str] = None) -> Dict[str, Any]:
        """Schedule the chain's protocols whose stops before them were all passed (passing passedStop first)."""
        chain = self.db.chain(projectId, chainId)
        if chain is None:
            raise ProposalError("There is no chain %s in the project" % chainId)
        passed = list(chain.get("passed") or [])
        stops = list(chain.get("stops") or [])
        if passedStop is not None:
            if str(passedStop) not in stops:
                raise ProposalError("Protocol %s is not a stop of that chain" % passedStop)
            row = self.db.protocol(projectId, passedStop)
            if not row or str(row.get("status") or "").lower() != templates.FINISHED:
                raise ProposalError("Protocol %s has not finished yet" % passedStop)
            if str(passedStop) not in passed:
                passed.append(str(passedStop))
        launched = list(chain.get("launched") or [])
        toLaunch = templates.launchable(chain.get("protocolIds") or [], chain.get("parents") or {}, stops, passed,
                                        launched)
        if toLaunch and not self.service.loadPostgresqlRuntimeProjectForMutation(
                mapper=self.mapper, projectId=projectId, currentUser=self.currentUser):
            raise ProposalError("The project is not there any more")
        errors = []
        for protocolId in toLaunch:
            row = self.db.protocol(projectId, protocolId) or {}
            try:
                # With its inputs, as the protocol form launches one: without them the save empties them
                self.service.launchProtocol(mapper=self.mapper, projectId=projectId, protocolId=protocolId,
                                            protocolClassName=row.get("className"),
                                            params=self.db.pointerParams(projectId, protocolId),
                                            executeMode="schedule", currentUserId=self.currentUser.get("id"),
                                            protocolIdIsScipionId=True)
                launched.append(protocolId)
            except Exception as error:
                detail = getattr(error, "detail", None) or str(error)
                logger.warning("The chain %s could not schedule protocol %s: %s", chainId, protocolId, detail)
                errors.append("#%s: %s" % (protocolId, detail))
        self.db.saveChainProgress(projectId, chainId, passed, launched)
        return {"launched": [pid for pid in toLaunch if pid in launched], "errors": errors}

    # Reading -------------------------------------------------------------------------------------------------
    def chainsOf(self, projectId: int) -> List[Dict[str, Any]]:
        statuses = {str(row["protocolId"]): row for row in self.help.projectProtocols(projectId)}
        answer = []
        for chain in self.db.chains(projectId):
            stops = [{"protocolId": pid, "label": statuses.get(pid, {}).get("label", ""),
                      "status": statuses.get(pid, {}).get("status", "deleted"),
                      "passed": pid in (chain.get("passed") or [])} for pid in chain.get("stops") or []]
            waiting = templates.launchable(chain.get("protocolIds") or [], chain.get("parents") or {},
                                           chain.get("stops") or [], chain.get("passed") or [],
                                           chain.get("launched") or [])
            notLaunched = [pid for pid in chain.get("protocolIds") or [] if pid not in (chain.get("launched") or [])]
            answer.append({"chainId": chain["id"], "title": chain.get("title"), "templateId": chain.get("templateId"),
                           "protocols": len(chain.get("protocolIds") or []), "stops": stops,
                           "notLaunched": len(notLaunched), "readyToLaunch": waiting})
        return answer

    def continueCard(self, projectId: int, chainId: int, stopProtocolId: str, reason: str = "") -> Dict[str, Any]:
        chain = self.db.chain(projectId, chainId)
        if chain is None:
            raise ProposalError("There is no chain %s in the project" % chainId)
        stops = chain.get("stops") or []
        if str(stopProtocolId) not in stops:
            raise ProposalError("Protocol %s is not a stop of chain %s (its stops: %s)"
                                % (stopProtocolId, chainId, ", ".join(stops)))
        row = self.db.protocol(projectId, stopProtocolId) or {}
        if str(row.get("status") or "").lower() != templates.FINISHED:
            raise ProposalError("Protocol %s is %s: the chain goes on once it has finished"
                                % (stopProtocolId, row.get("status") or "not there"))
        passed = list(chain.get("passed") or []) + [str(stopProtocolId)]
        nextIds = templates.launchable(chain.get("protocolIds") or [], chain.get("parents") or {}, stops, passed,
                                       chain.get("launched") or [])
        if not nextIds:
            raise ProposalError("Nothing is waiting for that stop")
        labels = {str(item["protocolId"]): item for item in self.help.projectProtocols(projectId)}
        nextStops = [pid for pid in nextIds if pid in stops]
        return {"kind": "action", "action": "continue", "projectId": int(projectId), "chainId": int(chainId),
                "protocolId": str(stopProtocolId), "label": row.get("label") or "", "title": chain.get("title"),
                "next": [{"protocolId": pid, "label": labels.get(pid, {}).get("label", ""),
                          "className": labels.get(pid, {}).get("className", ""), "stop": pid in nextStops}
                         for pid in nextIds],
                "reason": str(reason or "")[:500]}
