"""The facility's processing templates for the AI assistant: describing them, cutting one to start from what a
project already has, and running the protocols it adds stretch by stretch, stopping at the key steps.

A template is Scipion's workflow JSON: a list of protocols, each with "object.id", "object.className" and its
params, where an input is written "<object.id>.<output>" (or a list of them). Cutting keeps the protocols that
depend on one output of the template (the anchor) and links every input they take from the protocols left out to
an output of the project ("<protocol id>.<output>"): Scipion's import links an id it does not find in the workflow
to the project's protocol with that id. The kept protocols get new ids above every id of the project, so none can
be taken for one of its protocols.

Stops: a stop is a protocol after which the chain waits for the user. The protocols the assistant launches are
those whose stops before them (inside the chain) were all passed; continuing after a stop passes it.
"""
import re
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from app.backend.api.services.assistant_actions import ProposalError

_REF = re.compile(r"^(\d+)\.([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)$")
MAX_STEPS = 80

# The key steps of single particle processing, by the words of their class names: where to stop by default
KEY_STEPS = (
    ("2D classes", re.compile(r"(Classify2D|Cryo2D|2DClassification|ClassifyPca|CL2D|Prot2D$|ProtCryoSparc2D)", re.I)),
    ("class selection", re.compile(r"(SelectClasses|Assess|GoodClasses|ClassesSelector|AutoClassSelection)", re.I)),
    ("initial model", re.compile(r"InitialModel", re.I)),
    ("3D classes", re.compile(r"(3DClassification|Classify3D|Heterogeneous|3DClass)", re.I)),
)


def _id(protocol: Dict[str, Any]) -> str:
    return str(protocol.get("object.id"))


def _label(protocol: Dict[str, Any]) -> str:
    return str(protocol.get("object.label") or protocol.get("runName") or protocol.get("object.className") or "")


def refsOf(protocol: Dict[str, Any], ids: Set[str]) -> List[Tuple[str, Optional[int], str, str]]:
    """(param, index in a list or None, protocol id, output) of every input of a protocol to one of ids."""
    found = []
    for name, value in protocol.items():
        if name.startswith("object.") or name.startswith("_"):
            continue
        values = [(None, value)] if isinstance(value, str) else \
            list(enumerate(value)) if isinstance(value, list) else []
        for index, item in values:
            match = _REF.match(item.strip()) if isinstance(item, str) else None
            if match and match.group(1) in ids:
                found.append((name, index, match.group(1), match.group(2)))
    return found


def protocolsOf(content: Any) -> List[Dict[str, Any]]:
    if isinstance(content, dict):
        for key in ("workflow", "content", "protocols"):
            if isinstance(content.get(key), list):
                content = content[key]
                break
    return [item for item in content or [] if isinstance(item, dict) and item.get("object.className")]


def keyStepOf(className: str) -> Optional[str]:
    for name, pattern in KEY_STEPS:
        if pattern.search(className or ""):
            return name
    return None


def steps(content: Any) -> List[Dict[str, Any]]:
    """The protocols of a template, in its order: id, class, label, inputs ("id.output") and the key step it is."""
    protocols = protocolsOf(content)
    ids = {_id(protocol) for protocol in protocols}
    return [{"id": _id(protocol), "className": protocol["object.className"], "label": _label(protocol),
             "inputs": sorted({"%s.%s" % (ref[2], ref[3]) for ref in refsOf(protocol, ids)}),
             "keyStep": keyStepOf(protocol["object.className"])} for protocol in protocols]


def summary(template: Dict[str, Any]) -> Dict[str, Any]:
    """What the assistant reads of a template to choose one."""
    allSteps = steps(template.get("content") or [])
    starts = [step["className"] for step in allSteps if not step["inputs"]]
    fields = []
    params = template.get("params") or {}
    for key, param in (params.items() if isinstance(params, dict) else []):
        param = param if isinstance(param, dict) else {}
        fields.append({"alias": str(param.get("alias") or key), "title": str(param.get("title") or key),
                       "value": param.get("value")})
    return {"id": template.get("id"), "name": template.get("name"), "source": template.get("source"),
            "description": str(template.get("description") or "")[:400], "canLoad": template.get("canLoad", True),
            "missingPlugins": template.get("missingPluginNames") or [], "startsWith": starts,
            "fields": fields, "steps": [{key: step[key] for key in ("id", "className", "label", "inputs", "keyStep")}
                                        for step in allSteps[:MAX_STEPS]]}


