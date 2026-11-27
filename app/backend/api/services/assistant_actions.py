"""What the AI assistant may propose (phase 2) and how a proposal is applied once the user confirms it.

A proposal does nothing by itself: it becomes a card in the chat with what would happen, and only the user's
[Apply] runs it, through the same services as the web's own buttons, with the user's permissions checked again.

Relaunch follows the protocol form's rules:
- changed parameters always restart (continuing with other values would mix results);
- without changes, a failed or aborted protocol continues (restart is offered too); a finished one restarts;
- with protocols depending on it, the user chooses "only this one" (they are reset and lose their outputs) or
  "the whole workflow" (they run again); nothing is chosen for them.
Only parameters the user sees in the form can change, never an input (a pointer to another protocol's output).

Duplicate makes a copy with the changes asked, launched only when the user ticks it on the card.

On a protocol and everything depending on it (its subworkflow), the card lists every protocol it touches and the
apply refuses when that list changed since (nothing the user did not see is touched):
- copy the subworkflow (the copies linked among themselves, as the graph's copy does), optionally launched;
- reset it: its results are cleared, nothing may be running;
- delete it (with the delete switch only): nothing may be running, the card lists every result lost and the user
  confirms by writing how many protocols go.

A tag is added by its name to one or more protocols (a tag the project does not have yet is created), or taken
off them (the tag stays in the project).

Delete (only when the administrator allows it besides proposing) is the one that cannot be undone, so: protocols
only (never projects), never a running one, never one whose depending protocols run or have results (as the web's
own delete refuses), the card lists everything that is lost, and the user confirms by writing its number.
"""
from typing import Any, Dict, List, Optional, Tuple

ACTIVE_STATUSES = ("running", "launched", "scheduled")
CONTINUABLE_STATUSES = ("failed", "aborted", "interrupted")
NEVER_RUN_STATUSES = ("new", "saved", "")
MAX_CHANGES = 12
MAX_SUBWORKFLOW = 60
MAX_TAGGED = 50
MAX_TAG_CHARS = 60


class ProposalError(ValueError):
    """Why a proposal cannot be made or applied, in words for the model and the user."""


def _sameType(current: Any, value: Any, label: str) -> Any:
    """The new value in the type of the current one."""
    if isinstance(current, bool):
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "yes", "1", "sí", "si", "on"):
            return True
        if text in ("false", "no", "0", "off"):
            return False
        raise ProposalError("%s takes yes or no, not %r" % (label, value))
    if isinstance(current, int):
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ProposalError("%s takes a whole number, not %r" % (label, value))
        if number != int(number):
            raise ProposalError("%s takes a whole number, not %r" % (label, value))
        return int(number)
    if isinstance(current, float):
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ProposalError("%s takes a number, not %r" % (label, value))
    if isinstance(current, (dict, list)):
        raise ProposalError("%s cannot be changed from the chat; open the protocol's form" % label)
    return str(value)


def parameterChanges(storedParams: Dict[str, Any], help_: Optional[Dict[str, Any]],
                     changes: Dict[str, Any]) -> List[Dict[str, Any]]:
    """[{name, label, from, to}] of the changes asked, checked: only visible, non-input params of the form."""
    if not isinstance(changes, dict):
        raise ProposalError("The changes must be parameter names with their new values")
    if len(changes) > MAX_CHANGES:
        raise ProposalError("Too many changes at once")
    visible = {param["name"]: param for param in (help_ or {}).get("params") or []}
    checked = []
    for name, value in changes.items():
        param = visible.get(name)
        if param is None or name not in storedParams:
            raise ProposalError("The protocol has no parameter called %s in its form (use protocol_details to see "
                                "their names)" % name)
        if param.get("pointer"):
            raise ProposalError("%s is an input; inputs cannot be changed from the chat" % param["label"])
        current = storedParams[name]
        new = _sameType(current, value, param["label"])
        if new != current:
            checked.append({"name": name, "label": param["label"], "from": current, "to": new})
    return checked


def relaunchModes(status: str, changed: bool) -> Tuple[str, List[str]]:
    """(the mode proposed, the modes the user may pick)."""
    status = (status or "").lower()
    if status in ACTIVE_STATUSES:
        raise ProposalError("The protocol is %s; it has to be stopped first" % status)
    if changed or status in NEVER_RUN_STATUSES:
        return "restart", ["restart"]
    if status in CONTINUABLE_STATUSES:
        return "continue", ["continue", "restart"]
    return "restart", ["restart"]


