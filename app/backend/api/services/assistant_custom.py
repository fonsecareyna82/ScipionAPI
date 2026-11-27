"""A custom operation proposed by the AI assistant: a short Python script on any outputs of the project, for
something no installed protocol does. It becomes one protocol of the project (ProtCustomOperation) with the script
kept as its parameter, so it can be checked and run again; it runs in a sandbox where the server lets one start.
Only users with the protocols.customCode permission can be offered it or apply it."""
from typing import Any, Callable, Dict, List, Optional

from app.backend.api.services.assistant_actions import ProposalError
from app.backend.api.services.custom_code import PERMISSION

CLASS_NAME = "ProtCustomOperation"
FINISHED = "finished"
MAX_SCRIPT = 20000
MAX_OPERATION = 500
MAX_TITLE = 80
MAX_INPUTS = 10

CONTRACT = ("The script runs in a folder of its own, with the variable inputs (also in inputs.json there): a list "
            "in the order given, one entry per input with \"protocolId\", \"output\" and \"type\" (its class, "
            "e.g. Volume, SetOfCTFs). A set has \"count\", \"samplingRate\" if any, and \"file\": a CSV, one row "
            "per item, with the column id and the item's values by their names (as protocol_details or the "
            "metadata schema show them, e.g. _defocusU, _ctfModel._defocusU, _index, _filename; files are whole "
            "paths), listed in \"columns\". Anything else has its values by their names, \"file\" and \"index\" "
            "if it has a file, and \"samplingRate\" if any. It writes its results in output/: volume.mrc becomes "
            "the protocol's output volume (pixel size of the first input that has one); any other .mrc there "
            "becomes its output set of volumes (several maps, in the order of their names); result.txt is shown in "
            "its summary. Only numpy, scipy and mrcfile can be imported; there is no network and it can write only in "
            "its own folder.")


def _input(item: Dict[str, Any], protocolOf: Callable[[str], Optional[Dict[str, Any]]],
           outputsOf: Callable[[str], List[Dict[str, Any]]]) -> Dict[str, Any]:
    protocolId = str(item.get("protocolId") or "").strip().lstrip("#")
    protocol = protocolOf(protocolId) if protocolId else None
    if not protocol:
        raise ProposalError("There is no protocol %s in that project" % (protocolId or "(none given)"))
    if str(protocol.get("status") or "").lower() != FINISHED:
        raise ProposalError("Protocol %s has not finished; its outputs are not ready" % protocolId)
    outputs = {str(row["outputName"]): row for row in outputsOf(protocolId)}
    wanted = str(item.get("output") or "").strip()
    if wanted:
        if wanted not in outputs:
            raise ProposalError("Protocol %s has no output called %s%s" % (
                protocolId, wanted, (" (it has: %s)" % ", ".join(outputs)) if outputs else ""))
    elif len(outputs) == 1:
        wanted = next(iter(outputs))
    elif not outputs:
        raise ProposalError("Protocol %s has no outputs" % protocolId)
    else:
        raise ProposalError("Which output of protocol %s? It has: %s" % (protocolId, ", ".join(outputs)))
    row = outputs[wanted]
    return {"protocolId": protocolId, "protocolLabel": str(protocol.get("label") or protocol.get("className") or ""),
            "output": wanted, "type": str(row.get("setClassName") or ""),
            "size": int(row["size"]) if row.get("size") is not None else None}


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
        raise ProposalError("Give at least one input: an output of the project")
    if len(inputs) > MAX_INPUTS:
        raise ProposalError("At most %d inputs" % MAX_INPUTS)
    checked = [_input(item if isinstance(item, dict) else {}, protocolOf, outputsOf) for item in inputs]
    refs = ["%s.%s" % (item["protocolId"], item["output"]) for item in checked]
    if len(set(refs)) != len(refs):
        raise ProposalError("The same output is given twice")
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
    protocol["inputs"] = ["%s.%s" % (item["protocolId"], item["output"]) for item in data["inputs"]]
    return protocol
