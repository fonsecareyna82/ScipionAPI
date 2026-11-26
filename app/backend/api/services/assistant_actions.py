"""What the AI assistant may propose (phase 2) and how a proposal is applied once the user confirms it.

A proposal does nothing by itself: it becomes a card in the chat with what would happen, and only the user's
[Apply] runs it, through the same services as the web's own buttons, with the user's permissions checked again.

Relaunch follows the protocol form's rules:
- changed parameters always restart (continuing with other values would mix results);
- without changes, a failed or aborted protocol continues (restart is offered too); a finished one restarts;
- with protocols depending on it, the user chooses "only this one" (they are reset and lose their outputs) or
  "the whole workflow" (they run again); nothing is chosen for them.
Only parameters the user sees in the form can change, never an input (a pointer to another protocol's output).

Duplicate makes a copy that is not launched, with the changes asked (the user launches it).

Delete (only when the administrator allows it besides proposing) is the one that cannot be undone, so: protocols
only (never projects), never a running one, never one whose depending protocols run or have results (as the web's
own delete refuses), the card lists everything that is lost, and the user confirms by writing its number.
"""
from typing import Any, Dict, List, Optional, Tuple

ACTIVE_STATUSES = ("running", "launched", "scheduled")
CONTINUABLE_STATUSES = ("failed", "aborted", "interrupted")
NEVER_RUN_STATUSES = ("new", "saved", "")
MAX_CHANGES = 12


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
                  changes: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
    checked = parameterChanges(protocol.get("params") or {}, help_, changes or {})
    return {"kind": "action", "action": "duplicate", "projectId": int(projectId),
            "protocolId": str(protocol["protocolId"]), "label": protocol.get("label") or "",
            "className": protocol.get("className") or "", "status": protocol.get("status") or "",
            "changes": checked, "reason": str(reason or "")[:500]}


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