def relaunchCard(projectId: int, protocol: Dict[str, Any], help_: Optional[Dict[str, Any]], changes: Dict[str, Any],
                 preflight: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
    checked = parameterChanges(protocol.get("params") or {}, help_, changes or {})
    if changes and not checked:
        raise ProposalError("Those are already the protocol's values; nothing would change")
    mode, modes = relaunchModes(protocol.get("status"), bool(checked))
    rootId = str(protocol["protocolId"])
    children = [{"protocolId": str(item.get("protocolId")), "label": item.get("runName") or "",
                 "status": item.get("status") or "", "active": bool(item.get("active"))}
                for item in (preflight or {}).get("affectedProtocols") or []
                if str(item.get("protocolId")) != rootId]
    return {"kind": "action", "action": "relaunch", "projectId": int(projectId), "protocolId": rootId,
            "label": protocol.get("label") or "", "className": protocol.get("className") or "",
            "status": protocol.get("status") or "", "mode": mode, "modes": modes, "changes": checked,
            "children": children, "reason": str(reason or "")[:500]}


def stopCard(projectId: int, protocol: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
    status = (protocol.get("status") or "").lower()
    if status not in ACTIVE_STATUSES:
        raise ProposalError("The protocol is %s, not running or waiting: there is nothing to stop" % (status or "new"))
    return {"kind": "action", "action": "stop", "projectId": int(projectId),
            "protocolId": str(protocol["protocolId"]), "label": protocol.get("label") or "",
            "className": protocol.get("className") or "", "status": status, "reason": str(reason or "")[:500]}


def nextStepCard(projectId: int, source: Dict[str, Any], help_: Optional[Dict[str, Any]],
                 reason: str = "") -> Dict[str, Any]:
    if help_ is None:
        raise ProposalError("That protocol is not installed (use search_help to find one that is)")
    return {"kind": "action", "action": "next", "projectId": int(projectId),
            "protocolId": str(source["protocolId"]), "label": source.get("label") or "",
            "nextClassName": help_["className"], "nextLabel": help_.get("label") or help_["className"],
            "reason": str(reason or "")[:500]}


def duplicateCard(projectId: int, protocol: Dict[str, Any], help_: Optional[Dict[str, Any]],
                  changes: Dict[str, Any], reason: str = "", launch: bool = False) -> Dict[str, Any]:
    checked = parameterChanges(protocol.get("params") or {}, help_, changes or {})
    return {"kind": "action", "action": "duplicate", "projectId": int(projectId),
            "protocolId": str(protocol["protocolId"]), "label": protocol.get("label") or "",
            "className": protocol.get("className") or "", "status": protocol.get("status") or "",
            "changes": checked, "launch": bool(launch), "reason": str(reason or "")[:500]}


def _listed(items: List[Dict[str, Any]], withOutputs: bool = False) -> List[Dict[str, Any]]:
    listed = []
    for item in items:
        entry = {"protocolId": str(item["protocolId"]), "label": item.get("label") or "",
                 "status": item.get("status") or ""}
        if withOutputs:
            entry["outputs"] = [{"name": output.get("outputName") or "", "type": output.get("setClassName") or "",
                                 "size": output.get("size")} for output in item.get("outputs") or []]
        listed.append(entry)
    return listed


def _checkedSize(items: List[Dict[str, Any]]) -> None:
    if not items:
        raise ProposalError("The protocol is not in the project any more")
    if len(items) > MAX_SUBWORKFLOW:
        raise ProposalError("That is %d protocols; from the chat at most %d at once (use the project's graph)"
                            % (len(items), MAX_SUBWORKFLOW))


def _nothingRunning(items: List[Dict[str, Any]], doing: str) -> None:
    running = [item for item in items if item.get("active") or (item.get("status") or "").lower() in ACTIVE_STATUSES]
    if running:
        raise ProposalError("%s while protocols in it run (%s): stop them first" % (
            doing, ", ".join("#%s" % item["protocolId"] for item in running)))


def subworkflowCard(action: str, projectId: int, items: List[Dict[str, Any]], reason: str = "",
                    launch: bool = False) -> Dict[str, Any]:
    """A card for a protocol and everything depending on it (items: the root first, each with its outputs for a
    reset or a delete)."""
    _checkedSize(items)
    root = items[0]
    card = {"kind": "action", "action": action, "projectId": int(projectId), "protocolId": str(root["protocolId"]),
            "label": root.get("label") or "", "className": root.get("className") or "",
            "status": root.get("status") or "", "reason": str(reason or "")[:500]}
    if action == "copyworkflow":
        card.update(protocols=_listed(items), launch=bool(launch))
    elif action == "reset":
        _nothingRunning(items, "It cannot be reset")
        if not any(item.get("outputs") for item in items) and all(
                (item.get("status") or "").lower() in NEVER_RUN_STATUSES for item in items):
            raise ProposalError("Nothing there has run yet: there is nothing to reset")
        card.update(protocols=_listed(items, True))
    elif action == "deletefrom":
        _nothingRunning(items, "It cannot be deleted")
        card.update(protocols=_listed(items, True))
    else:
        raise ProposalError("Unknown action: %s" % action)
    return card


def sameProtocols(expected: Optional[List[str]], items: List[Dict[str, Any]]) -> None:
    """The protocols the user saw on the card are still the ones it would touch."""
    now = sorted(str(item["protocolId"]) for item in items)
    if sorted(str(item) for item in expected or []) != now:
        raise ProposalError("The protocols depending on it changed since the card was made; ask again")


def deleteFromChecks(items: List[Dict[str, Any]], expected: Optional[List[str]], confirm: Optional[str]) -> None:
    _checkedSize(items)
    sameProtocols(expected, items)
    _nothingRunning(items, "It cannot be deleted")
    if str(confirm or "").strip() != str(len(items)):
        raise ProposalError("Write how many protocols are deleted (%d) to confirm" % len(items))


def tagTitle(title: Any) -> str:
    text = " ".join(str(title or "").split())
    if not text:
        raise ProposalError("Say the tag's name")
    if len(text) > MAX_TAG_CHARS:
        raise ProposalError("A tag's name has at most %d characters" % MAX_TAG_CHARS)
    return text


def tagCard(projectId: int, protocols: List[Dict[str, Any]], title: str, existing: Optional[Dict[str, Any]],
            tagged: Dict[str, List[str]], reason: str = "", remove: bool = False) -> Dict[str, Any]:
    """protocols: the ones to tag (or untag, with remove); existing: the project's tag with that name, if any;
    tagged: each protocol's tag ids now. "already": the protocol has the tag now."""
    if not protocols:
        raise ProposalError("Say which protocols")
    if len(protocols) > MAX_TAGGED:
        raise ProposalError("At most %d protocols at once" % MAX_TAGGED)
    title = tagTitle(title)
    already = [str(item["protocolId"]) for item in protocols
               if existing and existing["id"] in tagged.get(str(item["protocolId"]), [])]
    if remove:
        if existing is None:
            raise ProposalError("The project has no tag called %s" % title)
        if not already:
            raise ProposalError("None of those protocols has the tag %s" % existing["title"])
    elif len(already) == len(protocols):
        raise ProposalError("Those protocols already have the tag %s" % title)
    return {"kind": "action", "action": "untag" if remove else "tag", "projectId": int(projectId),
            "protocolId": str(protocols[0]["protocolId"]), "label": protocols[0].get("label") or "",
            "tag": existing["title"] if existing else title, "newTag": existing is None,
            "color": (existing or {}).get("color"),
            "protocols": [dict(entry, already=entry["protocolId"] in already) for entry in _listed(protocols)],
            "reason": str(reason or "")[:500]}


def blockingChildren(children: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The depending protocols that stop a delete: running ones and ones with results."""
    return [child for child in children if child.get("active") or child.get("hasOutputs")]


def deleteCard(projectId: int, protocol: Dict[str, Any], outputs: List[Dict[str, Any]],
               children: List[Dict[str, Any]], reason: str = "") -> Dict[str, Any]:
    status = (protocol.get("status") or "").lower()
    if status in ACTIVE_STATUSES:
        raise ProposalError("The protocol is %s; it cannot be deleted while it runs" % status)
    blocking = blockingChildren(children)
    if blocking:
        raise ProposalError("Protocols depending on it are running or have results (%s); they would have to be "
                            "deleted first, from the project's graph" % ", ".join("#%s" % child["protocolId"]
                                                                                  for child in blocking))
    return {"kind": "action", "action": "delete", "projectId": int(projectId),
            "protocolId": str(protocol["protocolId"]), "label": protocol.get("label") or "",
            "className": protocol.get("className") or "", "status": status,
            "outputs": [{"name": item.get("outputName") or "", "type": item.get("setClassName") or "",
                         "size": item.get("size")} for item in outputs or []],
            "children": [{"protocolId": str(child["protocolId"]), "label": child.get("label") or "",
                          "status": child.get("status") or ""} for child in children],
            "reason": str(reason or "")[:500]}


def applyChecks(protocol: Optional[Dict[str, Any]], help_: Optional[Dict[str, Any]], action: str, mode: str,
                scope: Optional[str], changes: Dict[str, Any], hasChildren: bool,
                confirm: Optional[str] = None, children: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Check again, as things are now, what the user confirmed; the params to send for a relaunch or a copy."""
    if protocol is None:
        raise ProposalError("The protocol is not in the project any more")
    if action == "stop":
        stopCard(0, protocol)
        return {}
    if action == "duplicate":
        checked = parameterChanges(protocol.get("params") or {}, help_, changes or {})
        return {"params": {item["name"]: item["to"] for item in checked}}
    if action == "delete":
        if str(confirm or "").strip().lstrip("#") != str(protocol["protocolId"]):
            raise ProposalError("Write the protocol's number (%s) to confirm the delete" % protocol["protocolId"])
        deleteCard(0, protocol, [], children or [])
        return {}
    if action != "relaunch":
        raise ProposalError("Unknown action: %s" % action)
    checked = parameterChanges(protocol.get("params") or {}, help_, changes or {})
    _, modes = relaunchModes(protocol.get("status"), bool(checked))
    if mode not in modes:
        raise ProposalError("The protocol cannot %s now (it is %s)" % (mode, protocol.get("status") or "new"))
    if scope not in ("single", "all"):
        if hasChildren:
            raise ProposalError("Choose whether to relaunch only this protocol or its whole workflow")
        scope = "single"
    return {"params": {item["name"]: item["to"] for item in checked}, "mode": mode, "scope": scope}
