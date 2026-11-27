"""A custom operation proposed by the AI assistant: a short Python script on a volume, a mask and/or particles of the
project, for something no installed protocol does. It becomes one protocol of the project (ProtCustomOperation)
with the script kept as its parameter, so it can be checked and run again; it runs in a sandbox where the server
has one. Only users with the protocols.customCode permission can be offered it or apply it."""
from typing import Any, Callable, Dict, List, Optional

from app.backend.api.services.assistant_actions import ProposalError
from app.backend.api.services.custom_code import PERMISSION

CLASS_NAME = "ProtCustomOperation"
FINISHED = "finished"
MAX_SCRIPT = 20000
MAX_OPERATION = 500
MAX_TITLE = 80

# role -> (the protocol's input, the kinds of output it takes)
ROLES: Dict[str, Any] = {
    "volume": ("inputVolume", ("Volume",)),
    "mask": ("inputMask", ("VolumeMask",)),
    "particles": ("inputParticles", ("SetOfParticles",)),
}

CONTRACT = ("The script runs in a folder of its own. inputs.json there has the inputs given: \"volume\" and "
            "\"mask\" ({\"file\": an .mrc path, \"index\", \"samplingRate\"}) and \"particles\" ({\"file\": "
            "particles.csv with columns id, index, file; \"count\", \"samplingRate\"}). It writes its results in "
            "output/: volume.mrc becomes the protocol's output volume (same pixel size as the first input), "
            "result.txt is shown in its summary. Only numpy, scipy and mrcfile can be imported; there is no "
            "network and it can write only in its own folder.")


def _isA(className: str, bases) -> bool:
    """Whether an output of className is one of bases (a subclass counts: a mask is a volume)."""
    if className in bases:
        return True
    try:
        import pwem.objects as objects
        from pwem import Domain

        found = getattr(objects, className, None) or Domain.findClass(className)
        return any(isinstance(found, type) and issubclass(found, getattr(objects, base)) for base in bases)
    except Exception:
        return False


def _input(item: Dict[str, Any], protocolOf: Callable[[str], Optional[Dict[str, Any]]],
           outputsOf: Callable[[str], List[Dict[str, Any]]]) -> Dict[str, Any]:
    role = str(item.get("role") or "").strip().lower()
    if role not in ROLES:
        raise ProposalError("Each input is a volume, a mask or particles, not %r" % role)
    param, bases = ROLES[role]
    protocolId = str(item.get("protocolId") or "").strip().lstrip("#")
    protocol = protocolOf(protocolId) if protocolId else None
    if not protocol:
        raise ProposalError("There is no protocol %s in that project" % (protocolId or "(none given)"))
    if str(protocol.get("status") or "").lower() != FINISHED:
        raise ProposalError("Protocol %s has not finished; its outputs are not ready" % protocolId)
    outputs = [row for row in outputsOf(protocolId) if _isA(str(row.get("setClassName") or ""), bases)]
    names = [str(row["outputName"]) for row in outputs]
    wanted = str(item.get("output") or "").strip()
    if wanted:
        if wanted not in names:
            raise ProposalError("Protocol %s has no %s output called %s%s" % (
                protocolId, role, wanted, (" (it has: %s)" % ", ".join(names)) if names else ""))
    elif len(names) == 1:
        wanted = names[0]
    elif not names:
        raise ProposalError("Protocol %s has no %s output" % (protocolId, role))
    else:
        raise ProposalError("Which output of protocol %s? It has: %s" % (protocolId, ", ".join(names)))
    return {"role": role, "param": param, "protocolId": protocolId,
            "protocolLabel": str(protocol.get("label") or protocol.get("className") or ""), "output": wanted}


def plan(inputs: Any, script: Any, operation: Any, title: Any, canRun: bool,
         protocolOf: Callable[[str], Optional[Dict[str, Any]]],
         outputsOf: Callable[[str], List[Dict[str, Any]]]) -> Dict[str, Any]:
    """The operation checked as the project is now, or ProposalError saying what is wrong."""
    if not canRun:
        raise ProposalError("Custom operations need the %s permission; an administrator gives it" % PERMISSION)
    code = str(script or "")
    if not code.strip():
        raise ProposalError("The script is empty")
    if len(code) > MAX_SCRIPT:
        raise ProposalError("The script is too long (at most %d characters)" % MAX_SCRIPT)
    try:
        compile(code, "operation.py", "exec")
    except SyntaxError as error:
        raise ProposalError("The script has a syntax error in line %s: %s" % (error.lineno, error.msg))
    words = " ".join(str(operation or "").split())
    if not words:
        raise ProposalError("Say in plain words what the operation does")
    if not isinstance(inputs, list) or not inputs:
        raise ProposalError("Give at least one input: a volume, a mask or particles")
    checked = [_input(item if isinstance(item, dict) else {}, protocolOf, outputsOf) for item in inputs]
    roles = [item["role"] for item in checked]
    if len(set(roles)) != len(roles):
        raise ProposalError("One input of each kind at most: one volume, one mask, one set of particles")
    name = " ".join(str(title or "").split())[:MAX_TITLE] or "custom operation"
    return {"title": name, "operation": words[:MAX_OPERATION], "script": code, "inputs": checked}


def card(projectId: int, data: Dict[str, Any], reason: str) -> Dict[str, Any]:
    return {"kind": "action", "action": "custom", "projectId": int(projectId), "protocolId": "", "label": data["title"],
            "title": data["title"], "operation": data["operation"], "script": data["script"],
            "lines": len(data["script"].splitlines()), "inputs": data["inputs"], "reason": reason}


def workflowProtocol(data: Dict[str, Any], newId: int) -> Dict[str, Any]:
    """The operation as a one-protocol workflow, its inputs pointing to the project's outputs."""
    protocol = {"object.className": CLASS_NAME, "object.id": str(newId), "object.label": data["title"],
                "object.comment": data["operation"], "operation": data["operation"], "script": data["script"]}
    for item in data["inputs"]:
        protocol[item["param"]] = "%s.%s" % (item["protocolId"], item["output"])
    return protocol