def matches(template: Dict[str, Any], query: str) -> bool:
    words = [word for word in re.split(r"\W+", (query or "").lower()) if word]
    if not words:
        return True
    text = " ".join([str(template.get("name") or ""), str(template.get("description") or "")]
                    + [step["className"] + " " + step["label"] for step in steps(template.get("content") or [])])
    text = text.lower()
    return all(word in text for word in words)


# Cutting -------------------------------------------------------------------------------------------------------

def anchorCandidates(content: Any, outputName: str, className: Optional[str] = None) -> List[str]:
    """The template's outputs ("id.output") an output of the project could stand for: the same output name, from
    the same class first."""
    allSteps = steps(content)
    classes = {step["id"]: step["className"] for step in allSteps}
    used = OrderedDict()
    for step in allSteps:
        for ref in step["inputs"]:
            protocolId, output = ref.split(".", 1)
            if output.split(".")[0] == outputName:
                used[ref] = classes.get(protocolId)
    same = [ref for ref, refClass in used.items() if className and refClass == className]
    return same or list(used)


def cut(content: Any, anchor: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """(the protocols that depend on the anchor output, in the template's order; the inputs they take from the
    protocols left out, "id.output", the anchor first)."""
    protocols = protocolsOf(content)
    ids = {_id(protocol) for protocol in protocols}
    match = _REF.match(anchor or "")
    if not match or match.group(1) not in ids:
        raise ProposalError("The template has no output %s" % anchor)
    anchorId, anchorOutput = match.group(1), match.group(2)
    kept: Set[str] = set()
    changed = True
    while changed:
        changed = False
        for protocol in protocols:
            pid = _id(protocol)
            if pid in kept or pid == anchorId:
                continue
            for _, _, refId, output in refsOf(protocol, ids):
                if (refId == anchorId and output.split(".")[0] == anchorOutput.split(".")[0]) or refId in kept:
                    kept.add(pid)
                    changed = True
                    break
    if not kept:
        raise ProposalError("Nothing in the template uses %s" % anchor)
    keptProtocols = [protocol for protocol in protocols if _id(protocol) in kept]
    external = OrderedDict([(anchor, True)])
    for protocol in keptProtocols:
        for _, _, refId, output in refsOf(protocol, ids):
            if refId not in kept:
                external["%s.%s" % (refId, output)] = True
    return keptProtocols, list(external)


def renumbered(protocols: List[Dict[str, Any]], links: Dict[str, str], firstId: int,
               allIds: Optional[Set[str]] = None) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """The protocols with new ids from firstId and their inputs pointing to them, or to the project through links
    ("template id.output" -> "project protocol id.output"); (the protocols, old id -> new id)."""
    kept = {_id(protocol) for protocol in protocols}
    allIds = set(allIds or kept) | kept
    newIds = {pid: str(firstId + index) for index, pid in enumerate(_id(protocol) for protocol in protocols)}
    missing = []
    result = []
    for protocol in protocols:
        copy = dict(protocol)
        copy["object.id"] = newIds[_id(protocol)]
        for name, index, refId, output in refsOf(protocol, allIds):
            ref = "%s.%s" % (refId, output)
            if refId in kept:
                target = "%s.%s" % (newIds[refId], output)
            elif ref in links:
                target = links[ref]
            elif "%s.%s" % (refId, output.split(".")[0]) in links:
                # A volume of a set ("id.outputVolumes.2") follows the set's link
                base = links["%s.%s" % (refId, output.split(".")[0])]
                target = base + output[len(output.split(".")[0]):]
            else:
                missing.append(ref)
                continue
            if index is None:
                copy[name] = target
            else:
                values = list(copy[name])
                values[index] = target
                copy[name] = values
        # The template's "wait for" protocols are not kept with it
        copy.pop("_prerequisites", None)
        result.append(copy)
    if missing:
        raise ProposalError("Nothing in the project stands for %s" % ", ".join(sorted(set(missing))))
    return result, newIds


def parentsOf(protocols: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Each protocol's parents inside the list."""
    ids = {_id(protocol) for protocol in protocols}
    return {_id(protocol): sorted({ref[2] for ref in refsOf(protocol, ids)}) for protocol in protocols}


def defaultStops(protocols: List[Dict[str, Any]]) -> List[str]:
    """The first protocol of each key step (2D classes, selection, initial model, 3D classes) in the chain."""
    stops, seen = [], set()
    for protocol in protocols:
        step = keyStepOf(protocol.get("object.className"))
        if step and step not in seen:
            seen.add(step)
            stops.append(_id(protocol))
    return stops


def _ancestors(protocolId: str, parents: Dict[str, List[str]]) -> Set[str]:
    found: Set[str] = set()
    pending = list(parents.get(protocolId) or [])
    while pending:
        parent = pending.pop()
        if parent not in found:
            found.add(parent)
            pending.extend(parents.get(parent) or [])
    return found


def launchable(order: Iterable[str], parents: Dict[str, List[str]], stops: Iterable[str], passed: Iterable[str],
               launched: Iterable[str]) -> List[str]:
    """The protocols of a chain to launch now: not launched yet, and every stop before them passed."""
    stops, passed, launched = set(stops), set(passed), set(launched)
    return [pid for pid in order
            if pid not in launched and not ((_ancestors(pid, parents) & stops) - passed)]


# Linking a cut template to the project ----------------------------------------------------------------------------

FINISHED = "finished"


def suggestLinks(external: List[str], templateClasses: Dict[str, str], anchor: str, source: Dict[str, str],
                 ancestors: List[Dict[str, Any]], projectProtocols: List[Dict[str, Any]],
                 outputsOf, overrides: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Where each input a cut template takes from outside comes from in the project:
    [{templateRef, templateClass, projectRef (None when nothing is found), how}]. The anchor is the source the user
    named; the others, in this order: the same kind of protocol among the source's ancestors (the nearest), the
    same kind anywhere in the project (the newest finished), the same output among the ancestors (the nearest).
    overrides (template ref -> project ref) win."""
    overrides = overrides or {}
    byId = {str(row["protocolId"]): row for row in projectProtocols}
    nearest = [str(row["protocolId"]) for row in sorted(ancestors, key=lambda row: row["depth"])]

    def finishedWith(protocolId: str, output: str) -> bool:
        row = byId.get(protocolId)
        return bool(row) and str(row.get("status") or "").lower() == FINISHED and output in outputsOf(protocolId)

    newestFirst = sorted(byId, key=lambda pid: int(pid) if pid.isdigit() else 0, reverse=True)
    links = []
    for ref in external:
        templateId, output = ref.split(".", 1)
        base = output.split(".")[0]
        templateClass = templateClasses.get(templateId, "")
        found, how = None, ""
        if ref in overrides:
            found, how = overrides[ref], "chosen"
        elif ref == anchor:
            found, how = "%s.%s" % (source["protocolId"], source["output"]), "the source"
        else:
            for candidates, rule, sameClass in ((nearest, "an earlier step of the source", True),
                                                (newestFirst, "the same kind of protocol in the project", True),
                                                (nearest, "the same output in an earlier step", False)):
                hit = next((pid for pid in candidates
                            if (not sameClass or byId.get(pid, {}).get("className") == templateClass)
                            and finishedWith(pid, base)), None)
                if hit:
                    found, how = "%s.%s" % (hit, output), rule
                    break
        links.append({"templateRef": ref, "templateClass": templateClass, "projectRef": found, "how": how})
    return links
